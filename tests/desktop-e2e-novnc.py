#!/usr/bin/env python3
"""desktop-e2e-novnc.py — E2E renderu i WEJŚCIA pulpitu przez Hub → server-proxy → noVNC (#206, #277).

Dowodzi, że BADACZ widzi pulpit w PRZEGLĄDARCE (nie tylko że lokalny X wstaje — to pokrywa
tests/desktop-render-smoke.sh, #205) ORAZ że realne wejście (mysz/klawiatura) dociera do sesji.
Sterujemy headless Chromium przez Playwright: logowanie przez Hub, kafelek „Desktop" w Launcherze
JupyterLab, sesja jupyter-remote-desktop-proxy, canvas noVNC, wejście, resize, reconnect.

STAN: etap 2 (#277). Test RUNTIME — wymaga Playwrighta + Chromium w WARSTWIE TESTOWEJ
(nie w obrazie badacza) oraz osiągalnego Huba VM. Jak desktop-render-smoke.sh: samodzielny skrypt,
NIE wpięty w bramkującą akceptację (etap 5 uruchamia go nie-bramkująco; WLB_E2E_GATING=1 promuje
wynik do bramki). NIE dubluje copy-lockdown schowka/plików (#140).

Dlaczego krok interakcji jest teraz deterministyczny (#277):
  * noVNC 1.4.0 (jrdp 3.0.1) słucha mousedown/mouseup/mousemove NA CANVASIE i wysyła PointerEvent
    po WebSocket; `viewOnly` jest domyślnie wyłączony, więc wejście nie wymaga „grab".
  * Poprzednia próbka czytała tylko lewy-górny róg 200x200, a klik trafiał w ~(640,400) — menu
    xfdesktop powstawało POZA próbką, więc `before == after` było artefaktem pomiaru, nie brakiem
    transmisji. Teraz porównujemy PEŁNY bufor canvasu (z progiem na piksel i minimalną liczbą
    zmienionych pikseli), a zrzut robimy, ZANIM Escape zamknie menu.
  * Dodatkowo liczymy komunikaty RFB wysłane przez noVNC (PointerEvent/KeyEvent) — to dowód na
    poziomie protokołu, niezależny od pikseli; pozwala rozróżnić „zdarzenie nie dotarło do noVNC"
    od „noVNC wysłał, pulpit nie zareagował".

Uruchomienie (na VM testowej z zainstalowanym Playwrightem, jako badacz lub z dostępem do Huba):
    pip install playwright && python -m playwright install chromium
    WLB_E2E_HUB=https://localhost WLB_E2E_USER=u01 WLB_E2E_PASS="$(cat /root/wlb-hub-u01-initial-password)" \
        python3 tests/desktop-e2e-novnc.py

Parametry (env):
    WLB_E2E_HUB              baza Huba (domyślnie z HUB_TLS: https://localhost lub http://127.0.0.1)
    WLB_E2E_USER/PASS        konto badacza (np. u01) i hasło początkowe (plik /root/wlb-hub-<u>-initial-password)
    WLB_E2E_CA               ścieżka CA testowego (domyślnie /etc/wlb/hub-ca.pem przy HTTPS)
    WLB_E2E_TIMEOUT          deadline całości w s (domyślnie 180)
    WLB_E2E_ARTIFACT_DIR     katalog artefaktów (screenshot, console.log, result.json)
    WLB_E2E_INTERACTION      required (domyślnie) | optional (raportuj bez bramkowania) | off (pomiń krok 4)
    WLB_E2E_MIN_CHANGED_PX   ile pikseli musi się zmienić, by uznać reakcję pulpitu (domyślnie 200)

Kody wyjścia: 0 = pulpit renderuje (i reaguje, chyba że WLB_E2E_INTERACTION=optional/off);
              1 = błąd środowiska/logowania/startu; 2 = błąd E2E (brak kafelka, pusty canvas,
              brak reakcji na wejście).
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import time

SCHEMA = "wlb.desktop-e2e-novnc/v2"
PIXEL_DELTA = 24  # próg na piksel (suma |ΔR|+|ΔG|+|ΔB|) — toleruje szum dekodowania Tight/JPEG
SAMPLE_POINTS = 24000  # globalna siatka próbkowania canvasu do diagnostyki („nie-pusty", hash)


def _fail(dir_: pathlib.Path, code: int, reason: str, **extra) -> None:
    """Zapisz result.json i wyjdź danym kodem (zawsze wypisz ścieżkę wyniku)."""
    out = {"schema": SCHEMA, "status": "pass" if code == 0 else "fail", "reason": reason, **extra}
    dir_.mkdir(parents=True, exist_ok=True)
    rp = dir_ / "result.json"
    rp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"desktop-e2e: wynik: {rp} ({reason})")
    sys.exit(code)


def _hub_default() -> str:
    """Scheme Huba jak w tests/lib/remote-common.sh: HUB_TLS=0 → HTTP, inaczej HTTPS."""
    try:
        labenv = pathlib.Path("/etc/wlb/lab.env").read_text(encoding="utf-8")
        for line in labenv.splitlines():
            if line.strip() == "HUB_TLS=0":
                return "http://127.0.0.1"
    except OSError:
        pass
    return "https://localhost"


# --- canvas: wspólne wykrycie elementu (jrdp/noVNC, także shadow DOM) ----------------------------
# jrdp /desktop/ montuje noVNC w #screen; noVNC dokłada osobny canvas kursora na body — stąd
# zawężenie do #screen i fallback na największy canvas. OBECNOŚĆ wykrywamy NIEZALEŻNIE od rozmiaru:
# RFB ustawia wymiary dopiero po połączeniu VNC, więc 0×0 przez pierwsze sekundy to NIE „brak canvasu".
_JS_PICK_CANVAS = r"""
  const pick = (root) => {
    if (!root || !root.querySelector) return null;
    return root.querySelector('#screen canvas')
        || root.querySelector('canvas.noVNC_canvas')
        || (root.getElementById && root.getElementById('noVNC_canvas'))
        || root.querySelector('canvas');
  };
  let canvas = pick(document);
  if (!canvas) {
    for (const host of document.querySelectorAll('*')) {
      if (host.shadowRoot) { canvas = pick(host.shadowRoot); if (canvas) break; }
    }
  }
"""


def _js(body: str) -> str:
    """Snippet JS: wspólne wykrycie canvasu + treść (jedno miejsce utrzymania selektorów)."""
    return "() => {\n" + _JS_PICK_CANVAS + body + "\n}"


# Pola: present = element istnieje; found = gotowy do próbkowania (niezerowy i czytelny).
# colors/luminance/hash liczone z siatki rozłożonej po CAŁYM buforze (nie z rogu 200×200).
_CANVAS_PROBE_JS = _js(
    r"""
  if (!canvas) return {present: false, found: false};
  const w = canvas.width | 0, h = canvas.height | 0;
  const rect = canvas.getBoundingClientRect();
  const info = {
    present: true, w, h,
    cssW: Math.round(rect.width * 10) / 10, cssH: Math.round(rect.height * 10) / 10,
    left: Math.round(rect.left * 10) / 10, top: Math.round(rect.top * 10) / 10,
    viewportW: window.innerWidth, viewportH: window.innerHeight,
  };
  if (w < 2 || h < 2) return Object.assign(info, {found: false, sized: false});
  const ctx = canvas.getContext('2d');
  if (!ctx) return Object.assign(info, {found: false, readable: false});
  let data;
  try {
    data = ctx.getImageData(0, 0, w, h).data;
  } catch (err) {
    return Object.assign(info, {found: false, readable: false, error: String(err)});
  }
  const step = Math.max(1, Math.floor(Math.sqrt((w * h) / @SAMPLES@)));
  const seen = new Set();
  let sum = 0, n = 0, hash = 0x811c9dc5;
  for (let y = 0; y < h; y += step) {
    for (let x = 0; x < w; x += step) {
      const i = (y * w + x) * 4;
      const rgb = (data[i] << 16) | (data[i + 1] << 8) | data[i + 2];
      seen.add(rgb);
      sum += data[i] + data[i + 1] + data[i + 2];
      hash = Math.imul(hash ^ rgb, 0x01000193) >>> 0;
      n += 1;
    }
  }
  // Widoczny fragment canvasu — tam klikamy. jrdp startuje z geometrią 1680x1050, czyli canvas
  // bywa WIĘKSZY niż okno przeglądarki (1280x800 minus pasek noVNC); klikamy środek części widocznej.
  const vx = Math.max(rect.left, 0), vy = Math.max(rect.top, 0);
  const vw = Math.max(0, Math.min(rect.right, window.innerWidth) - vx);
  const vh = Math.max(0, Math.min(rect.bottom, window.innerHeight) - vy);
  const cx = vx + vw / 2, cy = vy + vh / 2;
  const at = document.elementFromPoint(cx, cy);
  return Object.assign(info, {
    found: true, readable: true,
    colors: seen.size, luminance: n ? Math.round(sum / n) : 0, hash,
    step, sampled: n,
    visible: {left: Math.round(vx), top: Math.round(vy), w: Math.round(vw), h: Math.round(vh)},
    click: {
      viewportX: Math.round(cx), viewportY: Math.round(cy),
      canvasX: Math.round(cx - rect.left), canvasY: Math.round(cy - rect.top),
    },
    atClick: at ? {tag: at.tagName, id: at.id || '', isCanvas: at === canvas} : null,
  });
""".replace("@SAMPLES@", str(SAMPLE_POINTS))
)

# Zrzut pełnego bufora do pamięci strony — diff liczymy W PRZEGLĄDARCE (nie serializujemy 7 MB).
_SNAPSHOT_JS = _js(
    r"""
  if (!canvas) return {ok: false, reason: 'brak canvasu'};
  const w = canvas.width | 0, h = canvas.height | 0;
  if (w < 2 || h < 2) return {ok: false, reason: 'canvas 0x0'};
  const ctx = canvas.getContext('2d');
  if (!ctx) return {ok: false, reason: 'brak kontekstu 2d'};
  let img;
  try {
    img = ctx.getImageData(0, 0, w, h);
  } catch (err) {
    return {ok: false, reason: String(err)};
  }
  window.__wlbSnap = {w, h, data: img.data, at: Date.now()};
  return {ok: true, w, h};
"""
)

# Różnica względem _SNAPSHOT_JS: liczba zmienionych pikseli + bounding box (gdzie zadziałało wejście).
_DIFF_JS = _js(
    r"""
  const snap = window.__wlbSnap;
  if (!canvas) return {ok: false, reason: 'brak canvasu'};
  if (!snap) return {ok: false, reason: 'brak snapshotu'};
  const w = canvas.width | 0, h = canvas.height | 0;
  if (w !== snap.w || h !== snap.h) {
    return {ok: false, resized: true, w, h, snapW: snap.w, snapH: snap.h};
  }
  const ctx = canvas.getContext('2d');
  if (!ctx) return {ok: false, reason: 'brak kontekstu 2d'};
  let cur;
  try {
    cur = ctx.getImageData(0, 0, w, h).data;
  } catch (err) {
    return {ok: false, reason: String(err)};
  }
  const prev = snap.data;
  let changed = 0, bx0 = w, by0 = h, bx1 = -1, by1 = -1;
  for (let p = 0, i = 0; p < w * h; p += 1, i += 4) {
    const d = Math.abs(cur[i] - prev[i]) + Math.abs(cur[i + 1] - prev[i + 1])
            + Math.abs(cur[i + 2] - prev[i + 2]);
    if (d > @DELTA@) {
      changed += 1;
      const x = p % w, y = (p / w) | 0;
      if (x < bx0) bx0 = x;
      if (x > bx1) bx1 = x;
      if (y < by0) by0 = y;
      if (y > by1) by1 = y;
    }
  }
  const total = w * h;
  return {
    ok: true, w, h, changed, total,
    ratio: Math.round((changed / total) * 1e6) / 1e6,
    bbox: bx1 >= 0 ? {x: bx0, y: by0, w: bx1 - bx0 + 1, h: by1 - by0 + 1} : null,
  };
""".replace("@DELTA@", str(PIXEL_DELTA))
)

# Dowód na poziomie protokołu RFB: opakowujemy WebSocket.send i liczymy komunikaty klienta
# (5 = PointerEvent, 6 B; 4 = KeyEvent, 8 B) oraz zdarzenia DOM dochodzące do canvasu.
_PROBE_JS = _js(
    r"""
  if (!canvas) return {installed: false, reason: 'brak canvasu'};
  if (window.__wlbProbe) return Object.assign({installed: true, reused: true}, window.__wlbProbe.state());
  const counts = {send: 0, pointer: 0, key: 0, other: 0, lastPointer: null, lastKey: null};
  const events = {
    mousedown: 0, mouseup: 0, mousemove: 0, contextmenu: 0, click: 0,
    keydown: 0, keyup: 0, pointerdown: 0, pointerup: 0,
  };
  const state = () => ({
    send: counts.send, pointer: counts.pointer, key: counts.key, other: counts.other,
    lastPointer: counts.lastPointer, lastKey: counts.lastKey,
    events: Object.assign({}, events),
    canvas: {w: canvas.width | 0, h: canvas.height | 0},
  });
  const send = WebSocket.prototype.send;
  WebSocket.prototype.send = function (data) {
    counts.send += 1;
    try {
      let b = null;
      if (data instanceof ArrayBuffer) b = new Uint8Array(data);
      else if (ArrayBuffer.isView(data)) b = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
      if (b && b.length === 6 && b[0] === 5) {
        counts.pointer += 1;
        counts.lastPointer = {x: (b[2] << 8) | b[3], y: (b[4] << 8) | b[5], mask: b[1]};
      } else if (b && b.length === 8 && b[0] === 4) {
        counts.key += 1;
        counts.lastKey = {down: b[1] === 1, keysym: ((b[4] << 24) | (b[5] << 16) | (b[6] << 8) | b[7]) >>> 0};
      } else {
        counts.other += 1;
      }
    } catch (err) { /* diagnostyka nigdy nie może psuć wejścia */ }
    return send.apply(this, arguments);
  };
  for (const name of Object.keys(events)) {
    canvas.addEventListener(name, () => { events[name] += 1; }, {capture: true, passive: true});
  }
  window.__wlbProbe = {state};
  return Object.assign({installed: true, reused: false}, state());
"""
)


def _canvas_locator(desktop):
    """Lokator canvasu noVNC — Playwright liczy `position` względem elementu (bez ręcznego offsetu)."""
    for sel in ("#screen canvas", "canvas.noVNC_canvas", "#noVNC_canvas", "canvas"):
        loc = desktop.locator(sel).first
        try:
            found = loc.count() > 0 and loc.bounding_box() is not None
        except Exception:  # strona mogła się zamknąć/przeładować w trakcie
            found = False
        if found:
            return loc
    return None


def _probe_state(desktop) -> dict:
    """Stan liczników RFB/DOM (instaluje opakowanie WebSocket.send przy pierwszym wywołaniu)."""
    return desktop.evaluate(_PROBE_JS)


def _wait_settled(desktop, deadline: float, settle: float = 1.0) -> dict:
    """Czeka, aż canvas będzie gotowy i STABILNY (noVNC resizeSession zmienia rozmiar po połączeniu)."""
    probe: dict = {"present": False, "found": False}
    prev: tuple | None = None
    stable_since = 0.0
    while time.monotonic() < deadline:
        probe = desktop.evaluate(_CANVAS_PROBE_JS)
        if probe.get("found"):
            key = (probe.get("w"), probe.get("h"), probe.get("left"), probe.get("top"))
            if key == prev:
                stable_since = stable_since or time.monotonic()
                if time.monotonic() - stable_since >= settle:
                    return probe
            else:
                prev, stable_since = key, 0.0
        time.sleep(0.3)
    return probe


def _wait_diff(desktop, timeout: float, min_changed: int) -> tuple[dict, float]:
    """Czeka na różnicę ≥ min_changed; przy zmianie rozmiaru bufora odświeża baseline."""
    t0 = time.monotonic()
    last: dict = {"ok": False}
    while True:
        last = desktop.evaluate(_DIFF_JS)
        elapsed = time.monotonic() - t0
        if last.get("ok") and last.get("changed", 0) >= min_changed:
            return last, elapsed
        if elapsed >= timeout:
            return last, elapsed
        if last.get("resized"):
            desktop.evaluate(_SNAPSHOT_JS)  # resizeSession przebudował bufor — nowy baseline
        time.sleep(0.3)


def _interact(desktop, probe: dict, art: pathlib.Path, left, min_changed: int) -> dict:
    """Krok 4 (#277): wymuś realną reakcję pulpitu i zmierz ją deterministycznie.

    Reakcja = niepusta różnica na PEŁNYM canvasie (nie w rogu 200×200) po realnym wejściu.
    Mierzymy też komunikaty RFB wysłane przez noVNC, żeby odróżnić brak transmisji od braku reakcji.
    """
    out: dict = {"min_changed_px": min_changed, "canvas": {k: probe.get(k) for k in ("w", "h", "cssW", "cssH")}}
    start = _probe_state(desktop)
    pos = {"x": probe["click"]["canvasX"], "y": probe["click"]["canvasY"]}
    out["click"] = {
        "canvas_px": pos,
        "viewport_px": {"x": probe["click"]["viewportX"], "y": probe["click"]["viewportY"]},
        "expected_framebuffer": {
            "x": round(pos["x"] * probe["w"] / max(probe["cssW"], 1)),
            "y": round(pos["y"] * probe["h"] / max(probe["cssH"], 1)),
        },
        "at_click": probe.get("atClick"),
    }

    canvas = _canvas_locator(desktop)
    if canvas is None:
        out.update({"reacted": False, "error": "brak lokatora canvasu"})
        return out

    # Hover PRZED bazowym zrzutem: samo najechanie może podświetlić element (hover/tooltip), więc
    # nie może zostać policzone jako reakcja na klik.
    canvas.hover(position=pos, timeout=min(left(), 15) * 1000)
    time.sleep(0.4)
    desktop.evaluate(_SNAPSHOT_JS)
    time.sleep(0.5)
    idle = desktop.evaluate(_DIFF_JS)  # dryf tła bez wejścia (animacje, zegar)
    out["idle_diff"] = idle
    out["baseline_stable"] = bool(idle.get("ok") and idle.get("changed", 0) < min_changed)

    desktop.evaluate(_SNAPSHOT_JS)  # świeży baseline tuż przed prawym klikiem
    canvas.click(position=pos, button="right", timeout=min(left(), 15) * 1000)
    menu, elapsed = _wait_diff(desktop, min(left(), 6.0), min_changed)
    out["right_click"] = {"diff": menu, "elapsed_s": round(elapsed, 2)}
    out["after_click"] = _probe_state(desktop)

    reacted = bool(menu.get("ok") and menu.get("changed", 0) >= min_changed)
    source = "right-click" if reacted else None
    if reacted:
        # Zrzut ZANIM Escape zamknie menu — wcześniej robiliśmy go po Escape i dlatego był „czysty".
        desktop.screenshot(path=str(art / "interaction-after.png"))

    # Escape zamyka menu i jednocześnie mierzy ścieżkę klawiatury (w noVNC osobna od myszy).
    keys_before = _probe_state(desktop)
    desktop.keyboard.press("Escape")
    time.sleep(0.4)
    keys_after = _probe_state(desktop)
    out["keyboard"] = {
        "keysym_msgs": keys_after.get("key", 0) - keys_before.get("key", 0),
        "last": keys_after.get("lastKey"),
    }

    if not reacted:
        # Fallback: zaznaczenie prostokątem na pulpicie (xfdesktop rysuje je TYLKO podczas trzymania
        # przycisku — dlatego diff robimy PRZED mouse.up(), a nie po).
        vis = probe["visible"]
        ax = round(vis["left"] + vis["w"] * 0.30)
        ay = round(vis["top"] + vis["h"] * 0.30)
        bx = round(vis["left"] + vis["w"] * 0.65)
        by = round(vis["top"] + vis["h"] * 0.65)
        canvas.hover(position={"x": ax - probe["left"], "y": ay - probe["top"]}, timeout=min(left(), 15) * 1000)
        time.sleep(0.3)
        desktop.evaluate(_SNAPSHOT_JS)
        desktop.mouse.down()
        desktop.mouse.move(bx, by, steps=12)
        time.sleep(0.3)
        drag = desktop.evaluate(_DIFF_JS)
        desktop.mouse.up()
        time.sleep(0.3)
        released = desktop.evaluate(_DIFF_JS)
        out["drag"] = {
            "from": {"x": ax, "y": ay},
            "to": {"x": bx, "y": by},
            "diff": drag,
            "after_release": released,
        }
        if drag.get("ok") and drag.get("changed", 0) >= min_changed:
            reacted, source = True, "drag"
            desktop.screenshot(path=str(art / "interaction-after.png"))

    end = _probe_state(desktop)
    out["transmitted"] = {
        "pointer_msgs": end.get("pointer", 0) - start.get("pointer", 0),
        "key_msgs": end.get("key", 0) - start.get("key", 0),
        "events": end.get("events"),
        "last_pointer": end.get("lastPointer"),
        "last_key": end.get("lastKey"),
    }
    out["reacted"] = reacted
    out["source"] = source
    return out


def _interaction_reason(interaction: dict) -> str:
    """Czytelny powód porażki — najpierw rozstrzygamy: brak transmisji czy brak reakcji pulpitu."""
    if interaction.get("error"):
        return f"interakcja niemożliwa: {interaction['error']}"
    sent = interaction.get("transmitted") or {}
    if sent.get("pointer_msgs", 0) == 0:
        return (
            "brak reakcji pulpitu I brak PointerEvent z noVNC — zdarzenia myszy nie dotarły do canvasu "
            f"(events={sent.get('events')}, canvas={interaction.get('canvas')})"
        )
    changed = ((interaction.get("right_click") or {}).get("diff") or {}).get("changed", 0)
    return (
        "noVNC wysłał PointerEvent, ale pulpit nie zmienił obrazu "
        f"(last_pointer={sent.get('last_pointer')}, changed={changed}, próg={interaction.get('min_changed_px')})"
    )


def main() -> None:
    _art_env = os.environ.get("WLB_E2E_ARTIFACT_DIR", "")
    art = pathlib.Path(_art_env) if _art_env else pathlib.Path(tempfile.mkdtemp(prefix="wlb-e2e-"))
    hub = os.environ.get("WLB_E2E_HUB") or _hub_default()
    user = os.environ.get("WLB_E2E_USER", "")
    passwd = os.environ.get("WLB_E2E_PASS", "")
    art.mkdir(parents=True, exist_ok=True)
    deadline = float(os.environ.get("WLB_E2E_TIMEOUT", "180"))
    interaction_mode = os.environ.get("WLB_E2E_INTERACTION", "required").strip().lower()
    try:
        min_changed = int(os.environ.get("WLB_E2E_MIN_CHANGED_PX", "200"))
    except ValueError:
        _fail(art, 1, "WLB_E2E_MIN_CHANGED_PX nie jest liczbą")
    if interaction_mode not in ("required", "optional", "off"):
        _fail(art, 1, f"WLB_E2E_INTERACTION={interaction_mode!r} — dozwolone: required|optional|off")
    if not user or not passwd:
        _fail(art, 1, "brak WLB_E2E_USER/WLB_E2E_PASS")

    try:
        from playwright.sync_api import TimeoutError as PwTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        _fail(art, 1, "brak Playwrighta w warstwie testowej (pip install playwright; playwright install chromium)")

    console_errors: list[str] = []
    t0 = time.monotonic()

    def left() -> float:
        return max(1.0, deadline - (time.monotonic() - t0))

    with sync_playwright() as p:  # type: ignore[name-defined]
        browser = p.chromium.launch(headless=True, args=["--ignore-certificate-errors"])
        ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)

        try:
            # 1. Logowanie przez Hub (Native Authenticator: formularz username/password).
            page.goto(f"{hub}/hub/login", wait_until="domcontentloaded", timeout=left() * 1000)
            page.fill("input[name='username']", user)
            page.fill("input[name='password']", passwd)
            page.click("input[type='submit'], button[type='submit']")
            # Po zalogowaniu hub spawnuje serwer i przekierowuje do /user/<user>/lab.
            page.wait_for_url("**/user/**", timeout=left() * 1000)

            # 2. Launcher → kafelek „Desktop" (LINK). jrdp otwiera pulpit w NOWEJ karcie, więc
            #    PRZECHWYTUJEMY nową stronę (popup) i dalej próbkujemy JĄ, nie Launcher — inaczej canvas
            #    nigdy się nie znajdzie (SKIP/FAIL). FALLBACK: bezpośredni goto /user/<user>/desktop/
            #    (ten sam widok noVNC bez klikania kafelka), gdy kafelek niewidoczny / nie otworzył karty.
            desktop = None
            try:
                tile = page.get_by_role("link", name="Desktop")
                tile.wait_for(timeout=min(left(), 30) * 1000)
                with ctx.expect_page(timeout=min(left(), 30) * 1000) as popup_info:
                    tile.click()
                desktop = popup_info.value
                desktop.wait_for_load_state("domcontentloaded", timeout=left() * 1000)
            except PwTimeoutError:
                desktop = None
            if desktop is None:
                desktop = ctx.new_page()
                desktop.goto(f"{hub}/user/{user}/desktop/", wait_until="domcontentloaded", timeout=left() * 1000)
            desktop.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)

            # 3. Sesja server-proxy: canvas noVNC na stronie pulpitu. jrdp montuje noVNC w #screen; RFB
            #    ustawia wymiary DOPIERO po połączeniu VNC, więc przez pierwsze sekundy canvas bywa 0×0.
            #    Czekamy dwufazowo: najpierw element (present), potem niezerowy i niepusty (found). (#206)
            deadline_canvas = time.monotonic() + min(left(), 90)
            sample = {"present": False, "found": False}
            ever_present = False
            while time.monotonic() < deadline_canvas:
                sample = desktop.evaluate(_CANVAS_PROBE_JS)
                ever_present = ever_present or bool(sample.get("present"))
                if sample.get("found") and sample.get("readable") and sample.get("colors", 0) > 2:
                    break
                time.sleep(1.5)
            if not sample.get("found"):
                # Zrzut + struktura DOM pozwalają zdiagnozować BEZ dostępu do VM (#206): rozróżniamy
                # "elementu canvas w ogóle nie ma" od "jest, ale 0×0" (VNC nie połączył / pulpit nie wstał).
                desktop.screenshot(path=str(art / "canvas-missing.png"))
                (art / "desktop.html").write_text(desktop.content(), encoding="utf-8")
                reason = (
                    "canvas #screen obecny, ale 0×0/nieczytelny — VNC nie połączył w czasie (pulpit nie wystartował?)"
                    if ever_present
                    else "brak elementu canvas #screen (kafelek/proxy nie wystawił pulpitu)"
                )
                _fail(art, 2, reason, hub=hub, sample=sample, console_errors=console_errors[:20])
            if sample.get("colors", 0) <= 2:
                desktop.screenshot(path=str(art / "canvas-empty.png"))
                _fail(
                    art, 2, "canvas pusty/jednolity (czarny ekran)", sample=sample, console_errors=console_errors[:20]
                )

            # 4. Interakcja (#277) — dowód, że wejście DOCIERA i pulpit REAGUJE. Domyślnie wymagana;
            #    WLB_E2E_INTERACTION=optional zostawia raport bez bramkowania, =off pomija krok.
            interaction: dict = {"mode": interaction_mode}
            if interaction_mode != "off":
                settled = _wait_settled(desktop, time.monotonic() + min(left(), 20))
                if not settled.get("found"):
                    _fail(art, 2, "canvas nie ustabilizował się przed interakcją", sample=settled)
                interaction.update(_interact(desktop, settled, art, left, min_changed))
                if interaction.get("reacted"):
                    diff = (interaction.get("right_click") or {}).get("diff") or {}
                    if interaction.get("source") == "drag":
                        diff = ((interaction.get("drag") or {}).get("diff")) or {}
                    sent = interaction.get("transmitted") or {}
                    print(
                        f"desktop-e2e: interakcja OK ({interaction.get('source')}): "
                        f"changed={diff.get('changed')}px bbox={diff.get('bbox')} "
                        f"pointer_msgs={sent.get('pointer_msgs')} key_msgs={sent.get('key_msgs')}"
                    )
                else:
                    print(f"desktop-e2e: interakcja NIE potwierdzona — {_interaction_reason(interaction)}")
                    desktop.screenshot(path=str(art / "interaction-failed.png"))
                    if interaction_mode == "required":
                        (art / "console.log").write_text("\n".join(console_errors), encoding="utf-8")
                        _fail(
                            art,
                            2,
                            _interaction_reason(interaction),
                            hub=hub,
                            sample=sample,
                            interaction=interaction,
                            console_errors=console_errors[:20],
                        )

            # 5. Resize + reconnect (regresja: po zmianie rozmiaru i ponownym połączeniu canvas dalej żyje).
            desktop.set_viewport_size({"width": 1024, "height": 768})
            time.sleep(2)
            desktop.reload(wait_until="domcontentloaded", timeout=left() * 1000)
            reconn = {"found": False}
            d2 = time.monotonic() + min(left(), 45)
            while time.monotonic() < d2:
                reconn = desktop.evaluate(_CANVAS_PROBE_JS)
                if reconn.get("found") and reconn.get("colors", 0) > 2:
                    break
                time.sleep(1.5)
            if reconn.get("colors", 0) <= 2:
                _fail(art, 2, "reconnect: canvas nie wrócił", reconn=reconn, console_errors=console_errors[:20])

            art.mkdir(parents=True, exist_ok=True)
            desktop.screenshot(path=str(art / "desktop-ok.png"))
            (art / "console.log").write_text("\n".join(console_errors), encoding="utf-8")
            _fail(
                art,
                0,
                "pulpit renderuje (Hub→proxy→noVNC) i reaguje na wejście"
                if interaction.get("reacted")
                else f"pulpit renderuje; interakcja niepotwierdzona ({interaction_mode})",
                hub=hub,
                sample=sample,
                interaction=interaction,
                interaction_reacted=interaction.get("reacted"),
                reconnect=reconn,
            )
        finally:
            ctx.close()
            browser.close()


if __name__ == "__main__":
    main()

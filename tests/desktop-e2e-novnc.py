#!/usr/bin/env python3
"""desktop-e2e-novnc.py — E2E renderu i WEJŚCIA pulpitu przez Hub → server-proxy → noVNC (#206, #277).

Dowodzi, że BADACZ widzi pulpit w PRZEGLĄDARCE (nie tylko że lokalny X wstaje — to pokrywa
tests/desktop-render-smoke.sh, #205) ORAZ że realne wejście (mysz/klawiatura) dociera do sesji.
Sterujemy headless Chromium przez Playwright: logowanie przez Hub, kafelek „Desktop” w Launcherze
JupyterLaba, sesja jupyter-remote-desktop-proxy, canvas noVNC, wejście, resize, reconnect.

RDZEŃ #277-B: bramką NIE jest diff pikseli ani licznik WebSocket.send, tylko SKUTEK wejścia
odczytany OUT-OF-BAND z systemu plików VM:
  * klawiatura — test wpisuje świeży nonce realną ścieżką klawiatury (keyboard.type + Enter),
    a root czyta /run/wlb/e2e/keyboard.txt i porównuje nonce;
  * mysz — test klika KONKRETNY przycisk targetu (geometria z /run/wlb/e2e/target.json,
    odświeżona tuż przed akcją), a root czyta /run/wlb/e2e/mouse.txt i wymaga rc=0.

Katalog markerów czyści się PRZED każdą akcją (jako root, lokalnie lub przez WLB_E2E_SSH).
Diff pełnego canvasu i liczniki RFB zostają WYŁĄCZNIE diagnostyką w result.json — nigdy warunkiem
pass. Progu diffu nie kalibrujemy (#277).

Scenariusze są rozstrzygane niezależnie: launcher / render / pointer / keyboard / resize /
reconnect. Mysz OK nie zalicza klawiatury. Brak kafelka Desktop to FAIL scenariusza „launcher”,
nie globalny `goto` na /desktop/.

TLS: realne zaufanie do testowego CA (WLB_E2E_CA) przez NSS Chromium + `certutil -A -t C,,`.
Nie używamy --ignore-certificate-errors ani ignore_https_errors; zły/niezaufany cert = ERROR.

Uruchomienie (runner z warstwą testową; u01 tworzy akceptacja, hasło czyta root):
    WLB_E2E_HUB=https://localhost:8443 WLB_E2E_USER=u01 \\
    WLB_E2E_PASS="$(sudo cat /root/wlb-hub-u01-initial-password)" \\
    WLB_E2E_SSH="ssh -q -o StrictHostKeyChecking=no -i build/test/id_ed25519 -p 2222 wlbadmin@127.0.0.1" \\
    WLB_E2E_CA="$PWD/build/test/siem-ca.pem" \\
        python3 tests/desktop-e2e-novnc.py

Parametry (env):
    WLB_E2E_HUB              baza Huba (domyślnie z HUB_TLS: https://localhost lub http://127.0.0.1)
    WLB_E2E_USER/PASS        konto badacza (np. u01) i hasło początkowe
    WLB_E2E_SSH              opcjonalna komenda SSH na VM (markery /run/wlb/e2e); bez niej test
                             działa lokalnie i wymaga roota lub `sudo -n`
    WLB_E2E_CA               CA testowego Huba (PEM); przy HTTPS bez zaufanego CA test kończy ERROR
    WLB_E2E_DESKTOP          required (domyślnie) | absent — czy flavor ma pulpit (baza: absent)
    WLB_E2E_INTERACTION      required (domyślnie) | optional (raport bez bramkowania) | off (NOT_RUN)
    WLB_E2E_TIMEOUT          deadline całości w s (domyślnie 300)
    WLB_E2E_ARTIFACT_DIR     katalog artefaktów (result.json, screenshoty, console.log)

Kody wyjścia: 0 = wynik zgodny z kontraktem; 1 = błąd środowiska/konfiguracji (VM, TLS,
Playwright, fixture targetu); 2 = bramkowany scenariusz FAIL.
"""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
import re
import shlex
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import traceback
import uuid

SCHEMA = "wlb.desktop-e2e-novnc/v3"
TARGET_SCHEMA = "wlb.e2e-target/v1"
CANVAS_SELECTOR = "#screen canvas"
MARKER_DIR = "/run/wlb/e2e"
SAMPLE_POINTS = 24000  # diagnostyka „nie-pusty” canvasu (siatka po całym buforze)
PIXEL_DELTA = 24  # próg na piksel w diagnostyce diffu — NIE warunek pass
SCENARIO_ORDER = ("launcher", "render", "pointer", "keyboard", "resize", "reconnect")
DESKTOP_TILE_RE = re.compile(r"^\s*Desktop(\s*\[[^\]]*\])?\s*$")


class ConfigError(Exception):
    """Błąd środowiska/konfiguracji — wynik ERROR (rc=1), nie FAIL produktu."""


class DeadlineExceeded(ConfigError):
    """Przekroczony monotoniczny deadline całości."""


class ScenarioFailure(Exception):
    """Bramkowany scenariusz nie przeszedł — wynik FAIL (rc=2)."""


class Deadline:
    """Jeden monotoniczny deadline na cały przebieg; każda operacja bierze z niego limit."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.started = time.monotonic()
        self.ended = self.started + seconds

    def left(self) -> float:
        return max(0.0, self.ended - time.monotonic())

    def check(self) -> None:
        if self.left() <= 0:
            raise DeadlineExceeded(f"przekroczono WLB_E2E_TIMEOUT={self.seconds:.0f}s")

    def ms(self, cap: float = 15.0) -> int:
        """Timeout Playwrighta w ms, przycięty do pozostałego deadline'u."""
        self.check()
        return max(1, int(min(cap, self.left()) * 1000))

    def sleep(self, seconds: float) -> None:
        self.check()
        time.sleep(min(seconds, self.left()))


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


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _truncate(text: str, limit: int = 400) -> str:
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= limit else text[:limit] + "…"


def _parse_mouse_rc(text: str) -> int | None:
    """Kontrakt mouse.txt: `rc=0` w linii albo JSON `{\"rc\": 0, ...}`."""
    stripped = text.strip()
    match = re.fullmatch(r"rc\s*=\s*(-?\d+)", stripped)
    if match:
        return int(match.group(1))
    with contextlib.suppress(json.JSONDecodeError):
        data = json.loads(stripped)
        if isinstance(data, dict) and "rc" in data:
            try:
                return int(data["rc"])
            except (TypeError, ValueError):
                return None
    return None


def _validate_target(data: object) -> dict:
    """Waliduje /run/wlb/e2e/target.json (kontrakt #277-A) i zwraca znormalizowany słownik."""
    if not isinstance(data, dict):
        raise ConfigError("target.json: oczekiwano obiektu JSON")
    if data.get("schema") != TARGET_SCHEMA:
        raise ConfigError(f"target.json: schema={data.get('schema')!r}, oczekiwano {TARGET_SCHEMA!r}")
    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ConfigError("target.json: brak niepustego session_id")
    screen = data.get("screen")
    if not isinstance(screen, dict):
        raise ConfigError("target.json: brak obiektu screen {w,h}")
    try:
        screen_w, screen_h = int(screen["w"]), int(screen["h"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError("target.json: screen wymaga liczb w,h") from exc
    if screen_w <= 0 or screen_h <= 0:
        raise ConfigError("target.json: screen.w/screen.h muszą być dodatnimi liczbami")
    button = data.get("button")
    if not isinstance(button, dict):
        raise ConfigError("target.json: brak obiektu button {x,y,w,h}")
    try:
        bx, by, bw, bh = int(button["x"]), int(button["y"]), int(button["w"]), int(button["h"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError("target.json: button wymaga liczb x,y,w,h") from exc
    if bw <= 0 or bh <= 0:
        raise ConfigError("target.json: button.w/button.h muszą być dodatnie")
    keyboard = data.get("keyboard") if isinstance(data.get("keyboard"), dict) else {}
    return {
        "schema": TARGET_SCHEMA,
        "session_id": session_id,
        "screen": {"w": screen_w, "h": screen_h},
        "button": {"x": bx, "y": by, "w": bw, "h": bh},
        "keyboard": {"title": str(keyboard.get("title", ""))},
    }


class Vm:
    """Dostęp do systemu plików VM jako root: lokalnie (sudo -n) albo przez WLB_E2E_SSH."""

    def __init__(self, ssh_command: str, clock: Deadline) -> None:
        self.ssh = shlex.split(ssh_command) if ssh_command else []
        self.local = not self.ssh
        self.clock = clock
        self.sudo = [] if self.local and os.geteuid() == 0 else ["sudo", "-n"]

    def _argv(self, script: str) -> list[str]:
        if self.local:
            return [*self.sudo, "/bin/sh", "-c", script]
        remote = f"sudo -n /bin/sh -c {shlex.quote(script)}"
        return [*self.ssh, remote]

    def run(self, script: str, timeout: float = 20.0, check: bool = False) -> subprocess.CompletedProcess[str]:
        self.clock.check()
        limit = max(1.0, min(timeout, self.clock.left()))
        try:
            done = subprocess.run(  # noqa: S603 - argv z konfiguracji, bez shell=True
                self._argv(script),
                capture_output=True,
                text=True,
                timeout=limit,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            where = "SSH" if self.ssh else "lokalnie"
            raise ConfigError(f"VM ({where}): nie udało się wykonać polecenia: {exc}") from exc
        if check and done.returncode != 0:
            detail = _truncate((done.stderr or done.stdout or "").strip())
            raise ConfigError(f"VM: polecenie zakończone rc={done.returncode}: {detail}")
        return done

    def check(self) -> None:
        done = self.run("id -u", timeout=15)
        if done.returncode != 0:
            detail = _truncate((done.stderr or done.stdout or "").strip())
            where = "WLB_E2E_SSH" if self.ssh else "sudo -n lokalnie"
            raise ConfigError(f"brak roota na VM ({where}): {detail}")
        if done.stdout.strip() != "0":
            raise ConfigError(f"markery /run/wlb/e2e wymagają roota, otrzymano uid={done.stdout.strip()!r}")

    def clean(self) -> None:
        """Czyści katalog markerów PRZED każdą akcją; fixture odtwarza target.json."""
        done = self.run(f"rm -rf -- {MARKER_DIR}/*; mkdir -p -- {MARKER_DIR}", timeout=15)
        if done.returncode != 0:
            raise ConfigError(f"nie udało się wyczyścić {MARKER_DIR}: {_truncate(done.stderr.strip())}")

    def read(self, name: str) -> str | None:
        path = f"{MARKER_DIR}/{name}"
        done = self.run(f"if [ -f {path} ]; then cat {path}; else exit 3; fi", timeout=15)
        if done.returncode == 3:
            return None
        if done.returncode != 0:
            raise ConfigError(f"odczyt {path} nie powiódł się: {_truncate(done.stderr.strip())}")
        return done.stdout

    def wait_marker(self, name: str, seconds: float) -> str | None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.clock.check()
            text = self.read(name)
            if text is not None:
                return text
            self.clock.sleep(0.3)
        return None

    def target(self, seconds: float = 20.0) -> dict:
        """Czeka na odtworzenie target.json po czyszczeniu i waliduje kontrakt."""
        end = time.monotonic() + seconds
        last_error = ""
        while time.monotonic() < end:
            self.clock.check()
            text = self.read("target.json")
            if text is not None:
                try:
                    return _validate_target(json.loads(text))
                except json.JSONDecodeError:
                    last_error = "target.json nie jest poprawnym JSON"
                except ConfigError as exc:
                    last_error = str(exc)
            self.clock.sleep(0.3)
        detail = f" ({last_error})" if last_error else ""
        raise ConfigError(
            f"fixture targetu nie odtworzyła {MARKER_DIR}/target.json w {seconds:.0f}s{detail} — "
            "target in-session z #277-A nie działa"
        )


# --- canvas: jednoznaczny selektor #screen canvas (bez fallbacku na dowolny canvas) ---------------
_CANVAS_PROBE_JS = (
    r"""
() => {
  const all = document.querySelectorAll('@SEL@');
  if (all.length !== 1) return {count: all.length, present: all.length > 0, found: false};
  const canvas = all[0];
  const w = canvas.width | 0, h = canvas.height | 0;
  const rect = canvas.getBoundingClientRect();
  const info = {
    count: 1, present: true, w, h,
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
  return Object.assign(info, {
    found: true, readable: true,
    colors: seen.size, luminance: n ? Math.round(sum / n) : 0, hash,
    step, sampled: n,
  });
}
""".replace("@SEL@", CANVAS_SELECTOR)
    .replace("@SAMPLES@", str(SAMPLE_POINTS))
)

_SNAPSHOT_JS = (
    r"""
() => {
  const canvas = document.querySelector('@SEL@');
  if (!canvas) return {ok: false, reason: 'brak @SEL@'};
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
}
""".replace("@SEL@", CANVAS_SELECTOR)
)

_DIFF_JS = (
    r"""
() => {
  const canvas = document.querySelector('@SEL@');
  if (!canvas) return {ok: false, reason: 'brak @SEL@'};
  const snap = window.__wlbSnap;
  if (!snap) return {ok: false, reason: 'brak snapshotu'};
  const w = canvas.width | 0, h = canvas.height | 0;
  if (w !== snap.w || h !== snap.h) return {ok: false, resized: true, w, h};
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
}
""".replace("@SEL@", CANVAS_SELECTOR)
    .replace("@DELTA@", str(PIXEL_DELTA))
)

# Diagnostyka RFB/DOM (NIGDY bramka): opakowany WebSocket.send liczy PointerEvent/KeyEvent,
# a listenery na canvasie pokazują, czy zdarzenia przeglądarki w ogóle doszły do noVNC.
_RFB_INSTALL_JS = (
    r"""
() => {
  const canvas = document.querySelector('@SEL@');
  if (!canvas) return {installed: false, reason: 'brak @SEL@'};
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
    } catch (err) { /* diagnostyka nie może psuć wejścia */ }
    return send.apply(this, arguments);
  };
  for (const name of Object.keys(events)) {
    canvas.addEventListener(name, () => { events[name] += 1; }, {capture: true, passive: true});
  }
  window.__wlbProbe = {state};
  return Object.assign({installed: true, reused: false}, state());
}
""".replace("@SEL@", CANVAS_SELECTOR)
)

_RFB_STATE_JS = "() => window.__wlbProbe ? window.__wlbProbe.state() : {installed: false}"

_FOCUS_JS = (
    r"""
() => {
  const canvas = document.querySelector('@SEL@');
  if (!canvas) return {ok: false, reason: 'brak @SEL@'};
  try {
    canvas.focus({preventScroll: true});
  } catch (err) {
    return {ok: false, active: false, error: String(err)};
  }
  return {ok: true, active: document.activeElement === canvas};
}
""".replace("@SEL@", CANVAS_SELECTOR)
)


def _show_launcher(page, clock: Deadline) -> bool:
    """Aktywuj kartę Launchera — po otwarciu notebooka kafelki przestają być widoczne."""
    if page.locator(".jp-Launcher:visible").count():
        return True
    tab = page.locator("#jp-main-dock-panel .lm-TabBar-tab", has_text="Launcher").first
    with contextlib.suppress(Exception):
        if tab.count():
            tab.click(timeout=clock.ms(10))
    with contextlib.suppress(Exception):
        page.wait_for_selector(".jp-Launcher:visible", timeout=clock.ms(20))
    return page.locator(".jp-Launcher:visible").count() > 0


def _launcher_labels(page) -> list[str]:
    with contextlib.suppress(Exception):
        return [text.strip() for text in page.locator(".jp-LauncherCard-label").all_inner_texts()][:40]
    return []


class E2E:
    def __init__(self, cfg: dict, art: pathlib.Path) -> None:
        self.cfg = cfg
        self.art = art
        self.clock = Deadline(cfg["timeout"])
        self.vm = Vm(cfg["ssh"], self.clock)
        self.page = None
        self.desktop = None
        self.console_errors: list[str] = []
        self.top_error = ""
        self.started = time.monotonic()
        self.result: dict = {
            "schema": SCHEMA,
            "status": "error",
            "reason": "test nie zakończył się",
            "hub": cfg["hub"],
            "desktop": cfg["desktop"],
            "interaction": cfg["interaction"],
            "started_at": _iso_now(),
            "duration_s": 0,
            "scenarios": {},
            "console_errors": [],
            "artifacts": [],
        }
        for name in SCENARIO_ORDER:
            gating = cfg["desktop"] == "required" and (
                name in ("launcher", "render", "resize", "reconnect")
                or (name in ("pointer", "keyboard") and cfg["interaction"] == "required")
            )
            self.result["scenarios"][name] = {
                "status": "not_run",
                "gating": gating,
                "reason": "scenariusz nie uruchomiony",
            }

    # --- wynik ------------------------------------------------------------------------------------
    def scenario(self, name: str, status: str, reason: str, gating: bool | None = None, **details: object) -> None:
        entry = self.result["scenarios"][name]
        entry.update({"status": status, "reason": reason})
        if gating is not None:
            entry["gating"] = gating
        entry.update(details)
        print(f"desktop-e2e: {name}: {status.upper()} — {reason}")

    def skip_downstream(self, reason: str) -> None:
        for name in ("render", "pointer", "keyboard", "resize", "reconnect"):
            if self.result["scenarios"][name]["status"] == "not_run":
                self.scenario(name, "not_run", f"pominięty: {reason}")

    def artifact(self, name: str) -> None:
        if name not in self.result["artifacts"]:
            self.result["artifacts"].append(name)

    def finalize(self) -> int:
        scenarios = self.result["scenarios"]
        fails = [n for n in SCENARIO_ORDER if scenarios[n]["status"] == "fail" and scenarios[n]["gating"]]
        errors = [n for n in SCENARIO_ORDER if scenarios[n]["status"] == "error" and scenarios[n]["gating"]]
        advisory = [
            n
            for n in SCENARIO_ORDER
            if scenarios[n]["status"] in ("fail", "error") and not scenarios[n]["gating"]
        ]
        self.result["duration_s"] = round(time.monotonic() - self.started, 1)
        self.result["console_errors"] = self.console_errors[:40]
        if self.top_error:
            self.result["status"] = "error"
            self.result["reason"] = self.top_error
            code = 1
        elif fails:
            self.result["status"] = "fail"
            self.result["reason"] = "; ".join(f"{n}: {scenarios[n]['reason']}" for n in fails[:3])
            code = 2
        elif errors:
            self.result["status"] = "error"
            self.result["reason"] = "; ".join(f"{n}: {scenarios[n]['reason']}" for n in errors[:3])
            code = 1
        else:
            self.result["status"] = "pass"
            if self.cfg["desktop"] == "absent":
                self.result["reason"] = "flavor bez pulpitu: brak kafelka Desktop (WLB_E2E_DESKTOP=absent)"
            elif self.cfg["interaction"] == "off":
                self.result["reason"] = "pulpit renderuje; interakcja wyłączona (WLB_E2E_INTERACTION=off)"
            else:
                self.result["reason"] = (
                    "pulpit renderuje; pointer/keyboard/resize/reconnect potwierdzone markerami /run/wlb/e2e"
                )
            if advisory:
                self.result["reason"] += " (tryb raportowy: " + ", ".join(advisory) + ")"
            code = 0
        path = self.art / "result.json"
        path.write_text(json.dumps(self.result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"desktop-e2e: wynik: {path} ({self.result['status']}: {self.result['reason']})")
        return code

    # --- przygotowanie ---------------------------------------------------------------------------
    def _prepare_tls(self) -> dict[str, str] | None:
        """Buduje tymczasowy NSS DB z CA testowego; Chromium ufa mu bez flag ignorujących TLS."""
        ca_path = self.cfg["ca"]
        if not ca_path:
            if self.cfg["hub"].startswith("https://"):
                print("desktop-e2e: HTTPS bez WLB_E2E_CA — używam systemowego zaufania Chromium")
            return None
        ca = pathlib.Path(ca_path)
        if not ca.is_file():
            raise ConfigError(f"WLB_E2E_CA={ca} nie istnieje")
        try:
            ssl.create_default_context(cafile=str(ca))
        except (OSError, ssl.SSLError) as exc:
            raise ConfigError(f"WLB_E2E_CA={ca} nie jest poprawnym certyfikatem PEM: {exc}") from exc
        certutil = shutil.which("certutil")
        if not certutil:
            raise ConfigError(
                "brak certutil (libnss3-tools) — ci/install-tools.sh e2e instaluje go na runnerze; "
                "bez niego nie da się zaufać WLB_E2E_CA bez --ignore-certificate-errors"
            )
        home = pathlib.Path(tempfile.mkdtemp(prefix="wlb-e2e-home-"))
        db = home / ".pki" / "nssdb"
        db.mkdir(parents=True)
        done = subprocess.run(  # noqa: S603 - certutil z PATH, argv bez shell=True
            [certutil, "-d", f"sql:{db}", "-A", "-t", "C,,", "-n", "wlb-e2e-ca", "-i", str(ca)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if done.returncode != 0:
            raise ConfigError(f"certutil nie dodał CA: {_truncate((done.stderr or done.stdout).strip())}")
        env = {"HOME": str(home)}
        # Nadpisane HOME gubi domyślny cache przeglądarek Playwrighta — wskaż realny katalog.
        browsers = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(pathlib.Path.home() / ".cache" / "ms-playwright")
        if pathlib.Path(browsers).is_dir():
            env["PLAYWRIGHT_BROWSERS_PATH"] = browsers
        self.result["tls"] = {"ca": str(ca), "nssdb": "sql:<tmp>/.pki/nssdb", "certutil": certutil}
        return env

    def _hook(self, page) -> None:
        def on_console(message) -> None:
            if message.type == "error":
                self.console_errors.append(_truncate(message.text, 300))

        page.on("console", on_console)
        page.on("pageerror", lambda exc: self.console_errors.append(_truncate(f"pageerror: {exc}", 300)))

    def _save_screenshot(self, page, name: str) -> None:
        with contextlib.suppress(Exception):
            page.screenshot(path=str(self.art / name), timeout=self.clock.ms(10))
            self.artifact(name)

    def _release_input(self, page) -> None:
        if page is None:
            return
        with contextlib.suppress(Exception):
            page.mouse.up()
        for key in ("Shift", "Control", "Alt", "Meta"):
            with contextlib.suppress(Exception):
                page.keyboard.up(key)

    # --- akcje na pulpicie -----------------------------------------------------------------------
    def _wait_canvas(self, page, seconds: float) -> dict:
        end = time.monotonic() + seconds
        last: dict = {"count": 0, "found": False}
        while time.monotonic() < end:
            self.clock.check()
            try:
                last = page.evaluate(_CANVAS_PROBE_JS)
            except Exception:
                # nawigacja/reload potrafi zniszczyć kontekst JS — to nie jest wynik testu
                last = {"count": 0, "found": False, "transient": True}
                self.clock.sleep(0.5)
                continue
            if last.get("count", 0) > 1:
                raise ConfigError(f"niejednoznaczny canvas: {CANVAS_SELECTOR} występuje {last['count']}×")
            if last.get("found") and last.get("readable") and last.get("colors", 0) > 2:
                return last
            self.clock.sleep(0.5)
        return last

    def _target(self, seconds: float = 20.0) -> dict | None:
        try:
            return self.vm.target(seconds)
        except ConfigError as exc:
            if self.cfg["interaction"] == "off":
                print(f"desktop-e2e: target niedostępny (interakcja off): {exc}")
                return None
            raise

    def _fit_viewport(self, page, target: dict) -> None:
        """Headless viewport musi pokazać cały canvas, inaczej klik w przycisk może być poza ekranem."""
        width = max(1280, target["screen"]["w"])
        height = max(800, target["screen"]["h"] + 60)
        current = page.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})")
        if current.get("w") != width or current.get("h") != height:
            page.set_viewport_size({"width": width, "height": height})
            self.clock.sleep(1.0)

    def _type_nonce(self, page, nonce: str, label: str) -> dict:
        """Realna ścieżka klawiatury: fokus strony → keydown/keyup per znak → Enter."""
        page.bring_to_front()
        focus = page.evaluate(_FOCUS_JS)
        before = page.evaluate(_RFB_STATE_JS)
        page.keyboard.type(nonce, delay=20)
        page.keyboard.press("Enter")
        self.clock.sleep(0.8)
        after = page.evaluate(_RFB_STATE_JS)
        return {
            "label": label,
            "nonce": nonce,
            "focus": focus,
            "rfb": {
                "key_msgs": after.get("key", 0) - before.get("key", 0),
                "send": after.get("send", 0) - before.get("send", 0),
                "events": after.get("events"),
                "last_key": after.get("lastKey"),
            },
        }

    def _keyboard_marker(self, page, label: str) -> dict:
        nonce = str(uuid.uuid4())
        self.vm.clean()
        details = self._type_nonce(page, nonce, label)
        raw = self.vm.wait_marker("keyboard.txt", 20)
        if raw is None:
            raise ScenarioFailure(
                f"klawiatura ({label}): po wpisaniu nonce i Enter nie powstał {MARKER_DIR}/keyboard.txt "
                f"(RFB key_msgs={details['rfb']['key_msgs']}, events={(details['rfb']['events'] or {}).get('keydown')})"
            )
        text = raw.rstrip("\r\n")
        details["marker"] = _truncate(text, 200)
        if text != nonce:
            raise ScenarioFailure(f"klawiatura ({label}): keyboard.txt={text[:80]!r} != nonce {nonce!r}")
        details["marker_ok"] = True
        return details

    def _click_pointer_marker(self, page, target: dict) -> dict:
        nonce = target["session_id"]
        probe = page.evaluate(_CANVAS_PROBE_JS)
        if probe.get("count") != 1 or not probe.get("found"):
            raise ScenarioFailure(f"pointer: brak jednoznacznego canvasu {CANVAS_SELECTOR} (probe={probe})")
        screen, button = target["screen"], target["button"]
        if (probe["w"], probe["h"]) != (screen["w"], screen["h"]):
            raise ConfigError(
                f"pointer: bufor canvasu {probe['w']}x{probe['h']} != target.screen "
                f"{screen['w']}x{screen['h']} — target.json nie opisuje tej sesji"
            )
        canvas = page.locator(CANVAS_SELECTOR)
        box = canvas.bounding_box()
        if box is None or box["width"] <= 0 or box["height"] <= 0:
            raise ScenarioFailure("pointer: canvas nie ma mierzalnego prostokąta")
        center_x = button["x"] + button["w"] / 2
        center_y = button["y"] + button["h"] / 2
        pos_x = center_x * box["width"] / screen["w"]
        pos_y = center_y * box["height"] / screen["h"]
        if not (0 <= pos_x < box["width"] and 0 <= pos_y < box["height"]):
            raise ScenarioFailure(
                f"pointer: środek przycisku ({center_x:.0f},{center_y:.0f}) wypada poza canvasem "
                f"({box['width']:.0f}x{box['height']:.0f})"
            )
        state_before = page.evaluate(_RFB_STATE_JS)
        page.evaluate(_SNAPSHOT_JS)
        page.mouse.move(box["x"] + pos_x, box["y"] + pos_y)
        page.mouse.down()
        page.mouse.up()
        self.clock.sleep(1.0)
        diff = page.evaluate(_DIFF_JS)
        state_after = page.evaluate(_RFB_STATE_JS)
        raw = self.vm.wait_marker("mouse.txt", 20)
        diagnostics = {
            "click": {
                "screen": {"x": round(center_x, 1), "y": round(center_y, 1)},
                "canvas_css": {"x": round(pos_x, 1), "y": round(pos_y, 1)},
                "canvas_buffer": {"w": probe["w"], "h": probe["h"]},
                "canvas_box": {k: round(v, 1) for k, v in box.items()},
                "session_id": nonce,
            },
            "diff": diff,
            "rfb": {
                "pointer_msgs": state_after.get("pointer", 0) - state_before.get("pointer", 0),
                "send": state_after.get("send", 0) - state_before.get("send", 0),
                "events": state_after.get("events"),
                "last_pointer": state_after.get("lastPointer"),
            },
        }
        if raw is None:
            raise ScenarioFailure(
                f"pointer: klik w przycisk targetu nie utworzył {MARKER_DIR}/mouse.txt "
                f"(RFB pointer_msgs={diagnostics['rfb']['pointer_msgs']}, "
                f"events={(diagnostics['rfb']['events'] or {}).get('mousedown')})",
                diagnostics,
            )
        rc = _parse_mouse_rc(raw)
        diagnostics["marker"] = _truncate(raw.strip(), 200)
        if rc is None:
            raise ScenarioFailure(f"pointer: mouse.txt bez rc (treść={_truncate(raw.strip(), 120)!r})", diagnostics)
        if rc != 0:
            raise ScenarioFailure(f"pointer: mouse.txt rc={rc} (oczekiwano 0)", diagnostics)
        return diagnostics

    # --- scenariusze -----------------------------------------------------------------------------
    def _login(self, page) -> None:
        try:
            page.goto(f"{self.cfg['hub']}/hub/login", wait_until="domcontentloaded", timeout=self.clock.ms(30))
        except DeadlineExceeded:
            raise
        except Exception as exc:
            text = str(exc)
            if "ERR_CERT" in text:
                raise ConfigError(
                    f"TLS: Chromium nie ufa certyfikatowi Huba ({text.splitlines()[0][:160]}); "
                    "ustaw WLB_E2E_CA na CA testowego lub sprawdź certyfikat Huba"
                ) from exc
            raise ConfigError(f"Hub {self.cfg['hub']} nie odpowiada: {text.splitlines()[0][:160]}") from exc
        page.fill("input[name='username']", self.cfg["user"], timeout=self.clock.ms(15))
        page.fill("input[name='password']", self.cfg["pass"], timeout=self.clock.ms(10))
        page.click("input[type='submit'], button[type='submit']", timeout=self.clock.ms(15))
        try:
            page.wait_for_url("**/user/**", timeout=self.clock.ms(90))
        except DeadlineExceeded:
            raise
        except Exception as exc:
            head = str(exc).splitlines()[0][:160]
            raise ConfigError(f"logowanie u01 nie przekierowało do JupyterLaba: {head}") from exc

    def _open_desktop(self, context, page):
        """Launcher → kafelek Desktop. Osobny, wymagany scenariusz — bez `goto` na /desktop/."""
        required = self.cfg["desktop"] == "required"
        try:
            page.wait_for_selector("#jp-main-dock-panel", timeout=self.clock.ms(90))
        except DeadlineExceeded:
            raise
        except Exception as exc:
            raise ScenarioFailure(f"JupyterLab nie wczytał się po logowaniu: {str(exc).splitlines()[0][:160]}") from exc
        if not _show_launcher(page, self.clock):
            raise ScenarioFailure("Launcher JupyterLaba nie jest dostępny")
        tile = page.get_by_role("link", name=DESKTOP_TILE_RE)
        count = tile.count()
        visible = False
        if count:
            with contextlib.suppress(Exception):
                visible = tile.first.is_visible()
        if not required:
            if visible:
                raise ScenarioFailure("WLB_E2E_DESKTOP=absent, a Launcher wystawia kafelek Desktop (regresja lekkości)")
            self.scenario(
                "launcher",
                "pass",
                "flavor bez pulpitu: brak kafelka Desktop (WLB_E2E_DESKTOP=absent)",
                labels=_launcher_labels(page),
            )
            self.skip_downstream("flavor bez pulpitu (WLB_E2E_DESKTOP=absent)")
            return None
        if not visible:
            raise ScenarioFailure(f"brak kafelka Desktop w Launcherze (kafelki={_launcher_labels(page)})")
        same_tab = False
        pages_before = set(context.pages)
        desktop = None
        try:
            with context.expect_page(timeout=self.clock.ms(30)) as popup_info:
                tile.first.click(timeout=self.clock.ms(20))
            desktop = popup_info.value
        except DeadlineExceeded:
            raise
        except Exception as exc:
            new_pages = [candidate for candidate in context.pages if candidate not in pages_before]
            if new_pages:
                desktop = new_pages[0]
            elif "/desktop" in page.url:
                desktop = page
                same_tab = True
            else:
                raise ScenarioFailure(
                    f"kafelek Desktop nie otworzył pulpitu (url={page.url}, błąd={str(exc).splitlines()[0][:120]})"
                ) from exc
        desktop.bring_to_front()
        with contextlib.suppress(Exception):
            desktop.wait_for_load_state("domcontentloaded", timeout=self.clock.ms(30))
        if "/desktop" not in desktop.url:
            raise ScenarioFailure(f"kafelek Desktop otworzył stronę bez pulpitu (url={desktop.url})")
        self._hook(desktop)
        self.scenario(
            "launcher",
            "pass",
            "Launcher → kafelek Desktop otworzył sesję pulpitu" + (" (ta sama karta)" if same_tab else " (nowa karta)"),
            url=desktop.url,
            same_tab=same_tab,
        )
        return desktop

    def _run_render(self, page, target: dict | None) -> dict:
        probe = self._wait_canvas(page, min(90.0, self.clock.left()))
        if probe.get("count") == 0:
            self._save_screenshot(page, "canvas-missing.png")
            with contextlib.suppress(Exception):
                (self.art / "desktop.html").write_text(page.content(), encoding="utf-8")
                self.artifact("desktop.html")
            raise ScenarioFailure(f"brak elementu {CANVAS_SELECTOR} (kafelek/proxy nie wystawił pulpitu)")
        if not probe.get("found"):
            self._save_screenshot(page, "canvas-not-ready.png")
            raise ScenarioFailure(f"canvas {CANVAS_SELECTOR} obecny, ale niegotowy (0×0/nieczytelny): {probe}")
        if probe.get("colors", 0) <= 2:
            self._save_screenshot(page, "canvas-empty.png")
            raise ScenarioFailure(f"canvas pusty/jednolity (czarny ekran): colors={probe.get('colors')}")
        details: dict = {"sample": probe}
        if target is not None:
            details["screen_match"] = (probe["w"], probe["h"]) == (target["screen"]["w"], target["screen"]["h"])
        self.scenario(
            "render",
            "pass",
            f"pulpit renderuje: canvas {probe['w']}×{probe['h']}, kolorów {probe['colors']}",
            **details,
        )
        return probe

    def _run_pointer(self, page, target: dict | None) -> None:
        if self.cfg["interaction"] == "off":
            self.scenario("pointer", "not_run", "interakcja wyłączona (WLB_E2E_INTERACTION=off)")
            return
        if target is None:
            self.scenario("pointer", "error", f"brak fixture {MARKER_DIR}/target.json (target #277-A)")
            return
        try:
            self.vm.clean()
            fresh = self.vm.target(20)
            details = self._click_pointer_marker(page, fresh)
        except ScenarioFailure as exc:
            extra = exc.args[1] if len(exc.args) > 1 and isinstance(exc.args[1], dict) else {}
            self.scenario("pointer", "fail", str(exc.args[0]), **extra)
            return
        except ConfigError as exc:
            self.scenario("pointer", "error", str(exc))
            return
        self.scenario("pointer", "pass", "klik w przycisk targetu → mouse.txt rc=0", **details)

    def _run_keyboard(self, page) -> None:
        if self.cfg["interaction"] == "off":
            self.scenario("keyboard", "not_run", "interakcja wyłączona (WLB_E2E_INTERACTION=off)")
            return
        try:
            details = self._keyboard_marker(page, "keyboard")
        except ScenarioFailure as exc:
            self.scenario("keyboard", "fail", str(exc.args[0]))
            return
        except ConfigError as exc:
            self.scenario("keyboard", "error", str(exc))
            return
        self.scenario("keyboard", "pass", "nonce wpisany klawiaturą + Enter → keyboard.txt zgodny", **details)

    def _run_resize(self, page) -> None:
        before = page.evaluate(_CANVAS_PROBE_JS)
        page.set_viewport_size({"width": 1024, "height": 768})
        end = time.monotonic() + min(30.0, self.clock.left())
        after = before
        while time.monotonic() < end:
            self.clock.check()
            after = page.evaluate(_CANVAS_PROBE_JS)
            changed = (after.get("cssW"), after.get("cssH")) != (before.get("cssW"), before.get("cssH")) or (
                after.get("w"),
                after.get("h"),
            ) != (before.get("w"), before.get("h"))
            if after.get("found") and after.get("colors", 0) > 2 and changed:
                break
            self.clock.sleep(0.5)
        details = {"before": before, "after": after, "post_resize_input": None}
        if not after.get("found") or after.get("colors", 0) <= 2:
            self.scenario("resize", "fail", f"po zmianie viewportu canvas nie wrócił: {after}", **details)
            return
        if before.get("w") != after.get("w") or before.get("h") != after.get("h"):
            details["framebuffer_changed"] = {
                "from": [before.get("w"), before.get("h")],
                "to": [after.get("w"), after.get("h")],
            }
        if self.cfg["interaction"] == "off":
            self.scenario("resize", "pass", "canvas żyje po zmianie viewportu (interakcja off)", **details)
            return
        try:
            details["post_resize_input"] = self._keyboard_marker(page, "resize")
        except ScenarioFailure as exc:
            self.scenario(
                "resize",
                "fail",
                f"wejście po resize: {exc.args[0]}",
                gating=False if self.cfg["interaction"] == "optional" else None,
                **details,
            )
            return
        except ConfigError as exc:
            self.scenario("resize", "error", f"wejście po resize: {exc}", **details)
            return
        self.scenario("resize", "pass", "canvas żyje i przyjmuje klawiaturę po zmianie viewportu", **details)

    def _run_reconnect(self, page, target: dict | None) -> None:
        session_before = target["session_id"] if target else None
        try:
            if self.cfg["interaction"] != "off":
                self.vm.clean()
        except ConfigError as exc:
            self.scenario("reconnect", "error", f"czyszczenie markerów przed reconnectem: {exc}")
            return
        try:
            page.reload(wait_until="domcontentloaded", timeout=self.clock.ms(30))
        except DeadlineExceeded:
            raise
        except Exception as exc:
            self.scenario("reconnect", "fail", f"reload pulpitu nie powiódł się: {str(exc).splitlines()[0][:160]}")
            return
        if "/desktop" not in page.url:
            self.scenario("reconnect", "fail", f"po reloadzie strona nie jest pulpiterm (url={page.url})")
            return
        try:
            probe = self._wait_canvas(page, min(60.0, self.clock.left()))
        except ConfigError as exc:
            self.scenario("reconnect", "error", str(exc))
            return
        details: dict = {"sample": probe, "session_id_before": session_before, "session_id_after": None}
        if not probe.get("found") or probe.get("colors", 0) <= 2:
            self._save_screenshot(page, "reconnect-failed.png")
            self.scenario("reconnect", "fail", f"po reconnect canvas nie wrócił: {probe}", **details)
            return
        try:
            fresh = self.vm.target(20)
        except ConfigError as exc:
            if self.cfg["interaction"] == "off":
                self.scenario("reconnect", "pass", "canvas wrócił po reloadzie (interakcja off)", **details)
                return
            self.scenario("reconnect", "error", str(exc), **details)
            return
        details["session_id_after"] = fresh["session_id"]
        if session_before is not None and fresh["session_id"] != session_before:
            self.scenario(
                "reconnect",
                "fail",
                f"sesja X została odtworzona: session_id {session_before} → {fresh['session_id']}",
                **details,
            )
            return
        if self.cfg["interaction"] == "off":
            self.scenario("reconnect", "pass", "ta sama sesja X i canvas po reloadzie (interakcja off)", **details)
            return
        try:
            details["post_reconnect_input"] = self._keyboard_marker(page, "reconnect")
        except ScenarioFailure as exc:
            self.scenario(
                "reconnect",
                "fail",
                f"wejście po reconnect: {exc.args[0]}",
                gating=False if self.cfg["interaction"] == "optional" else None,
                **details,
            )
            return
        except ConfigError as exc:
            self.scenario("reconnect", "error", f"wejście po reconnect: {exc}", **details)
            return
        self.scenario("reconnect", "pass", "ta sama sesja X i klawiatura działa po reloadzie", **details)

    def _run_desktop(self, context, page) -> None:
        try:
            desktop = self._open_desktop(context, page)
        except ScenarioFailure as exc:
            self.scenario("launcher", "fail", str(exc.args[0]))
            self.skip_downstream("launcher nie przeszedł")
            return
        if desktop is None:
            return
        self.desktop = desktop
        target = None
        fixture_error = ""
        try:
            target = self._target(15)
        except ConfigError as exc:
            fixture_error = str(exc)
            print(f"desktop-e2e: fixture targetu: {fixture_error}")
        if target is not None:
            self._fit_viewport(desktop, target)
        try:
            self._run_render(desktop, target)
        except ScenarioFailure as exc:
            self.scenario("render", "fail", str(exc.args[0]))
            self.skip_downstream("render nie przeszedł")
            return
        with contextlib.suppress(Exception):
            page_eval = desktop.evaluate(_RFB_INSTALL_JS)
            self.result["rfb_probe"] = {"installed": page_eval.get("installed"), "reason": page_eval.get("reason")}
        # Najpierw wszystkie akcje klawiatury (target klawiatury ma focus w X), potem klik myszą:
        # klik w zenity może przejąć focus X i nie może fałszować wyniku klawiatury.
        self._run_keyboard(desktop)
        self._run_resize(desktop)
        self._run_reconnect(desktop, target)
        if self.cfg["interaction"] == "off":
            self._run_pointer(desktop, None)
        elif target is None:
            self.scenario("pointer", "error", fixture_error or f"brak fixture {MARKER_DIR}/target.json")
        else:
            self._run_pointer(desktop, target)

    # --- przebieg --------------------------------------------------------------------------------
    def execute(self) -> int:
        try:
            self.vm.check()
            nss_env = self._prepare_tls()
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:
                raise ConfigError(
                    "brak Playwrighta w warstwie testowej (ci/install-tools.sh e2e; venv-e2e)"
                ) from exc
            browser_env = {**os.environ, **nss_env} if nss_env else None
            with sync_playwright() as pw:
                launch_args = ["--disable-dev-shm-usage"]
                browser = pw.chromium.launch(headless=True, args=launch_args, env=browser_env)
                context = browser.new_context(viewport={"width": 1280, "height": 800})
                page = context.new_page()
                self.page = page
                self._hook(page)
                try:
                    self._login(page)
                    self._run_desktop(context, page)
                finally:
                    self._release_input(self.desktop)
                    if self.desktop is not None:
                        self._save_screenshot(self.desktop, "desktop-final.png")
                    (self.art / "console.log").write_text("\n".join(self.console_errors), encoding="utf-8")
                    self.artifact("console.log")
                    with contextlib.suppress(Exception):
                        context.close()
                    with contextlib.suppress(Exception):
                        browser.close()
        except DeadlineExceeded as exc:
            self.top_error = str(exc)
        except ConfigError as exc:
            self.top_error = str(exc)
        except Exception as exc:  # nieznany błąd nie może zgubić result.json
            self.top_error = f"nieoczekiwany błąd: {type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
            with contextlib.suppress(Exception):
                (self.art / "traceback.log").write_text(traceback.format_exc(), encoding="utf-8")
                self.artifact("traceback.log")
        finally:
            self.result["duration_s"] = round(time.monotonic() - self.started, 1)
        return self.finalize()


def _load_config(art: pathlib.Path) -> dict:
    hub = (os.environ.get("WLB_E2E_HUB") or _hub_default()).rstrip("/")
    user = os.environ.get("WLB_E2E_USER", "")
    password = os.environ.get("WLB_E2E_PASS", "")
    desktop = os.environ.get("WLB_E2E_DESKTOP", "required").strip().lower()
    interaction = os.environ.get("WLB_E2E_INTERACTION", "required").strip().lower()
    if desktop not in ("required", "absent"):
        raise ConfigError(f"WLB_E2E_DESKTOP={desktop!r} — dozwolone: required|absent")
    if interaction not in ("required", "optional", "off"):
        raise ConfigError(f"WLB_E2E_INTERACTION={interaction!r} — dozwolone: required|optional|off")
    if not user or not password:
        raise ConfigError("brak WLB_E2E_USER/WLB_E2E_PASS")
    try:
        timeout = float(os.environ.get("WLB_E2E_TIMEOUT", "300"))
    except ValueError as exc:
        raise ConfigError("WLB_E2E_TIMEOUT nie jest liczbą") from exc
    if timeout <= 0:
        raise ConfigError("WLB_E2E_TIMEOUT musi być dodatni")
    return {
        "hub": hub,
        "user": user,
        "pass": password,
        "desktop": desktop,
        "interaction": interaction,
        "timeout": timeout,
        "ssh": os.environ.get("WLB_E2E_SSH", "").strip(),
        "ca": os.environ.get("WLB_E2E_CA", "").strip(),
        "artifacts": art,
    }


def _write_result(art: pathlib.Path, result: dict) -> None:
    art.mkdir(parents=True, exist_ok=True)
    path = art / "result.json"
    tmp = art / "result.json.tmp"
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    art_env = os.environ.get("WLB_E2E_ARTIFACT_DIR", "")
    art = pathlib.Path(art_env) if art_env else pathlib.Path(tempfile.mkdtemp(prefix="wlb-e2e-"))
    art.mkdir(parents=True, exist_ok=True)
    try:
        cfg = _load_config(art)
    except ConfigError as exc:
        result = {
            "schema": SCHEMA,
            "status": "error",
            "reason": str(exc),
            "hub": os.environ.get("WLB_E2E_HUB", ""),
            "desktop": os.environ.get("WLB_E2E_DESKTOP", "required"),
            "interaction": os.environ.get("WLB_E2E_INTERACTION", "required"),
            "started_at": _iso_now(),
            "duration_s": 0,
            "scenarios": {},
            "console_errors": [],
            "artifacts": [],
        }
        _write_result(art, result)
        print(f"desktop-e2e: wynik: {art / 'result.json'} (error: {exc})")
        return 1
    return E2E(cfg, art).execute()


if __name__ == "__main__":
    sys.exit(main())

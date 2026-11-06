#!/usr/bin/env python3
"""desktop-e2e-novnc.py — E2E renderu pulpitu przez Hub → server-proxy → noVNC (#206).

Dowodzi, że BADACZ widzi pulpit w PRZEGLĄDARCE (nie tylko że lokalny X wstaje — to pokrywa
tests/desktop-render-smoke.sh, #205). Sterujemy headless Chromium przez Playwright: logowanie przez
Hub, kafelek „Desktop" w Launcherze JupyterLab, sesja jupyter-remote-desktop-proxy, canvas noVNC,
wejście, resize, reconnect.

STAN: scaffold etapu 1 (#206). Test RUNTIME — wymaga Playwrighta + Chromium w WARSTWIE TESTOWEJ
(nie w obrazie badacza) oraz osiągalnego Huba VM. Jak desktop-render-smoke.sh: samodzielny skrypt,
NIE wpięty w bramkującą akceptację do czasu stabilizacji (promocja przez osobny fragment acceptance.d,
nie-bramkująco jak #138). NIE dubluje copy-lockdown schowka/plików (#140).

Uruchomienie (na VM testowej z zainstalowanym Playwrightem, jako badacz lub z dostępem do Huba):
    pip install playwright && python -m playwright install chromium
    WLB_E2E_HUB=https://localhost WLB_E2E_USER=u01 WLB_E2E_PASS="$(cat /root/wlb-hub-u01-initial-password)" \
        python3 tests/desktop-e2e-novnc.py

Parametry (env):
    WLB_E2E_HUB            baza Huba (domyślnie z HUB_TLS: https://localhost lub http://127.0.0.1)
    WLB_E2E_USER/PASS      konto badacza (np. u01) i hasło początkowe (plik /root/wlb-hub-<u>-initial-password)
    WLB_E2E_CA             ścieżka CA testowego (domyślnie /etc/wlb/hub-ca.pem przy HTTPS)
    WLB_E2E_TIMEOUT        deadline całości w s (domyślnie 180)
    WLB_E2E_ARTIFACT_DIR   katalog artefaktów (screenshot, console.log, result.json)

Kody wyjścia: 0 = pulpit renderuje i reaguje; 1 = błąd środowiska/logowania/startu; 2 = błąd E2E
(brak kafelka, pusty canvas, brak reakcji na wejście).
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import time

SCHEMA = "wlb.desktop-e2e-novnc/v1"


def _fail(dir_: pathlib.Path, code: int, reason: str, **extra) -> None:
    """Zapisz result.json i wyjdź danym kodem (zawsze wypisz ścieżkę wyniku)."""
    out = {"schema": SCHEMA, "status": "ok" if code == 0 else "fail", "reason": reason, **extra}
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


# --- nie-pusty canvas: próbkuj piksele w przeglądarce (odrzuć czarny/jednolity ekran) ----------
_CANVAS_SAMPLE_JS = r"""
() => {
  // noVNC ≥1.0: canvas#noVNC_canvas (czasem w shadow DOM UI). Szukamy najpierw po id, potem dowolny
  // canvas o niezerowych wymiarach na stronie/iframe.
  const find = (root) => {
    let c = root.getElementById ? root.getElementById('noVNC_canvas') : null;
    if (c) return c;
    const all = root.querySelectorAll ? root.querySelectorAll('canvas') : [];
    for (const el of all) if (el.width > 1 && el.height > 1) return el;
    return null;
  };
  let c = find(document);
  if (!c) {
    // przeszukaj shadow roots
    for (const host of document.querySelectorAll('*')) {
      if (host.shadowRoot) { c = find(host.shadowRoot); if (c) break; }
    }
  }
  if (!c) return {found: false};
  const ctx = c.getContext('2d');
  if (!ctx) return {found: true, readable: false, w: c.width, h: c.height};
  const w = c.width, h = c.height;
  const data = ctx.getImageData(0, 0, Math.min(w, 200), Math.min(h, 200)).data;
  const seen = new Set();
  let sum = 0;
  for (let i = 0; i < data.length; i += 4) {
    seen.add((data[i] << 16) | (data[i + 1] << 8) | data[i + 2]);
    sum += data[i] + data[i + 1] + data[i + 2];
  }
  return {found: true, readable: true, w, h, colors: seen.size, luminance: sum};
}
"""


def main() -> None:
    _art_env = os.environ.get("WLB_E2E_ARTIFACT_DIR", "")
    art = pathlib.Path(_art_env) if _art_env else pathlib.Path(tempfile.mkdtemp(prefix="wlb-e2e-"))
    hub = os.environ.get("WLB_E2E_HUB") or _hub_default()
    user = os.environ.get("WLB_E2E_USER", "")
    passwd = os.environ.get("WLB_E2E_PASS", "")
    deadline = float(os.environ.get("WLB_E2E_TIMEOUT", "180"))
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

            # 2. Launcher → kafelek „Desktop". jrdp otwiera pulpit w NOWEJ karcie/oknie (kafelek
            #    „Desktop [↗]"), więc PRZECHWYTUJEMY nową stronę (popup) i dalej próbkujemy JĄ, nie
            #    Launcher — inaczej canvas nigdy się nie znajdzie (SKIP/FAIL). Fallback na tę samą
            #    kartę, gdyby wersja otwierała pulpit w miejscu (iframe).
            page.wait_for_selector("text=/^Desktop$/", timeout=left() * 1000)
            try:
                with ctx.expect_page(timeout=min(left(), 30) * 1000) as popup_info:
                    page.click("text=/^Desktop$/")
                desktop = popup_info.value
                desktop.wait_for_load_state("domcontentloaded", timeout=left() * 1000)
            except PwTimeoutError:
                desktop = page  # pulpit otwarty w tej samej karcie
            desktop.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)

            # 3. Sesja server-proxy: canvas noVNC na stronie pulpitu (desktop), z shadow-DOM pierce.
            deadline_canvas = time.monotonic() + min(left(), 60)
            sample = {"found": False}
            while time.monotonic() < deadline_canvas:
                sample = desktop.evaluate(_CANVAS_SAMPLE_JS)
                if sample.get("found") and sample.get("readable") and sample.get("colors", 0) > 2:
                    break
                time.sleep(1.5)
            if not sample.get("found"):
                _fail(
                    art,
                    2,
                    "brak canvasu noVNC (kafelek/proxy nie wystawił pulpitu)",
                    hub=hub,
                    console_errors=console_errors[:20],
                )
            if sample.get("colors", 0) <= 2:
                desktop.screenshot(path=str(art / "canvas-empty.png"))
                _fail(
                    art, 2, "canvas pusty/jednolity (czarny ekran)", sample=sample, console_errors=console_errors[:20]
                )

            # 4. Interakcja zmienia obraz: ruch/klik + klawisz na stronie pulpitu, ponowne próbkowanie.
            before = desktop.evaluate(_CANVAS_SAMPLE_JS)
            desktop.mouse.move(640, 400)
            desktop.mouse.click(640, 400)
            desktop.keyboard.type("echo wlb-e2e")
            time.sleep(2)
            after = desktop.evaluate(_CANVAS_SAMPLE_JS)
            if after.get("luminance") == before.get("luminance") and after.get("colors") == before.get("colors"):
                desktop.screenshot(path=str(art / "no-interaction.png"))
                _fail(
                    art,
                    2,
                    "wejście nie zmienia obrazu (brak reakcji pulpitu)",
                    before=before,
                    after=after,
                    console_errors=console_errors[:20],
                )

            # 5. Resize + reconnect (regresja: po zmianie rozmiaru i ponownym połączeniu canvas dalej żyje).
            desktop.set_viewport_size({"width": 1024, "height": 768})
            time.sleep(2)
            desktop.reload(wait_until="domcontentloaded", timeout=left() * 1000)
            reconn = {"found": False}
            d2 = time.monotonic() + min(left(), 45)
            while time.monotonic() < d2:
                reconn = desktop.evaluate(_CANVAS_SAMPLE_JS)
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
                "pulpit renderuje i reaguje (Hub→proxy→noVNC)",
                hub=hub,
                sample=sample,
                after=after,
                reconnect=reconn,
            )
        finally:
            ctx.close()
            browser.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""jupyterlab-e2e.py — E2E UI JupyterLaba w przeglądarce (#288, klasa 5).

Dowodzi tego, czego NIE sprawdza grep configu ani test HTTP: że BADACZ po zalogowaniu do Huba
dostaje działający JupyterLab — widzi kafelki (Python, R, Julia, a na flavorach Desktop/RStudio),
startuje z UI kernele i liczy `1+1`, tworzy/edytuje/zapisuje plik w file browserze, a ścieżki
pobierania i eksportu są ZABLOKOWANE (#284). Ten sam stack Playwrighta co tests/desktop-e2e-novnc.py
(ci/install-tools.sh e2e, ci/requirements-e2e.txt) — żadnego drugiego.

Zakres (mapowanie na #288 sekcja 5):
  (a) logowanie u01 przez formularz Huba → JupyterLab i brak UI admina (`/hub/admin` = 403),
  (b) Launcher: kafelki Python/R/Julia + Help; Desktop (memory/radiologia/histologia),
      RStudio (memory/histologia) — wymagania zależne od WLB_JLAB_FLAVOR,
  (c) kernel Python z UI i `1+1`; to samo dla R; Julia, jeśli jest kafelek
      (WLB_JLAB_REQUIRE_JULIA=0 czyni ją opcjonalną),
  (d) file browser: utwórz/otwórz/edytuj/zapisz plik (zapis potwierdzony przez zamknięcie i ponowne
      otwarcie — nie przez stan w pamięci edytora),
  (e) Download nieobecny w menu File i w menu kontekstowym pliku; „Save and Export Notebook As…”
      nie oferuje ANI JEDNEJ aktywnej pozycji (#284) — sprawdzane w DOM, nie w configu.

Krok Desktopu (niepusty canvas noVNC + wejście) należy do tests/desktop-e2e-novnc.py (#206/#277);
tutaj tylko pilnujemy, że kafelek istnieje na flavorze — bez duplikowania.

Uruchomienie (runner z warstwą testową; u01 tworzy akceptacja, hasło czyta root):
    WLB_E2E_HUB=https://localhost WLB_E2E_USER=u01 \\
    WLB_E2E_PASS="$(sudo cat /root/wlb-hub-u01-initial-password)" \\
        python3 tests/jupyterlab-e2e.py

Parametry (env):
    WLB_E2E_HUB              baza Huba (domyślnie z HUB_TLS: https://localhost lub http://127.0.0.1)
    WLB_E2E_USER/PASS        konto badacza (np. u01) i hasło początkowe
    WLB_JLAB_TIMEOUT         deadline całości w s (domyślnie 420; zimny start serwera + 3 kernele)
    WLB_JLAB_ARTIFACT_DIR    katalog artefaktów (result.json, screenshot, trace.zip, console.log)
    WLB_JLAB_FLAVOR          general (domyślnie) | memory | radiologia | histologia | auto
                             „auto” = nie wymagaj kafelków flavora, tylko raportuj
    WLB_JLAB_REQUIRE_JULIA   1 (domyślnie) = brak kafelka Julia to błąd; 0 = tylko raport
    WLB_JLAB_RSTUDIO_LOAD    1 (domyślnie) = kliknij RStudio i sprawdź, że proxy realnie się ładuje

Kody wyjścia: 0 = JupyterLab działa wg scenariuszy; 1 = błąd konfiguracji/środowiska (brak zmiennych,
brak Playwrighta); 2 = błąd E2E (scenariusz nie przeszedł).
"""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
import re
import sys
import tempfile
import time

SCHEMA = "wlb.jupyterlab-e2e/v1"

# Oczekiwania wobec kafelków zależne od flavora (#105/#108/#135). Baza NIE ma pulpitu ani RStudio —
# ich pojawienie się jest regresją lekkości obrazu bazowego (tests/acceptance.d/40-pulpit.sh).
FLAVOR_TILES = {
    "general": {"Desktop": False, "RStudio": False},
    # wlb-memory = ansible/desktop.yml (desktop + rstudio), radiologia = desktop + neuro_apps,
    # histologia = desktop + rstudio + histo_apps (packer/*.pkr.hcl, #108/#135).
    "memory": {"Desktop": True, "RStudio": True},
    "radiologia": {"Desktop": True, "RStudio": False},
    "histologia": {"Desktop": True, "RStudio": True},
    "auto": {"Desktop": None, "RStudio": None},  # None = tylko raportuj
}

TILE_JS = """
() => Array.from(document.querySelectorAll('.jp-LauncherCard')).map((el) => ({
  label: (el.getAttribute('title') || (el.textContent || '')).trim(),
  category: (el.getAttribute('data-category') || '').trim(),
}))
"""

MENU_JS = """
() => {
  const visible = Array.from(document.querySelectorAll('.lm-Menu'))
    .filter((m) => m.getClientRects().length > 0);
  const menu = visible[visible.length - 1];
  if (!menu) return null;
  return Array.from(menu.querySelectorAll('.lm-Menu-item')).map((item) => {
    const label = item.querySelector('.lm-Menu-itemLabel');
    return {
      text: (label ? label.textContent : '').trim(),
      disabled: item.classList.contains('lm-mod-disabled')
        || item.getAttribute('aria-disabled') === 'true',
      submenu: !!item.querySelector('.lm-Menu-itemSubmenuIcon'),
    };
  });
}
"""

# Kolejność etykiet widocznego menu — pozwala kliknąć pozycję bez wyścigu z DOM przy odczycie tekstu.
MENU_LABELS_JS = """
() => {
  const visible = Array.from(document.querySelectorAll('.lm-Menu'))
    .filter((m) => m.getClientRects().length > 0);
  const menu = visible[visible.length - 1];
  if (!menu) return [];
  return Array.from(menu.querySelectorAll(':scope > .lm-Menu-item > .lm-Menu-itemLabel'))
    .map((el) => (el.textContent || '').trim());
}
"""


def _fail(dir_: pathlib.Path, code: int, reason: str, **extra) -> None:
    """Zapisz result.json i wyjdź danym kodem (zawsze wypisz ścieżkę wyniku)."""
    out = {"schema": SCHEMA, "status": "pass" if code == 0 else "fail", "reason": reason, **extra}
    dir_.mkdir(parents=True, exist_ok=True)
    rp = dir_ / "result.json"
    rp.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"jupyterlab-e2e: wynik: {rp} ({reason})")
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


class Clock:
    """Jeden deadline całości; każde oczekiwanie bierze min(limit kroku, reszta budżetu)."""

    def __init__(self, seconds: float) -> None:
        self.deadline = time.monotonic() + seconds

    def left(self) -> float:
        return max(1.0, self.deadline - time.monotonic())

    def ms(self, cap: float) -> float:
        return min(self.left(), cap) * 1000


def _labels(tiles: list[dict]) -> list[str]:
    return [t["label"] for t in tiles]


def _kernel_tile(tiles: list[dict], pattern: str) -> dict | None:
    """Kafelek kernela: kategoria „Notebook” (nie „Python File” z kategorii Other)."""
    rx = re.compile(pattern, re.IGNORECASE)
    for tile in tiles:
        if tile["category"] == "Notebook" and rx.search(tile["label"]):
            return tile
    return None


def _server_tile(tiles: list[dict], name: str) -> dict | None:
    for tile in tiles:
        if tile["label"].strip() == name:
            return tile
    return None


def _launcher_tiles(page) -> list[dict]:
    return page.evaluate(TILE_JS)


def _open_menu(page, name: str, clock: Clock) -> list[dict]:
    """Otwórz menu główne (File/Help/…) i zwróć jego pozycje (tekst + disabled + submenu)."""
    bar = page.locator(".lm-MenuBar").first
    item = bar.locator(".lm-MenuBar-item", has_text=name).first
    item.click()
    page.wait_for_selector(".lm-Menu", state="visible", timeout=clock.ms(8))
    items = page.evaluate(MENU_JS) or []
    return items


def _close_menu(page) -> None:
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)


def _menu_snapshot(page, name: str, clock: Clock) -> dict:
    items = _open_menu(page, name, clock)
    _close_menu(page)
    return {"items": items, "labels": [i["text"] for i in items if i["text"]]}


def _hover_label(page, rx: str, clock: Clock) -> bool:
    """Najedź na pozycję menu pasującą do regexu (otwiera podmenu)."""
    item = page.locator(".lm-Menu-item").filter(has_text=re.compile(rx, re.IGNORECASE)).first
    if item.count() == 0:
        return False
    item.hover(timeout=clock.ms(5))
    page.wait_for_timeout(400)
    return True


def _download_export_blocked(page, clock: Clock) -> dict:
    """(e) Download i eksport zablokowane w menu File — dowód z DOM, nie z page_config (#284)."""
    snap = _menu_snapshot(page, "File", clock)
    items = snap["items"]
    labels = snap["labels"]

    # Kontrola pozytywna: menu File musi się realnie otworzyć i zawierać bazowe pozycje
    # (np. New/Open/Save). Puste lub nieotwarte menu to FAIL, nie PASS (#288, #313).
    has_base_items = (
        bool(items)
        and any(re.search(r"\bnew\b", lbl, re.IGNORECASE) for lbl in labels)
        and any(re.search(r"\bsave\b", lbl, re.IGNORECASE) for lbl in labels)
    )

    download = [i for i in items if i["text"].strip().lower() == "download"]
    export_top = [i for i in items if re.search(r"save\s+and\s+export\s+notebook", i["text"], re.IGNORECASE)]

    export_submenu: list[dict] = []
    if export_top:
        _open_menu(page, "File", clock)
        if _hover_label(page, r"save\s+and\s+export\s+notebook", clock):
            export_submenu = page.evaluate(MENU_JS) or []
        _close_menu(page)

    enabled_export = [i for i in export_submenu if not i["disabled"] and i["text"]]
    out = {
        "file_menu": labels,
        "menu_opened": has_base_items,
        "download_present": bool(download),
        "download_enabled": any(not i["disabled"] for i in download),
        "export_item_present": bool(export_top),
        "export_item_disabled": bool(export_top) and all(i["disabled"] for i in export_top),
        "export_submenu": [i["text"] for i in export_submenu if i["text"]],
        "export_enabled_entries": [i["text"] for i in enabled_export],
    }
    # Eksport byłby „martwą ścieżką” także wtedy, gdy podmenu jest puste — ale aktywna pozycja
    # (np. HTML/PDF) znaczy, że ktoś przywrócił plugin, czyli blokada #284 zniknęła.
    # Wymagamy dowodu obecności menu (has_base_items): brak pozycji w menu to błąd renderu, nie blokada.
    out["blocked"] = has_base_items and not out["download_enabled"] and not enabled_export
    return out


def _context_menu(page, target, clock: Clock) -> list[dict]:
    target.click(button="right")
    page.wait_for_selector(".lm-Menu", state="visible", timeout=clock.ms(8))
    items = page.evaluate(MENU_JS) or []
    return items


def _wait_tiles(page, clock: Clock, timeout: float = 90.0) -> list[dict]:
    """Czekaj na Launcher i kafelki; jeśli workspace przywrócony bez Launchera — otwórz go."""
    end = time.monotonic() + min(clock.left(), timeout)
    tiles: list[dict] = []
    while time.monotonic() < end:
        try:
            tiles = _launcher_tiles(page)
        except Exception:
            tiles = []
        if tiles:
            return tiles
        # Launcher bywa zamknięty po przywróceniu workspace — spróbuj otworzyć komendą.
        if page.locator(".jp-Launcher:visible").count() == 0:
            try:
                page.keyboard.press("Control+Shift+C")
                page.wait_for_selector(".lm-CommandPalette-input", timeout=3000)
                page.fill(".lm-CommandPalette-input", "New Launcher")
                page.wait_for_timeout(300)
                page.keyboard.press("Enter")
            except Exception:
                page.keyboard.press("Escape")
        page.wait_for_timeout(1500)
    return tiles


def _wait_output(nb, timeout: float) -> str:
    """Czekaj na wynik `1+1` w aktywnym notebooku; zwróć ostatni widoczny tekst outputu."""
    end = time.monotonic() + timeout
    last = ""
    while time.monotonic() < end:
        # Karta może się przebudować między count() a inner_text() — to nie jest błąd scenariusza.
        with contextlib.suppress(Exception):
            outs = nb.locator(".jp-OutputArea-output")
            if outs.count():
                last = outs.last.inner_text()
                if re.search(r"(?<!\d)2(?!\d)", last):
                    return last
        time.sleep(0.4)
    return last


def _show_launcher(page, clock: Clock) -> bool:
    """Aktywuj kartę Launchera — po otwarciu notebooka kafelki przestają być widoczne."""
    if page.locator(".jp-Launcher:visible").count():
        return True
    tab = page.locator("#jp-main-dock-panel .lm-TabBar-tab", has_text="Launcher").first
    if tab.count():
        tab.click(timeout=clock.ms(10))
    else:
        page.keyboard.press("Control+Shift+C")
        page.wait_for_selector(".lm-CommandPalette-input", timeout=clock.ms(8))
        page.fill(".lm-CommandPalette-input", "New Launcher")
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
    with contextlib.suppress(Exception):
        page.wait_for_selector(".jp-Launcher:visible", timeout=clock.ms(20))
    return page.locator(".jp-Launcher:visible").count() > 0


def _run_kernel(page, tile: dict, clock: Clock) -> dict:
    """Klik kafelka kernela → nowy notebook → `1+1` → Shift+Enter → wynik z UI."""
    if not _show_launcher(page, clock):
        return {"ok": False, "reason": "Launcher nie jest dostępny", "tile": tile["label"]}
    before = page.locator(".jp-Notebook:visible").count()
    card = page.locator(f'.jp-LauncherCard[data-category="Notebook"][title="{tile["label"]}"]').first
    card.click(timeout=clock.ms(15))
    end = time.monotonic() + min(clock.left(), 60)
    while time.monotonic() < end and page.locator(".jp-Notebook:visible").count() <= before:
        time.sleep(0.3)
    if page.locator(".jp-Notebook:visible").count() <= before:
        return {"ok": False, "reason": "klik kafelka nie otworzył notebooka", "tile": tile["label"]}

    nb = page.locator(".jp-Notebook:visible").last
    # Status „idle” z paska JupyterLaba jest dowodem, że kernel odpowiedział na połączenie,
    # a nie tylko że karta notebooka powstała.
    idle = False
    end = time.monotonic() + min(clock.left(), 90)
    while time.monotonic() < end:
        status = None
        with contextlib.suppress(Exception):
            status = nb.evaluate(
                "(el) => { const i = el.querySelector('.jp-Notebook-ExecutionIndicator');"
                " return i ? i.getAttribute('data-status') : null; }"
            )
        if status == "idle":
            idle = True
            break
        time.sleep(0.5)

    nb.locator(".cm-content").first.click(timeout=clock.ms(15))
    page.keyboard.insert_text("1+1")
    page.keyboard.press("Shift+Enter")
    output = _wait_output(nb, min(clock.left(), 90))
    ok = bool(re.search(r"(?<!\d)2(?!\d)", output))
    return {
        "ok": ok,
        "tile": tile["label"],
        "kernel_idle": idle,
        "output": output.strip()[:200],
        "reason": "" if ok else f"brak wyniku 2 w outputcie (output={output.strip()[:120]!r})",
    }


def _new_file_via_launcher(page, clock: Clock, name: str, text: str) -> None:
    """Utwórz plik tekstowy z Launchera i zapisz pod `name` (dialog Ctrl+S)."""
    page.locator('.jp-LauncherCard[title="Text File"]').first.click(timeout=clock.ms(15))
    editor = page.locator(".jp-FileEditor:visible").last
    editor.wait_for(timeout=clock.ms(30))
    editor.locator(".cm-content").first.click(timeout=clock.ms(15))
    page.keyboard.insert_text(text)
    page.keyboard.press("Control+s")
    page.wait_for_selector(".jp-Dialog", state="visible", timeout=clock.ms(20))
    page.locator(".jp-Dialog input").first.fill(name)
    page.locator(".jp-Dialog .jp-Dialog-button", has_text=re.compile(r"^Save$")).first.click(timeout=clock.ms(10))
    page.wait_for_selector(".jp-Dialog", state="hidden", timeout=clock.ms(20))


def _close_active_tab(page, clock: Clock) -> dict:
    """Zamknij aktywną kartę; jeśli pojawi się dialog (niezapisane zmiany) — to błąd zapisu."""
    tab = page.locator("#jp-main-dock-panel .lm-TabBar-tab.lm-mod-current").last
    tab.hover(timeout=clock.ms(5))
    close = tab.locator(".lm-TabBar-tabCloseIcon")
    if close.count() == 0:
        return {"closed": False, "reason": "brak ikony zamknięcia na aktywnej karcie"}
    close.click(timeout=clock.ms(10))
    page.wait_for_timeout(500)
    if page.locator(".jp-Dialog:visible").count():
        body = page.locator(".jp-Dialog").last.inner_text().strip()[:300]
        return {"closed": False, "reason": f"dialog przy zamykaniu (niezapisane zmiany?): {body!r}"}
    return {"closed": True, "reason": ""}


def _file_row(page, name: str):
    return page.locator(".jp-FileBrowser .jp-DirListing-itemText", has_text=name).first


def _file_scenario(page, clock: Clock) -> dict:
    """(d) file browser: utwórz → zapisz → otwórz → edytuj → zapisz; weryfikacja po ponownym otwarciu."""
    name = f"wlb-e2e-{int(time.time())}.txt"
    first = "wlb e2e pierwsza linia"
    second = "wlb e2e po edycji"
    out: dict = {"name": name}

    _new_file_via_launcher(page, clock, name, first)
    row = _file_row(page, name)
    row.wait_for(timeout=clock.ms(30))
    out["created"] = True

    # Zamknij i otwórz ponownie — dopiero to dowodzi, że treść jest na dysku, a nie tylko w edytorze.
    out["close_after_create"] = _close_active_tab(page, clock)
    if not out["close_after_create"]["closed"]:
        return out
    row.click(timeout=clock.ms(10))
    editor = page.locator(".jp-FileEditor:visible").last
    editor.wait_for(timeout=clock.ms(30))
    out["reopened_content"] = editor.locator(".cm-content").first.inner_text()[:400]
    out["reopen_has_first"] = first in out["reopened_content"]

    editor.locator(".cm-content").first.click(timeout=clock.ms(10))
    page.keyboard.press("Control+End")
    page.keyboard.insert_text(f"\n{second}")
    page.keyboard.press("Control+s")
    page.wait_for_timeout(800)
    out["close_after_edit"] = _close_active_tab(page, clock)
    if not out["close_after_edit"]["closed"]:
        return out

    row.click(timeout=clock.ms(10))
    editor = page.locator(".jp-FileEditor:visible").last
    editor.wait_for(timeout=clock.ms(30))
    content = editor.locator(".cm-content").first.inner_text()[:600]
    out["final_content"] = content
    out["saved"] = first in content and second in content

    # (e) menu kontekstowe pliku: Download musi być nieobecny; przy okazji sprzątamy plik.
    items = _context_menu(page, row, clock)
    out["context_menu"] = [i["text"] for i in items if i["text"]]
    out["context_download_present"] = any(i["text"].strip().lower() == "download" for i in items)
    out["context_download_enabled"] = any(i["text"].strip().lower() == "download" and not i["disabled"] for i in items)
    # Zamknij menu przed akcją Delete (klikamy pozycję z tego samego, widocznego menu).
    labels = page.evaluate(MENU_LABELS_JS) or []
    if "Delete" in labels:
        menu = page.locator(".lm-Menu:visible").last
        menu.locator(".lm-Menu-item").nth(labels.index("Delete")).click(timeout=clock.ms(8))
    else:
        _close_menu(page)
        out["deleted"] = False
        return out
    page.wait_for_selector(".jp-Dialog", state="visible", timeout=clock.ms(10))
    page.locator(".jp-Dialog .jp-Dialog-button", has_text=re.compile(r"^(Delete|OK)$")).first.click(
        timeout=clock.ms(10)
    )
    page.wait_for_timeout(800)
    out["deleted"] = _file_row(page, name).count() == 0
    return out


def _admin_checks(page, hub: str, user: str, clock: Clock) -> dict:
    """(a) brak UI admina: żadnego linku do /hub/admin i 403 po wejściu na tę ścieżkę."""
    out: dict = {}
    out["admin_links_on_lab"] = page.locator("a[href*='/hub/admin']").count()
    resp = page.goto(f"{hub}/hub/admin", wait_until="domcontentloaded", timeout=clock.ms(30))
    out["admin_http_status"] = resp.status if resp else None
    out["admin_forbidden"] = out["admin_http_status"] == 403
    page.goto(f"{hub}/hub/home", wait_until="domcontentloaded", timeout=clock.ms(30))
    page.wait_for_timeout(500)
    out["admin_links_on_home"] = page.locator("a[href*='/hub/admin']").count()
    out["user"] = user
    return out


def _rstudio_check(page, tile: dict, clock: Clock) -> dict:
    """RStudio (histologia): kafelek otwiera proxy, które realnie się ładuje (nie 502/blank).

    jupyter-server-proxy montuje serwery w IFrame w głównym obszarze (.jp-ServerProxy) — w
    przeciwieństwie do jrdp („Desktop”, new_browser_window=True) NIE otwiera nowej karty.
    """
    out: dict = {"tile": tile["label"]}
    errors = re.compile(r"bad gateway|internal server error|error 50[234]|traceback", re.IGNORECASE)
    if not _show_launcher(page, clock):
        out.update({"loaded": False, "error": "Launcher nie jest dostępny"})
        return out
    page.locator(f'.jp-LauncherCard[title="{tile["label"]}"]').first.click(timeout=clock.ms(15))
    end = time.monotonic() + min(clock.left(), 150)
    src = title = body = ""
    loaded = False
    while time.monotonic() < end:
        iframe = page.locator(".jp-ServerProxy:visible iframe").last
        with contextlib.suppress(Exception):
            # iframe/rsession jeszcze się przeładowuje — próbujemy do końca deadline'u
            if iframe.count():
                src = iframe.get_attribute("src") or ""
                frame = iframe.content_frame
                title = frame.locator("title").text_content(timeout=5000) or ""
                body = frame.locator("body").inner_text(timeout=5000)[:600]
        if re.search(r"rstudio", f"{title}\n{body}", re.IGNORECASE) and not errors.search(body):
            loaded = True
            break
        time.sleep(1.5)
    out.update({"frame_src": src, "title": title.strip(), "body": body.strip(), "loaded": loaded})
    return out


def main() -> None:
    art_env = os.environ.get("WLB_JLAB_ARTIFACT_DIR") or os.environ.get("WLB_E2E_ARTIFACT_DIR", "")
    art = pathlib.Path(art_env) if art_env else pathlib.Path(tempfile.mkdtemp(prefix="wlb-jlab-e2e-"))
    art.mkdir(parents=True, exist_ok=True)
    hub = (os.environ.get("WLB_E2E_HUB") or _hub_default()).rstrip("/")
    user = os.environ.get("WLB_E2E_USER", "")
    passwd = os.environ.get("WLB_E2E_PASS", "")
    flavor = os.environ.get("WLB_JLAB_FLAVOR", "general").strip().lower()
    require_julia = os.environ.get("WLB_JLAB_REQUIRE_JULIA", "1").strip() != "0"
    rstudio_load = os.environ.get("WLB_JLAB_RSTUDIO_LOAD", "1").strip() != "0"

    if flavor not in FLAVOR_TILES:
        _fail(art, 1, f"WLB_JLAB_FLAVOR={flavor!r} — dozwolone: {', '.join(FLAVOR_TILES)}")
    if not user or not passwd:
        _fail(art, 1, "brak WLB_E2E_USER/WLB_E2E_PASS")
    try:
        timeout = float(os.environ.get("WLB_JLAB_TIMEOUT", "420"))
    except ValueError:
        _fail(art, 1, "WLB_JLAB_TIMEOUT nie jest liczbą")

    try:
        from playwright.sync_api import TimeoutError as PwTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        _fail(art, 1, "brak Playwrighta w warstwie testowej (ci/install-tools.sh e2e)")

    clock = Clock(timeout)
    console_errors: list[str] = []
    checks: dict = {"flavor": flavor, "hub": hub}

    with sync_playwright() as p:  # type: ignore[name-defined]
        browser = p.chromium.launch(headless=True, args=["--ignore-certificate-errors"])
        context = browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1440, "height": 900},
            accept_downloads=False,  # pobranie pliku NIE może się udać po cichu (#284)
        )
        context.tracing.start(screenshots=True, snapshots=True, sources=False)
        page = context.new_page()
        page.set_default_timeout(30_000)

        def on_console(msg) -> None:
            if msg.type == "error":
                console_errors.append(f"{msg.text}")

        context.on(
            "page",
            lambda pg: (
                pg.on("console", on_console),
                pg.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}")),
            ),
        )
        page.on("console", on_console)
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

        stage = "start"
        try:
            # (a) Logowanie przez formularz Huba.
            stage = "logowanie"
            page.goto(f"{hub}/hub/login", wait_until="domcontentloaded", timeout=clock.ms(45))
            page.fill("input[name='username']", user)
            page.fill("input[name='password']", passwd)
            page.click("input[type='submit'], button[type='submit']")
            # TLJH mógł zatrzymać się na /hub/home — sesja już jest, wejdźmy jawnie do Laba.
            with contextlib.suppress(PwTimeoutError):
                page.wait_for_url("**/user/**", timeout=clock.ms(60))
            checks["login"] = {"ok": True, "url_after_login": page.url}

            # Świeży workspace: `?reset` zdejmuje przywrócone dokumenty, więc Launcher jest widoczny.
            stage = "start JupyterLaba"
            page.goto(f"{hub}/user/{user}/lab?reset", wait_until="domcontentloaded", timeout=clock.ms(90))
            page.wait_for_selector(".jp-LabShell", timeout=clock.ms(120))
            tiles = _wait_tiles(page, clock)
            if not tiles:
                raise AssertionError("Launcher nie pokazał kafelków w czasie")
            checks["launcher"] = {"tiles": tiles, "labels": _labels(tiles)}

            # (b) Kafelki: Python/R/Julia + Help, a flavor decyduje o Desktop/RStudio.
            stage = "kafelki Launchera"
            expected = FLAVOR_TILES[flavor]
            py_tile = _kernel_tile(tiles, r"^python\b")
            r_tile = _kernel_tile(tiles, r"^r(\s|\()")
            jl_tile = _kernel_tile(tiles, r"^julia\b")
            desktop_tile = _server_tile(tiles, "Desktop")
            rstudio_tile = _server_tile(tiles, "RStudio")
            help_menu = page.locator(".lm-MenuBar-item", has_text="Help").count() > 0

            launcher = checks["launcher"]
            launcher["python_tile"] = py_tile["label"] if py_tile else None
            launcher["r_tile"] = r_tile["label"] if r_tile else None
            launcher["julia_tile"] = jl_tile["label"] if jl_tile else None
            launcher["desktop_tile"] = desktop_tile["label"] if desktop_tile else None
            launcher["rstudio_tile"] = rstudio_tile["label"] if rstudio_tile else None
            launcher["help_menu"] = help_menu
            problems = []
            if not py_tile:
                problems.append("brak kafelka Python")
            if not r_tile:
                problems.append("brak kafelka R")
            if not jl_tile and require_julia:
                problems.append("brak kafelka Julia (WLB_JLAB_REQUIRE_JULIA=1)")
            if not help_menu:
                problems.append("brak menu Help")
            for name, want in expected.items():
                got = desktop_tile if name == "Desktop" else rstudio_tile
                if want is True and not got:
                    problems.append(f"flavor {flavor}: brak kafelka {name}")
                if want is False and got:
                    problems.append(f"flavor {flavor}: kafelek {name} nie powinien istnieć (regresja lekkości)")
            launcher["problems"] = problems
            if problems:
                raise AssertionError("; ".join(problems))

            # (c) Kernele: Python i R zawsze; Julia, gdy kafelek jest.
            stage = "kernel Python"
            checks["kernels"] = {"python": _run_kernel(page, py_tile, clock)}
            if not checks["kernels"]["python"]["ok"]:
                raise AssertionError(f"Python: {checks['kernels']['python']['reason']}")

            stage = "kernel R"
            checks["kernels"]["r"] = _run_kernel(page, r_tile, clock)
            if not checks["kernels"]["r"]["ok"]:
                raise AssertionError(f"R: {checks['kernels']['r']['reason']}")

            if jl_tile:
                stage = "kernel Julia"
                checks["kernels"]["julia"] = _run_kernel(page, jl_tile, clock)
                if not checks["kernels"]["julia"]["ok"]:
                    raise AssertionError(f"Julia: {checks['kernels']['julia']['reason']}")
            else:
                checks["kernels"]["julia"] = {"ok": None, "skipped": "brak kafelka Julia"}

            # (e) Blokady pobierania/eksportu — sprawdzane w DOM przy aktywnym notebooku.
            stage = "blokady Download/Export"
            checks["download"] = _download_export_blocked(page, clock)
            if not checks["download"]["blocked"]:
                if not checks["download"].get("menu_opened"):
                    raise AssertionError(
                        f"menu File nie otworzyło się lub brak bazowych pozycji: {checks['download']['file_menu']}"
                    )
                raise AssertionError(
                    "blokady #284 nie działają: "
                    f"Download={checks['download']['download_present']}, "
                    f"eksport={checks['download']['export_enabled_entries']}"
                )

            # (d) File browser na świeżym workspace (Launcher znowu widoczny).
            stage = "file browser"
            page.goto(f"{hub}/user/{user}/lab?reset", wait_until="domcontentloaded", timeout=clock.ms(90))
            page.wait_for_selector(".jp-LauncherCard", timeout=clock.ms(90))
            checks["file"] = _file_scenario(page, clock)
            if not checks["file"].get("saved"):
                raise AssertionError(
                    f"plik nie zapisał się poprawnie (content={checks['file'].get('final_content')!r})"
                )
            if checks["file"].get("context_download_enabled"):
                raise AssertionError("menu kontekstowe pliku oferuje Download (#284)")
            if not checks["file"].get("deleted"):
                raise AssertionError("nie udało się posprzątać pliku testowego przez UI")

            # RStudio (histologia) — kafelek już sprawdzony; tu realne ładowanie proxy.
            if rstudio_tile and rstudio_load:
                stage = "RStudio"
                checks["rstudio"] = _rstudio_check(page, rstudio_tile, clock)
                if not checks["rstudio"].get("loaded"):
                    raise AssertionError(f"RStudio nie załadowało się: {checks['rstudio']}")

            # (a) brak UI admina — na końcu, bo przechodzimy poza Laba.
            stage = "kontrola admina"
            checks["admin"] = _admin_checks(page, hub, user, clock)
            if not checks["admin"]["admin_forbidden"] or checks["admin"]["admin_links_on_lab"]:
                raise AssertionError(f"UI admina widoczne/dozwolone dla {user}: {checks['admin']}")

            page.screenshot(path=str(art / "jupyterlab-ok.png"))
            (art / "console.log").write_text("\n".join(console_errors), encoding="utf-8")
            context.tracing.stop()
            browser.close()
            k_sum = {k: v.get("ok") for k, v in checks.get("kernels", {}).items()}
            _fail(
                art,
                0,
                f"JupyterLab działa (flavor {flavor}): kafelki, kernele {k_sum}, plik zapisany, "
                "Download/eksport zablokowane, brak UI admina",
                checks=checks,
                console_errors=console_errors[:20],
            )
        except Exception as exc:  # każdy błąd scenariusza kończy się artefaktami
            reason = f"{stage}: {type(exc).__name__}: {str(exc).splitlines()[0][:300]}"
            with contextlib.suppress(Exception):
                page.screenshot(path=str(art / "jupyterlab-failed.png"))
                (art / "page.html").write_text(page.content(), encoding="utf-8")
                context.tracing.stop(path=str(art / "trace.zip"))
            (art / "console.log").write_text("\n".join(console_errors), encoding="utf-8")
            with contextlib.suppress(Exception):
                browser.close()
            _fail(art, 2, reason, checks=checks, console_errors=console_errors[:20])


if __name__ == "__main__":
    main()

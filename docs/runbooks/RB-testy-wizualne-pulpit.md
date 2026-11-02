# RB: Testy wizualne pulpitu (render-smoke)

**Rola:** Operator budowy obrazu / QA
**Odniesienia:** #138 (plan etapowy), #205 (hardening etapu 1), #106 (pulpit), #105 (flavor wlb-memory), #135 (radiologia GUI)
**Co to:** render-smoke sprawdza, że pulpit **realnie się renderuje** i reaguje na interakcję, a nie tylko że pakiety są obecne. Etap 1 — samodzielny skrypt `tests/desktop-render-smoke.sh`, uruchamiany ręcznie na VM `wlb-memory`/`wlb-radiologia`. **Jeszcze nie** w bramkującej akceptacji (patrz §8).

## 1. Zasada działania

Skrypt:

1. wybiera wolny display (domyślnie `:99`–`:199`) i startuje prywatny serwer TigerVNC z sesją XFCE;
2. czeka z **deadline** (bez stałego `sleep`) na gotowość: X, gniazdo VNC, menedżer okien (`_NET_SUPPORTING_WM_CHECK`), `xfce4-session`, `xfce4-panel` i sesyjny `dbus-daemon`;
3. otwiera kontrolowane okno `xmessage` z unikalnym markerem i różowym tłem `#ff00ff`;
4. robi zrzut (`scrot`) i analizuje region okna przez Pillow: obecność tła, pikseli tekstu i geometrię;
5. przesuwa i skaluje okno (`wmctrl`), czeka na zmianę geometrii i sprawdza, że obraz regionu **się zmienił**;
6. zapisuje `result.json` oraz PNG/logi do katalogu artefaktów.

Liczba kolorów na ekranie jest **tylko diagnostyką** — niski wynik nie decyduje o PASS. PASS wymaga okna, tekstu, tła i reakcji na interakcję. Dzięki temu jednolity ekran, gradient albo okno błędu nie przechodzą testu.

## 2. Wymagania

- pakiety roli `desktop`: TigerVNC, XFCE, `dbus-x11`, `scrot`, `x11-utils` (`xdpyinfo`/`xprop`/`xwininfo`/`xmessage`), `wmctrl`, `xauth`;
- Pillow w env badaczy (`/opt/tljh/user/bin/python`);
- uruchomienie **jako badacz**, nie root — XFCE pod rootem jest niewspierany.

## 3. Jak uruchomić (na uruchomionej VM)

```bash
# na VM wlb-memory/wlb-radiologia, jako administrator platformy:
sudo -iu <badacz> /opt/wlb/tests/desktop-render-smoke.sh   # ścieżka = gdzie leży repo/skrypt
echo "wynik: $?"    # 0 = OK, 1 = środowisko/start/gotowość, 2 = błąd renderu
```

Skrypt zawsze wypisuje ścieżkę `result.json`, np.:

```text
render-smoke: wynik: /home/jupyter-u01/.local/state/wlb/desktop-render-smoke/20261102T101500Z-1234/result.json
```

Jeśli badacza testowego nie ma, utwórz go przez Hub (konto badacza) — pulpit startuje w jego kontekście, jak w produkcji.

## 4. Parametry (zmienne środowiskowe)

| Zmienna | Domyślnie | Po co |
|---|---|---|
| `WLB_SMOKE_DISPLAY` | auto (`:99`–`:199`) | wymuś display `:N`; zajęty display kończy się błędem bez dotykania cudzej sesji |
| `WLB_SMOKE_GEOMETRY` | `1280x800` | rozdzielczość wirtualnego ekranu (320–7680 × 240–4320) |
| `WLB_SMOKE_TIMEOUT` | `90` | deadline całego przebiegu w sekundach (1–3600); obejmuje start, gotowość i interakcję |
| `WLB_SMOKE_MIN_COLORS` | `64` | **tylko diagnostyka**; nie decyduje o PASS |
| `WLB_SMOKE_ARTIFACT_DIR` | `~/.local/state/wlb/desktop-render-smoke/<UTC>-<pid>` | katalog na `result.json`, PNG i logi |
| `WLB_SMOKE_PYTHON` | `/opt/tljh/user/bin/python` | Python z Pillow |

Usunięte względem prototypu: `WLB_SMOKE_SETTLE` (zastąpione deadline i pętlą gotowości) oraz `WLB_SMOKE_KEEP_SHOT` (artefakty są zawsze zachowywane).

## 5. Kody wyjścia i powody w `result.json`

| Kod | Znaczenie |
|---|---|
| `0` | PASS — render i interakcja OK |
| `1` | błąd środowiska, parametrów, startu lub gotowości (np. brak pakietu, zajęty display, brak WM) |
| `2` | błąd renderu (brak okna, brak tekstu, brak zmiany obrazu, błąd zrzutu/analizy) |
| `130`/`143` | przerwanie sygnałem `INT`/`TERM`; wynik i tak trafia do `result.json` |

Pole `reason` jest maszynowe, np. `ok`, `invalid_geometry`, `display_busy`, `vnc_start_failed`, `readiness_timeout`, `window_not_found`, `render_check_failed`, `interaction_failed`, `signal_term`. Pełny opis jest w `message`.

## 6. Artefakty i `result.json`

Katalog artefaktów ma tryb `0700`, pliki `0600`. Jest zachowywany zarówno przy PASS, jak i FAIL — na FAIL zawiera co najmniej `result.json`, `vnc.log`, `run.log`, a po wykonaniu zrzutów także PNG i `analysis-*.json`.

Przykładowy `result.json` (schemat `wlb.desktop-render-smoke/v1`):

```json
{
  "schema": "wlb.desktop-render-smoke/v1",
  "status": "pass",
  "reason": "ok",
  "duration_s": 18,
  "exit_code": 0,
  "display": ":99",
  "geometry": "1280x800",
  "timeout_s": 90,
  "min_colors": 64,
  "screenshots": {
    "initial": "/.../screen-initial.png",
    "interaction": "/.../screen-interaction.png"
  },
  "window": {
    "id": "0x600003",
    "title": "WLB-SMOKE-...",
    "geometry_before": "560x200+100+80",
    "geometry_after": "480x160+160+120"
  },
  "colors": {
    "screen": 5123,
    "window": 14,
    "background_pixels": 64000,
    "foreground_pixels": 1200,
    "background_fraction": 0.57
  },
  "checks": {
    "x": true,
    "vnc_socket": true,
    "wm": true,
    "session": true,
    "panel": true,
    "dbus": true,
    "window": true,
    "image": true,
    "interaction": true
  }
}
```

Do szybkiego sprawdzenia wyniku:

```bash
jq -e '.status == "pass"' "$ARTIFACT_DIR/result.json"
jq '.reason, .checks, .colors' "$ARTIFACT_DIR/result.json"
```

## 7. Bezpieczeństwo i izolacja

- RFB działa **tylko na prywatnym gnieździe Unix** w katalogu `0700` (`-rfbunixpath`, `-rfbunixmode 0600`, `-rfbport -1`); nie ma nieuwierzytelnionego nasłuchu TCP.
- `XAUTHORITY` jest prywatnym plikiem w katalogu artefaktów — test nie dotyka `~/.Xauthority` badacza.
- Cleanup zabija **wyłącznie własną grupę procesów** (PID z prywatnego pidfile + unikalny token w środowisku), nigdy `vncserver -kill` ani procesy po numerze displayu. Obca sesja na tym samym displayu nie jest dotykana.
- Dwa równoległe przebiegi wybierają różne displaye; przy wymuszonym `WLB_SMOKE_DISPLAY` drugi przebieg kończy się `display_busy`.
- Test nie łączy się z Hubem ani noVNC; to osobny etap (#206).

## 8. Dlaczego jeszcze nie w akceptacji (świadoma decyzja, #138/#205)

Render-smoke to test **runtime** (start X + XFCE + interakcja) — z natury wrażliwy na czas i wolniejszy niż lekkie fragmenty `acceptance.d/` (`command -v`). Wpięcie go teraz w bramkujący stage 5 (#86) groziłoby **fałszywymi czerwonymi**. Kolejność:

1. empiryczna walidacja na prawdziwym XFCE/TigerVNC (w tym cleanup i dwa równoległe przebiegi),
2. co najmniej 20 kolejnych przebiegów bez niewyjaśnionych błędów,
3. dopiero potem fragment `tests/acceptance.d/` (nazwa do ustalenia — `45-memory.sh` jest zajęte) i promocja do etapu 5.

## 9. Testy jednostkowe (atrapy X)

```bash
bats tests/unit/desktop-render-smoke.bats
```

Testy pokrywają PASS, brak WM/panelu/D-Bus/sesji, zajęty display, częściowy start, błąd zrzutu/analizy, jednolite tło, gradient, brak fontów, okno błędu, brak reakcji na `wmctrl`, walidację parametrów, SIGTERM i dwa równoległe przebiegi. Nie zastępują walidacji na prawdziwym X — atrapy sprawdzają kontrakt poleceń i logikę wyniku.

## 10. Tryby błędów

| Objaw | Przyczyna / naprawa |
|---|---|
| `FAIL — not_researcher` | XFCE pod rootem niewspierany — użyj `sudo -iu <badacz>` |
| `brak scrot/startxfce4/tigervncserver/xdpyinfo/wmctrl` | obraz nie jest flavorem z pulpitem (rola `desktop`) albo niekompletny build |
| `display_busy` | wybrany `WLB_SMOKE_DISPLAY` jest zajęty — usuń wymuszenie (auto) albo wskaż inny numer |
| `readiness_timeout` z `brak: WM/panel/D-Bus` | sesja XFCE nie wstała; sprawdź `vnc.log` i procesy sesji; zwiększ `WLB_SMOKE_TIMEOUT` na wolnej VM |
| `render_check_failed` | okno nie ma tła/tekstu (brak fontów, zły motyw) — obejrzyj `screen-initial.png` |
| `interaction_failed` | WM nie przeniósł/nie zmienił rozmiaru okna albo obraz się nie zmienił — sprawdź `screen-interaction.png` |
| `missing_pillow` | brak Pillow w `/opt/tljh/user/bin/python` — regresja env Pythona |
| `image_analysis_failed` | uszkodzony PNG albo region poza zrzutem — sprawdź `analysis.err` |

## 11. Dalej (etap 2, osobny PR)

Regresja **perceptualna** (nie pixel-exact) wybranych okien, które da się ustabilizować: **FSLeyes** z załadowanym wolumenem, **3DSlicer** po starcie (#135). Obraz bazowy + próg perceptualny; bloby wersjonowane świadomie. E2E przez Hub/noVNC — #206.

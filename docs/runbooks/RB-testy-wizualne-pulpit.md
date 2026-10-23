# RB: Testy wizualne pulpitu (render-smoke)

**Rola:** Operator budowy obrazu / QA
**Odniesienia:** #138 (plan etapowy), #106 (pulpit), #105 (flavor wlb-memory), #135 (radiologia GUI)
**Co to:** render-smoke sprawdza, że pulpit **realnie się renderuje** (nie czarny ekran), a nie tylko że pakiety są obecne. Etap 1 — samodzielny skrypt `tests/desktop-render-smoke.sh`, uruchamiany ręcznie na VM `wlb-memory`/`wlb-radiologia`. **Jeszcze nie** w bramkującej akceptacji (patrz §4).

## 1. Zasada działania

Skrypt wstaje headless serwer X (TigerVNC, localhost, bez hasła) z sesją XFCE, czeka na render, robi zrzut (`scrot`) i liczy kolory na obrazie przez Pillow (z env badaczy). **Pusty/czarny ekran ma ~1–2 kolory; wyrenderowany pulpit — wiele.** Próg domyślny: 64 kolory.

## 2. Jak uruchomić (na uruchomionej VM)

Pulpit XFCE nie działa pod rootem — uruchamiaj **jako badacz**:

```bash
# na VM wlb-memory/wlb-radiologia, jako administrator platformy:
sudo -iu <badacz> /opt/wlb/tests/desktop-render-smoke.sh   # ścieżka = gdzie leży repo/skrypt
echo "wynik: $?"    # 0 = render OK, 1 = błąd środowiska/startu, 2 = ekran pusty
```

Jeśli badacza testowego nie ma, utwórz go przez Hub (konto badacza) — pulpit startuje w jego kontekście, jak w produkcji.

## 3. Strojenie (zmienne środowiskowe)

| Zmienna | Domyślnie | Po co |
|---|---|---|
| `WLB_SMOKE_SETTLE` | `8` | sekundy na wyrenderowanie XFCE; na wolnej/obciążonej VM podnieś (np. 15) |
| `WLB_SMOKE_MIN_COLORS` | `64` | próg „nie pusty"; dobierz empirycznie z realnego zrzutu |
| `WLB_SMOKE_GEOMETRY` | `1280x800` | rozdzielczość wirtualnego ekranu |
| `WLB_SMOKE_DISPLAY` | `:99` | numer display (zmień przy konflikcie) |
| `WLB_SMOKE_KEEP_SHOT` | `0` | `1` zostawia PNG (ścieżkę wypisuje nagłówek) do obejrzenia |

Obejrzenie zrzutu przy strojeniu progu:

```bash
WLB_SMOKE_KEEP_SHOT=1 WLB_SMOKE_MIN_COLORS=1 sudo -iu <badacz> .../desktop-render-smoke.sh
# skrytkę .png skopiuj z VM i obejrzyj; ustaw próg bezpiecznie poniżej realnej liczby kolorów
```

## 4. Dlaczego jeszcze nie w akceptacji (świadoma decyzja, #138)

Render-smoke to test **runtime** (start X + XFCE + render) — z natury wrażliwy na czas i wolniejszy niż lekkie fragmenty `acceptance.d/` (`command -v`). Wpięcie go teraz w bramkujący stage 5 (#86) groziłoby **fałszywymi czerwonymi**. Kolejność: najpierw empiryczna walidacja razem z #106 (stabilny `SETTLE`, próg kolorów, zachowanie Xauth wrappera TigerVNC), potem **etap 1b** — adaptacyjny fragment `tests/acceptance.d/45-pulpit-render.sh` wołający ten skrypt przez `as R1`.

## 5. Tryby błędów

| Objaw | Przyczyna / naprawa |
|---|---|
| `FAIL — uruchom jako badacz, nie root` | XFCE pod rootem niewspierany — użyj `sudo -iu <badacz>` |
| `brak scrot/startxfce4/tigervncserver` | obraz nie jest flavorem z pulpitem (rola `desktop`) albo niekompletny build |
| `serwer VNC nie wstał` | zajęty display (`:99`) — zmień `WLB_SMOKE_DISPLAY`; sprawdź log w komunikacie |
| exit 2 przy działającym pulpicie | render wolniejszy niż `SETTLE` — podnieś `WLB_SMOKE_SETTLE`; sprawdź próg `MIN_COLORS` na realnym zrzucie |
| `analiza Pillow nie powiodła się` | brak Pillow w `/opt/tljh/user/bin/python` — regresja env Pythona |

## 6. Dalej (etap 2, osobny PR)

Regresja **perceptualna** (nie pixel-exact) wybranych okien, które da się ustabilizować: **FSLeyes** z załadowanym wolumenem, **3DSlicer** po starcie (#135). Obraz bazowy + próg perceptualny; bloby wersjonowane świadomie.

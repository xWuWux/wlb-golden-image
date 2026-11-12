# Śluza eksportu: jak sprawdzić status i dać zwrot badaczowi

Poradnik zadaniowy dla **Administratora Klienta** i **operatora** — jak odpowiedzieć badaczowi
na „czy mój plik jest w śluzie?" i „jak nastąpi przekazanie?". Szczegóły wewnętrzne (manifest v1,
awarie, kwarantanna) są w [RB-eksport-kolejka.md](RB-eksport-kolejka.md).

## Stan wdrożenia — przeczytaj najpierw

Działa: przyjęcie pliku do **kolejki przeglądu** + automatyczne **potwierdzenie/odrzucenie** dla badacza.
**Nie działa jeszcze (#20):** zgoda Lidera/Kontrolera i **publikacja (wydanie na zewnątrz)**. Wpis w
kolejce (`pending_review`) **nie jest zgodą na eksport** i nie oznacza, że dane opuściły VM. Dopóki #20
nie jest wdrożone, samo przekazanie na zewnątrz jest operacją **administratora platformy** wg decyzji
Kontrolera/Lidera, nie samoobsługą.

## Kto co widzi (dostęp)

| Rola | Konto | SSH | Kolejka `/workspace/.wlb-export-queue` | `/sluza-potwierdzenia`, `/sluza-odrzucone` |
|---|---|---|---|---|
| Badacz | `uNN` | nie | brak (root 0700) | **listuje**; czyta **własne** potwierdzenia/odrzucenia (treść 0640) |
| Administrator Klienta | `a01` | **nie** | brak (root 0700) | **listuje** (członek `jupyterhub-users`); treści cudzych nie czyta |
| Operator / admin platformy | root | tak | pełny | pełny |

Wniosek: **Administrator Klienta nie podejrzy kolejki ani cudzej treści potwierdzenia.** Może zobaczyć,
czy *istnieje* wpis o danej nazwie. Weryfikację paczki i wydanie robi operator (root).

## Przepływ w skrócie

1. Badacz kopiuje wynik **jednym poleceniem** do `/sluza-out` (tryb `1730` — tylko zapis, **bez
   listowania**; „nie da się otworzyć tego folderu" to **zachowanie poprawne**, nie błąd).
2. Mover (`wlb-sluza-out.service`) przejmuje plik, robi prywatną kopię na nowych i-węzłach + SHA-256 +
   `manifest.json`, odkłada paczkę do kolejki (`pending_review`). Plik **znika** ze `/sluza-out`.
3. Wynik dla badacza:
   - **przyjęto** → `/sluza-potwierdzenia/<czas>_jupyter-<login>_<nazwa>.potwierdzenie.*`
   - **odrzucono** → `/sluza-odrzucone/<czas>_<nazwa>.powod.*`
4. (#20, **do wdrożenia**) zgoda Lidera/Kontrolera → publikacja/wydanie.

## Scenariusz: „czy mój plik (np. `processed_1-30.zip`) jest w śluzie?"

Powiedz badaczowi (lub sprawdź z nim) **w jego sesji JupyterLab**:

1. **Potwierdzenie przyjęcia** — czy jest plik:
   ```sh
   ls -l /sluza-potwierdzenia/ | grep processed_1-30.zip
   cat /sluza-potwierdzenia/*processed_1-30.zip.potwierdzenie.*   # tylko właściciel odczyta swoje
   ```
   Potwierdzenie zawiera: `Element`, `Czas (UTC)`, `Wniosek` (request_id), **`Liczba plików`**,
   **`Łączny rozmiar`**, **`sha256-inventory`**, `Status`. **Badacz porównuje liczbę plików i rozmiar**
   z tym, co wysłał — to dowód, że paczka trafiła do kolejki **w komplecie**.
2. **Jeśli potwierdzenia nie ma — przyczyna odrzucenia:**
   ```sh
   cat /sluza-odrzucone/*processed_1-30.zip.powod.*
   ```
   Najczęściej: **różni właściciele** plików w paczce (np. element skopiowany z `/data-mart` należy do
   `root` — trzeba `cp`, nie dowiązanie), dowiązanie symboliczne/twarde, typ specjalny, albo **limit**
   (100 GiB / 100 000 plików na wniosek). **Jeden niepasujący element odrzuca cały wniosek.**
3. **Jeśli nie ma ani potwierdzenia, ani odrzucenia** — wniosek mógł **utknąć w kwarantannie operatora**
   (błąd migawki blokuje kolejkę). To zadanie operatora: patrz [RB-eksport-kolejka.md](RB-eksport-kolejka.md)
   („Publikacja do wewnętrznej kolejki i awarie"). Zgłoś HelpDeskowi/operatorowi.

> `cp ~/plik /sluza-out/` i brak pliku w `/sluza-out` **nie** potwierdza przyjęcia — potwierdza je
> wyłącznie plik w `/sluza-potwierdzenia`. Niech badacz **zachowa oryginał** w `~` do czasu wydania.

## Weryfikacja przez operatora (root) — integralność paczki w kolejce

Tylko operator z istniejącymi uprawnieniami; **nie** udostępniać tego badaczom/Kontrolerowi przez sudo:
```sh
sudo ls -l /workspace/.wlb-export-queue/
sudo /usr/local/sbin/wlb-export-snapshot verify /workspace/.wlb-export-queue/<PAKIET>   # 0 = spójny
sudo cat /workspace/.wlb-export-queue/<PAKIET>/manifest.json   # request_id, entries, sha256
```
Korelacja w SIEM (journald): zdarzenie `export_request user=… entry=… sha256=… queued_as=…`.
`verify` sprawdza dokładny spis, rozmiary i sumy — ale **nie** autentyczność metadanych ani zgodę na eksport.

## Jak dać zwrot badaczowi (gotowe formułki)

- **Przyjęto do kolejki:** „Paczka `processed_1-30.zip` trafiła do kolejki przeglądu — potwierdzenie
  masz w `/sluza-potwierdzenia/`. Porównaj `Liczba plików` i `Łączny rozmiar` z tym, co wysyłałeś.
  **To potwierdza przyjęcie, nie zgodę na eksport** — wydanie na zewnątrz odbędzie się decyzją
  Kontrolera/Lidera (mechanizm #20 w trakcie wdrażania); do tego czasu zachowaj oryginał w `~`."
- **Odrzucono:** „Wniosek odrzucony — powód w `/sluza-odrzucone/…powod…`: <treść>. Popraw (najczęściej:
  różni właściciele — użyj `cp`, nie dowiązania) i wyślij ponownie jako **jeden** plik/archiwum."
- **Brak śladu:** „Wniosek mógł utknąć w kwarantannie operatora — zgłaszam do administratora platformy;
  Twój oryginał w `~` jest bezpieczny, nic nie przepadło."

## Czego NIE robić

- Nie traktować obecności/braku pliku w `/sluza-out` ani nazwy paczki w kolejce jako zgody.
- Nie wydawać danych na zewnątrz „ręcznie" poza decyzją Kontrolera/Lidera i polityką instytucji
  (ścieżka wydania #20 nie jest jeszcze zaimplementowana; interim = operator wg udokumentowanej decyzji).
- Nie kopiować kwarantanny/payloadu na laptop ani nie wrzucać ponownie do śluzy automatycznie.

## Powiązane

- [RB-sluza-wydanie-tymczasowe.md](RB-sluza-wydanie-tymczasowe.md) — **tymczasowa** procedura ręcznego wydania do czasu #20 (operator + Kontroler).
- [RB-eksport-kolejka.md](RB-eksport-kolejka.md) — wewnętrzny format, awarie, kwarantanna, `verify` (operator).
- [docs/architektura/sluza-eksportu.md](../architektura/sluza-eksportu.md) — diagramy przepływu śluzy.
- `/docs/README` na VM — skrót dla badacza (ten sam opis `/sluza-*`).
- #20 — zgoda Lidera/Kontrolera i publikacja (do wdrożenia); #102 — rejestr osoba↔konto (przed #20).

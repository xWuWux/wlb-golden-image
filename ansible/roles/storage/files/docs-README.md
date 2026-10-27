# Wirtualne Laboratorium Badawcze — skrót dla badacza

| Katalog      | Co tu jest                                         | Co możesz zrobić        |
|--------------|----------------------------------------------------|-------------------------|
| `~` (`/workspace/jupyter-<login>`) | Twoja przestrzeń robocza, objęta backupem | czytać i zapisywać |
| `/sluza-in`  | dane wejściowe zatwierdzone przez Kontrolera Przesyłu Danych | tylko czytać |
| `/data-mart` | kohorta OMOP przypisana do Laboratorium            | tylko czytać            |
| `/sluza-out` | wyniki do eksportu                                 | tylko zapisywać         |
| `/docs`      | dokumentacja platformy i skrypty pomocnicze        | tylko czytać            |

**Eksport wyników — przygotuj najpierw, skopiuj na końcu:**
1. Zapisz **gotowy** wynik w katalogu domowym (`~`).
2. Skopiuj go do `/sluza-out` **jednym poleceniem**, np. `cp ~/wyniki.csv /sluza-out/`.

Po przejęciu plik znika ze śluzy. System przygotowuje osobną kopię do przeglądu;
jej przyjęcie do kolejki **nie jest zgodą na eksport**. Zmiana oryginału nie zmienia kopii.
**Każdy plik to osobny wniosek.** W razie błędu cały wniosek pozostaje w kwarantannie
operatora; nie jest przekazywany częściowo. Brak pliku w śluzie nie potwierdza przyjęcia.
Zachowaj oryginał w katalogu domowym do potwierdzenia przez operatora. Automatyczny
status dla badacza, zgoda Lidera i publikacja pozostają do wdrożenia (#20).

Żeby wynik nie rozpadł się na niekompletne części:

- Nie zapisuj bezpośrednio do `/sluza-out` w wielu krokach (dopisywanie w pętli, nagłówek
  osobno a dane później) — każdy zapis może trafić jako osobny, niepełny wniosek.
- Pliki należące do siebie (np. `.shp`+`.shx`+`.dbf`, model + metadane) spakuj w **jedno**
  archiwum przed kopiowaniem: `tar -czf ~/wynik.tar.gz ~/wyniki/ && cp ~/wynik.tar.gz /sluza-out/`.
- Cały katalog kopiuj w całości jednym `cp -r ~/wyniki /sluza-out/`.
- Nazwy tymczasowe (`.*`, `*.tmp`, `*.part`, `*~`) są pomijane do czasu zmiany nazwy na docelową,
  więc zapis atomowy (plik tymczasowy → zmiana nazwy) nie trafi do kolejki jako niekompletny.

**Sesja:** serwer notebooków zamyka się po 30 minutach bezczynności, a sesja kończy
się po 12 godzinach niezależnie od aktywności (§9.5 Regulaminu). Zapisuj pracę.

**Sieć:** VM nie ma dostępu do internetu — dozwolone są tylko adresy z allowlisty Laboratorium (patrz konfiguracyjna allowlista proxy i zapora egress). Zasady instalacji pakietów ustawia Administrator Laboratorium i opisuje je `/docs/pakiety.md` (decyzja IMG-004). Wysyłanie danych WLB do zewnętrznych usług, w tym modeli LLM, jest zabronione (§31.3).

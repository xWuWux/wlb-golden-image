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

Plik od razu znika z katalogu i trafia do kolejki zatwierdzenia przez Kontrolera Przesyłu
Danych — nie da się go już odczytać ani zmienić. **Każdy plik to osobny wniosek.**

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

**Sieć:** VM nie ma dostępu do internetu. Pakiety instaluje administrator przez
nową wersję obrazu. Wysyłanie danych WLB do zewnętrznych usług, w tym modeli LLM,
jest zabronione (§31.3).

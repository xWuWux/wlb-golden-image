# Wirtualne Laboratorium Badawcze — skrót dla badacza

| Katalog      | Co tu jest                                         | Co możesz zrobić        |
|--------------|----------------------------------------------------|-------------------------|
| `~` (`/workspace/jupyter-<login>`) | Twoja przestrzeń robocza, objęta backupem | czytać i zapisywać |
| `/sluza-in`  | dane wejściowe zatwierdzone przez Kontrolera Przesyłu Danych | tylko czytać |
| `/data-mart` | kohorta OMOP przypisana do Laboratorium            | tylko czytać            |
| `/sluza-out` | wyniki do eksportu                                 | tylko zapisywać         |
| `/docs`      | dokumentacja platformy i skrypty pomocnicze        | tylko czytać            |

**Eksport wyników:** zapisz plik w `/sluza-out`, np. `cp wyniki.csv /sluza-out/`.
Plik od razu znika z katalogu i trafia do kolejki zatwierdzenia przez Kontrolera
Przesyłu Danych. Nie da się go już odczytać ani zmienić.

**Sesja:** serwer notebooków zamyka się po 30 minutach bezczynności, a sesja kończy
się po 12 godzinach niezależnie od aktywności (§9.5 Regulaminu). Zapisuj pracę.

**Sieć:** VM nie ma dostępu do internetu. Pakiety instaluje administrator przez
nową wersję obrazu. Wysyłanie danych WLB do zewnętrznych usług, w tym modeli LLM,
jest zabronione (§31.3).

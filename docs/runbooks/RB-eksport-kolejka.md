# Kolejka eksportu: prywatna kopia i manifest v1 (#20)

Status: podstawa procesu, **nie zatwierdzanie ani publikacja**. Wpis `pending_review`
nie oznacza zgody Lidera ani Kontrolera. #20 pozostaje otwarte. Nie instalujemy sudoers,
konta Kontrolera, serwera HTTP ani kanału wyjściowego. Helper jest tylko dla operatora
z istniejącymi uprawnieniami administracyjnymi, nie jest bezpiecznym API dla sudo.

## Dlaczego zmiana jest potrzebna

`mv`, `chown` i `chmod` nie cofają dostępu przez już otwarty deskryptor. `fuser`
sprawdza tylko chwilowy stan, a odstęp 120 s dla katalogów nie dowodzi kompletności.
Dawna kolejka mogła zmienić się po obliczeniu SHA-256. Rekurencyjne operacje na
źródle kontrolowanym przez badacza były dodatkowo podatne na wyścigi w katalogach.

Mover przejmuje wpis do prywatnego `.incoming.*/source`, a helper kopiuje bajty na
**nowe i-węzły**. Otwiera dzieci względem deskryptorów katalogów (`dir_fd`,
`O_NOFOLLOW`, `O_NONBLOCK`), odrzuca dowiązania, typy specjalne, mieszanych właścicieli
i wykryte zmiany źródła. Nie wykonuje rekurencyjnego chown/chmod na źródle.
Niedozwolony element zatrzymuje **cały** wniosek; nie eksportujemy cicho reszty.

To gwarantuje odcięcie gotowej kopii od deskryptorów badacza, nie spójność transakcyjną
aplikacji zapisującej wiele plików. Potrzebne jest nadal jawne zgłoszenie gotowości
(#33). Root, storage i konto administratora pozostają zaufane. Nie jest to WORM,
podpis cyfrowy, automatyczna anonimizacja ani dowód dopuszczalności eksportu.

## Format i interfejs

Dotychczasowa nazwa kolejki pozostaje czytelna (`czas_login_nazwa`), ale **wpis jest
teraz pakietem** z `payload` (plik/katalog) i `manifest.json`. Konsument nie może
interpretować samej nazwy ani obecności pliku jako zatwierdzenia. Pełna nazwa źródła
jest tylko w manifeście; w nazwie pakietu i logu niedozwolone znaki zastępuje `_`,
a nazwa jest ograniczona do 120 znaków. Kolizję rozstrzyga UUID. Nie używać nazwy
pakietu jako tożsamości wniosku; służy do tego `request_id`.

| Pole manifestu v1 | Typ / wartości | Znaczenie |
|---|---|---|
| `schema_version` | integer, `1` | wersja kontraktu |
| `request_id` | string, UUID v4 z movera | identyfikator, stały po utworzeniu |
| `state` | string, `pending_review` | wyłącznie oczekiwanie na przegląd |
| `created_at` | string, ISO 8601 UTC | czas wykonania kopii, bez gwarancji poprawności NTP |
| `requester.uid` | integer >= 0 | właściciel przejętego wpisu, nie argument badacza |
| `requester.username` | string | nazwa konta z NSS lub tekst UID, gdy brak konta |
| `original_name` | string | pełna niezaufana nazwa; nie wykonywać, nie wstawiać do HTML/shella |
| `digest_algorithm` | `sha256-file` / `sha256-inventory-v1` | jawna wersja algorytmu |
| `sha256` | string, 64 małe znaki hex | suma payloadu według wskazanego algorytmu |
| `entries` | lista `Entry` | dokładny spis zawartości, włącznie z pustymi katalogami |
| `Entry.path` | string | `.` dla korzenia, dalej ścieżki względne, separator `/` |
| `Entry.type` | `file` / `directory` | inne typy niedopuszczalne |
| `Entry.size` | integer >= 0 | rozmiar bajtów pliku; `0` dla katalogu |
| `Entry.sha256` | string | SHA-256 pliku; pusty string dla katalogu |

W kodzie kontrakt opisują `Entry`, `Requester`, `Manifest` (TypedDict). Funkcje:
`create(source: Path, destination: Path, original_name: str, request_id: str) -> Manifest`
oraz `verify(bundle: Path) -> Manifest`. Błąd oznacza wyjątek `SnapshotError` lub
`OSError`; CLI zwraca wtedy 1. Sukces CLI zwraca 0 i drukuje wyłącznie SHA-256.

```sh
# Istniejący root/operator, wyłącznie dla pakietu w chronionej kolejce:
sudo /usr/local/sbin/wlb-export-snapshot verify /workspace/.wlb-export-queue/PAKIET
```

`create SOURCE DEST ORIGINAL_NAME REQUEST_ID` jest wewnętrznym interfejsem movera.
`DEST` musi nie istnieć, a jego rodzic musi być prywatny. Nie udostępniać tej komendy
badaczom/Kontrolerowi przez sudo i nie pozwalać im wybierać ścieżek.

Spis jest preorder (rodzic przed dziećmi), dzieci posortowane według bajtów nazw
(`os.fsencode`). Suma katalogu to SHA-256 spisu zakodowanego jako JSON ASCII:
`ensure_ascii=True, sort_keys=True, separators=(",", ":")`, bez końcowego newline.
Prawa, UID, mtime ani absolutna ścieżka nie należą do sumy. Puste katalogi należą.
Dla pliku suma nadal jest SHA-256 jego bajtów. Dawny pipeline `find | sha256sum`
**nie weryfikuje katalogów v1**. `verify` porównuje również dokładny spis i algorytm,
a nie tylko jedną sumę. Nie weryfikuje prawdziwości metadanych zmienionych przez roota.

`requester` identyfikuje konto systemowe, nie osobę fizyczną. Przyjęty
[IMG-002](../adr/IMG-002-model-kont-badaczy.md) przewiduje konta stanowiskowe `uNN`;
platforma musi powiązać wniosek z historycznym przypisaniem osoby (czas/wersja
rejestru). Nie wolno odtwarzać tożsamości z aktualnego właściciela konta ani zakładać,
że ciąg `jupyter-*` jest docelowym modelem. Ten PR nie wdraża migracji kont.

Nie dodano ustawień `lab.env`/Ansible. `SNAPSHOT` to ścieżka sąsiedniego helpera
instalowanego przez tę samą rolę. `WLB_EXPORT_QUEUE`, `WLB_SLUZA_OUT`,
`WLB_IMAGE_CONF`, `WLB_DIR_SETTLE_SECONDS` zachowują znaczenie. Stałe bezpieczeństwa
helpera: `MAX_BYTES=100*1024**3` na wniosek (100 GiB), `MAX_ENTRIES=100000`,
`MAX_DEPTH=64`, `CHUNK_SIZE=1024**2` (1 MiB). To jawne ograniczenia implementacji,
nie zatwierdzona polityka projektu. Przekroczenie wymaga interwencji i osobnej ścieżki
dużego transferu; nie podnosić limitów bez oceny pamięci, czasu i wolnego storage.

## Publikacja do wewnętrznej kolejki i awarie

1. `flock` na `.mover.lock` serializuje usługę i `--once`. Drugie uruchomienie niczego
   nie przejmuje. Nie usuwać pliku blokady podczas pracy procesu.
2. Źródło jest przejmowane do `.incoming.*`; między filesystemami `mv` może kopiować.
3. Dane, manifest i katalogi kopii są synchronizowane (`fsync`). Gotowy pakiet jest
   przemianowany w obrębie kolejki; `sync -f` utrwala zmianę przed usunięciem źródła.
4. `export_request` informuje o gotowej kopii, nie o zatwierdzeniu. Trwały manifest
   jest lokalnym punktem odtworzenia; wysłanie do loggera nie dowodzi odbioru w SIEM.
5. Jakakolwiek pozostałość `.incoming.*` **blokuje dalsze przyjęcia**, także po restarcie.
   Nie wykonujemy automatycznego replay, usuwania ani publikowania takich danych.
   Badacz nadal może pracować w swoim katalogu. Usługa pozostaje uruchomiona, więc
   sam monitoring `systemctl is-active` nie wykrywa zablokowanej kolejki.

| Punkt awarii | Stan po restarcie | Działanie operatora |
|---|---|---|
| przed przejęciem | źródło zwykle w śluzie | usunąć przyczynę I/O, ocenić następny przebieg |
| podczas `mv` między dyskami | źródło i/lub częściowa kwarantanna | porównać obie kopie; nic nie usuwać automatycznie |
| kopiowanie, limit, zmiana źródła, niedozwolony typ | kwarantanna, brak gotowego wniosku | ustalić przyczynę, uzyskać kompletny wynik od badacza |
| po utworzeniu kopii, przed rename | pakiet wewnątrz kwarantanny | nie traktować go jako przyjętego |
| po rename, przed sprzątaniem/logiem | gotowy pakiet i kwarantanna, możliwy brak zdarzenia SIEM | zweryfikować pakiet, powiązać UUID, uzgodnić audyt; nie tworzyć duplikatu |

Przed interwencją zatrzymać `wlb-sluza-out.service`. Ustalić właściciela i skorelować
manifest/UUID, logi `snapshot_failed` i `export_request`. Sprawdzić wolny dysk,
zamontowanie udziałów i stan audytu. Kwarantannę przenieść **w obrębie zaufanego
storage WLB** do odrębnego obszaru sprawy, poza wzorcem `.incoming.*`, dopiero po
udokumentowanej decyzji operatora. Nie kopiować na laptop, nie wrzucać ponownie do
śluz automatycznie, nie publikować ani nie usuwać wg wymyślonej retencji. Następnie
uruchomić usługę i sprawdzić nowe przyjęcie na danych syntetycznych.

Alarmować na `snapshot_failed`, pozostałości `.incoming.*`, niski wolny dysk oraz
rosnący wiek/numer kolejki. Kontrakt zdarzeń jest w `observability/contract.yml`;
wdrożenie reguł alarmowych i dyżuru jest zadaniem operatora/#17, nie tego PR.
Kopiowanie wymaga miejsca na dodatkowy payload; limit per wniosek nie zastępuje
quota/rezerwy całej kolejki (#19/#32). Celowe błędne zgłoszenie może zatrzymać przyjęcia
(do usunięcia kwarantanny): świadomy koszt blokowania przy błędzie, nie odporność na DoS.

## Migracja i wycofanie

Istniejące wpisy bez manifestu nie są modyfikowane. `verify` odmawia ich weryfikacji.
Nie wolno dopisać manifestu i twierdzić, że dawny audyt wiązał tę kopię: jej zawartość
mogła zmienić się wcześniej. Uzgodnić ponowne zgłoszenie/przegląd, zachowując ślad
starego wniosku. Wstrzymać przyjęcia na czas aktualizacji helpera i movera.

Rollback obrazu nie usuwa pakietów v1; stary mover może dopisywać obok wpisy starego
formatu. Po rollbacku wstrzymać eksport i stosować weryfikator odpowiadający wersji
manifestu. Nie uruchamiać starego narzędzia, które uznaje każdy katalog za dane do
opublikowania. Backup musi zachować manifest i payload razem, a odtworzenie wymaga
ponownego `verify` i uzgodnienia stanu publikacji z platformą.

## Pozostałe decyzje przed ukończeniem #20

- Zgoda Lidera i decyzja Kontrolera powiązane z tą samą wersją wyniku, celem i odbiorcą;
  tożsamość z zaufanego uwierzytelniania, zakres per projekt, zakaz zatwierdzania własnego wniosku.
- Jawne zgłoszenie gotowości (#33), podgląd bez wykonywania makr/skryptów, kontrola
  danych źródłowych/anonimizacji, uzasadnienie odmowy i status dostępny tylko właścicielowi.
- Kontrolowana lokalizacja wyjściowa i idempotentny protokół publikacji z potwierdzeniem.
  Zatwierdzenie nie może być utożsamiane z przekazaniem.
- Retencja payloadu, odmów, metadanych i backupów; limity całej kolejki.
  Uwzględnić [IMG-006](../adr/IMG-006-zamkniecie-laboratorium-usuwanie.md) (warunkowy,
  wymaga potwierdzenia IOD) i [IMG-007](../adr/IMG-007-przepelnienie-logow-audytu.md)
  (ciągłość pracy przy awarii logowania). Kwarantanna blokuje tylko przyjęcia eksportu,
  nie sesje/obliczenia; brak potwierdzenia loggera nie oznacza niedostępności samego SIEM.
- E2E na docelowym storage, zabicie procesu/restart VM w punktach awarii, odtworzenie
  backupu i niezależny przegląd bezpieczeństwa. Testy jednostkowe nie dowodzą tych cech.

## Walidacja metadanych v1 (#162)

`validate_manifest(value: object) -> Manifest` sprawdza strukturę i typy w czasie
wykonania; TypedDict sam nie waliduje JSON. `verify` wywołuje ją przed odczytem
payloadu, a `create` przed zapisaniem gotowego manifestu. Błąd to
`SnapshotError`, obsługiwany przez istniejące CLI kodem 1, bez logowania zawartości.

Wymagane są dokładne zbiory pól Manifest/Requester/Entry, UUID v4 zapisany kanonicznie,
czas ISO 8601 z offsetem UTC, niepuste nazwy, całkowity nieujemny UID/rozmiar
(z wykluczeniem bool), obsługiwany algorytm i małe sumy hex SHA-256.
Spis zawiera 1–MAX_ENTRIES pozycji. Katalog ma size=0 i pustą sumę.
`valid_digest(value: object) -> bool` jest wspólną kontrolą składni sumy.
Dokładne ścieżki, kolejność, rozmiary i treść nadal porównuje istniejące inventory.

To zaostrzenie czytnika, bez zmiany formatu danych emitowanych przez mover.
Nieznane pola wymagają jawnej aktualizacji kontraktu/czytnika; nie dodawać do v1
ad hoc pól zatwierdzenia. Błędne historyczne manifesty pozostawić do wyjaśnienia,
bez automatycznej naprawy lub dopisywania tożsamości. Wewnętrzne wywołania create
muszą przekazywać UUID v4 (mover już pobiera go z jądra).

Walidacja potwierdza strukturę, nie autentyczność tożsamości, poprawność zegara,
zgodę na eksport ani odporność na modyfikację przez roota. Nie wdraża rejestru #102,
limitu całej kolejki, automatycznego recovery ani procesu Kontrolera #20.

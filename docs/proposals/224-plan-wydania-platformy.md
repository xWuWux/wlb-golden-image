# Plan realizacji #224 — wydanie całej platformy

Przegląd 2026-11-18, main `476b8adc12bc5d1b341e85f8d72dd96c55f6ca97`. Dokument jest propozycją podziału prac. Właściciele wskazani poniżej oznaczają role do obsadzenia przez zespół.

## Stan i zmiany od poprzedniej analizy

- #225 jest scalony. `ci/verify_platform_images.py` weryfikuje katalog czterech obrazów, wersje, sumy rzeczywistych plików i deklarowaną bazę.
- #317 jest scalony. `ci.yml` ma budowę bazy, matrix wariantów, wspólną datę, przekazanie metadanych oraz pełny wtorkowy przebieg. Klucz cache obrazu ma postać `image-<run_id>`.
- `release.yml` nadal uruchamia stary tor z tagu, przydziela contents:write jobowi budowy i publikuje metadane. Nie uruchamia walidatora ani nie wymusza czterech wariantów.
- `release.sh` nadal wyszukuje katalog general, pierwszy manifest Packera i znalezione sumy. `image-sca` nadal ma fallback po czasie modyfikacji locka.
- Migracja domyślnie wywołuje `tests/migration.sh "${PREV_IMAGE:-$IMAGE}" "$IMAGE"`. To umożliwia X→X.
- #71 zawiera decyzję PO o promocji obrazu i rekomendację minisign. Zewnętrzny magazyn, custody klucza i odbiór importera pozostają do potwierdzenia. #15 opisuje pilot Proxmox i runner KVM, ale stan uruchomionej infrastruktury wymaga potwierdzenia operatora.
- Podczas odczytu bieżący CI przeszedł etapy 1–4 wraz z code scanning i mutacjami. Budowa bazy nadal trwała. Brak pełnego wyniku nowej macierzy w tej ocenie.

## Krytyka i proponowane wymagania

| Cytat ze zgłoszenia lub dyskusji | Luka | Proponowany zapis |
|---|---|---|
| „Dzisiejsze warianty wlb-memory i wlb-radiologia” | Katalog ma również histologię. Wymienianie wariantów ręcznie będzie się rozjeżdżać | „Oczekiwany zestaw pochodzi z zatwierdzonej wersji katalogu. Na tej rewizji obejmuje general, memory, radiologia i histologia” |
| „budujemy raz wlb-general” | Sam job i klucz cache nie zapewniają tożsamości bajtów ani bezpiecznego rerunu | „Każdy kandydat wskazuje digest jednego wyniku budowy bazy. Każdy konsument przelicza pobrany plik. Rerun nie może mieszać wyników różnych prób” |
| „stabilny tag […] ten sam zatwierdzony zestaw” | Obecny push tagu uruchamia ponowny build. Brakuje związania etykiety RC z wersją w obrazie | „Obraz kandydata ma docelową wersję X.Y.Z. candidate_id rozróżnia RC. Stable publikuje odwołanie do odebranego manifestu i tych samych bajtów bez uruchamiania Packera” |
| „wynik wskazuje commit, digest, wersję polityki, runner i przebieg” | Dowolny JSON z success może wyglądać jak wynik CI. Brak dowodu producenta | „Weryfikator pobiera wymagania z zaufanej polityki, sprawdza tożsamość workflow, rewizję, próbę i digest obrazu oraz pochodzenie raportu. Raport z innego wariantu lub przebiegu jest odrzucany” |
| „bezpieczne ponowienie […] ten sam numer” | Lokalna blokada ani GitHub concurrency nie zabezpieczą wielu magazynów i importerów | „Publikacja kończy się warunkowym utworzeniem indeksu wersji. Ten sam manifest daje idempotentny wynik, inny digest daje konflikt. Semantyka musi być odebrana na wybranym backendzie” |
| Komentarz „skok kosztów o rząd wielkości” i „nie zmieści się w 200 min” | Podane czasy nie są pomiarem obecnej macierzy. #317 już dzieli pracę | „Zmierzyć czas krytycznej ścieżki, peak dysku, transfer i minuty runnerów na pełnym kandydacie. Ustalić budżet na podstawie tych danych” |
| „ograniczyć katalog albo rozszerzyć build” | Usunięcie niewygodnego wariantu tylko po to, by publikacja przeszła, zmienia zakres dostawy | „Zmiana katalogu wymaga jawnego odbioru właściciela i nowego kandydata. Brak obowiązkowego wariantu zatrzymuje promocję” |
| „przed UAT/PROD […] podpis i audyt” | Odkładanie odbioru awarii na końcowy etap zostawia ryzyko pierwszej publikacji | „Test przerwania publikacji, sprawdzenia podpisu oraz niezależnego pobrania jest wymagany przed pierwszą stabilną promocją. Testy środowiska docelowego poprzedzają jego uruchomienie” |

## Kontrakt do zamrożenia przed równoległą implementacją

Zachować obecny image manifest schema 1. Jego ścisły walidator odrzuca dodatkowe pola. Dla kontraktu platformowego uzgodnić wersjonowaną otoczkę i adapter obrazu, zamiast dopisywać pola do v1. Poniższe pola są propozycją nowej otoczki.

| Pole | Typ i producent | Konsument |
|---|---|---|
| schema_version | int, jawnie 1 dla otoczki platformowej | Walidator odrzuca nieznane wersje |
| version / candidate_id | str X.Y.Z / str X.Y.Z-rc.N, koordynator rezerwacji | Build osadza version, raporty i promocja wiążą candidate_id |
| policy_sha256 / catalog_sha256 | str, 64 małe hex, koordynator z zatwierdzonych plików | Weryfikator odczytuje zaufane dokumenty i przelicza sumy |
| components | mapa identyfikatorów do repo, pełnego commit SHA i referencji artefaktów | Składacz manifestu i konsument wydania |
| artifacts | lista względnych ścieżek, size_bytes:int>=0 i sha256:str | Staging, magazyn i importer, odrzucają nieoczekiwane pliki i niebezpieczne ścieżki |
| build_attempt | repo, workflow_ref, commit_sha, run_id:str i run_attempt:int>=1 | Producent zapisuje, weryfikator porównuje z zaufanymi metadanymi przebiegu |
| evidence | rekordy test_id, variant, artifact_sha256, result, policy_sha256 i referencja dowodu | Bramka porównuje z oczekiwaną macierzą, odrzuca brak, duplikat, SKIP, błąd, anulowanie wymaganej próby |
| predecessor | digest poprzedniego wspieranego manifestu albo jawny bootstrap z decision_ref | Test migracji i importer |
| promotion | osobny zapis kandydata, digestu manifestu, roli, decyzji i czasu UTC | Rejestr wydania oraz wdrożenie Laboratorium |

Manifest kandydata po zatwierdzeniu jest niezmienny. Decyzja promocji jest osobnym rekordem odnoszącym się do digestu. Podpis obejmuje zapisane bajty manifestu, bez ponownej serializacji u importera. Polityka zaufania do podpisującego pochodzi z niezależnej konfiguracji importera, a nie z pobranego manifestu.

`PREV_IMAGE` zachowuje typ ścieżki tekstowej istniejącego harnessu. Tryb wydania wymaga zgodnego digestu poprzednika poza zatwierdzonym bootstrap. Klucze prywatne są dostępne wyłącznie osobnemu etapowi podpisu po weryfikacji. `run_id` i `run_attempt` pochodzą z GitHuba. Każdy rerun wskazuje odebrane artefakty konkretnej próby.

Proponowane punkty wejścia mają być małe i wykorzystać istniejący verify:
- `assemble_candidate(spec: Path, staging: Path, output: Path) -> None` składa manifest ze zweryfikowanych, jawnych wejść. Nie dobiera plików po mtime. Wywołuje adapter obecnego walidatora obrazów.
- `verify_candidate(manifest: Path, staging: Path, policy: Path) -> None` odrzuca brak, konflikt lub niespójny dowód. CLI ma kod 0/1.
- `promote_candidate(manifest_digest: str, decision: Path) -> PromotionResult` używa backendu wybranego w #71. Wynik rozróżnia published, already_published, conflict. Decyzja i zaufanie są weryfikowane przed zapisem.

To proponowane kontrakty do recenzji, a implementacja może je uprościć po uzgodnieniu danych. Unikać drugiego niezależnego katalogu wariantów.

## Pakiety do przydzielenia

| Pakiet i rola | Granice zmian / wynik PR | Zależność | Test odbioru |
|---|---|---|---|
| A0 — właściciel platformy + integrator | Katalog komponentów, wymagania testów, wersja otoczki i JSON fixtures. Wskazać komponenty zewnętrzne, ownerów oraz brakujące repo | Start | Syntetyczny kompletny kandydat i odrzucony kandydat z brakującym komponentem. Ownerzy akceptują zakres |
| A1 — agent provenance | #181, Packer i zbieranie artefaktów. Digest bazy przed budową warstwy, zapis próby i jawne katalogi per wariant | A0 dla pól, można eksplorować wcześniej | Podmieniona baza lub lock, mieszane próby, stary plik runnera i nieprawidłowy katalog są odrzucone |
| A2 — agent walidatora | Otoczka platformowa, adapter schema 1, expected evidence z polityki. Tylko moduły walidacji i unit | A0 | Obcy/zdublowany wariant, błędny digest, brak/duplikat raportu, SKIP, podpisana deklaracja bez zaufanego producenta nie przechodzą |
| A3 — agent CI | Wydzielić wspólny tor build/test z #317 i release orchestration. Jeden właściciel ci.yml, release.yml i dispatchera | A0, A1, A2 | Pełny katalog dla kandydata, digest bazy sprawdzany po pobraniu, flavor nie odbudowuje po cichu bazy. Porażka jednego joba blokuje komplet |
| A4 — operator magazynu + agent adaptera | #71/#19. Prywatny staging, pobranie i przeliczenie sum, commit indeksu warunkowy, retencja | A0 i decyzja backendu | Przerwany upload, awaria przed/po indeksie, dwa równoległe zapisy tej samej wersji, podmiana obiektu, idempotentny rerun |
| A5 — bezpieczeństwo + opiekun klucza | #260/#59. Rozdzielenie uprawnień, minisign, konfiguracja zaufania importera, rotacja i unieważnienie | A0, A4 | Obcy/unieważniony klucz i zmienione bajty odrzucone. Brak aprobaty blokuje publikację. Pozytywna weryfikacja offline |
| A6 — agent migracji + operator storage | #8/#13/#19, jawny poprzednik per wariant. Raport X→Y i rollback, syntetyczne nowe dane po migracji | A0, dostęp do poprzednika | Brak poprzednika i przypadkowe X→X blokują wydanie. Zapis po migracji nie ginie przy wybranej procedurze naprawy |
| A7 — integrator wydania + PO | Promocja, rezerwacja wersji, komunikacja, rytm/wsparcie/hotfix. Integracja wyników A3–A6 | A3–A6 | RC→stable ma identyczne bajty. Ponowienie tej samej promocji jest bezpieczne. Inny digest dla tej samej wersji odrzucony |
| A8 — niezależny odbiorca | Świeży host/VM pobiera opublikowany zestaw, weryfikuje podpis i digests, uruchamia warianty | A7 | Udokumentowany import, odczyt wersji/commita VM, akceptacja, migracja i pomiar odtworzenia |

A1, A2 i przygotowanie A4/A5/A6 można prowadzić równolegle po A0. A3 przejmuje pliki workflow po ustaleniu interfejsów A1/A2. Pozostali agenci przekazują mu zmiany wejść/wyjść zamiast równolegle edytować release.yml. Jeden integrator odpowiada za zgodność fixtures i kolejność merge.

Każdy PR zawiera zakres, wersję kontraktu, rzeczywisty wynik testów, nierozstrzygnięte zależności i brakujące dowody. Nie zmieniać równolegle kontraktu i jego konsumentów w nieskoordynowanych branchach. Zmianę polityki/katalogu recenzuje właściciel, implementację recenzuje osoba spoza jej autora.

## Kolejność przełączenia wydawania

1. A0 i pierwszy PR A2 z fixtures można dostarczyć bez dostępu do storage.
2. A1/A3 tworzą kompletnych kandydatów w CI/DEV i zbierają dane o kosztach.
3. A4/A5/A6 przechodzą testy awarii i importu w środowisku izolowanym.
4. A7 uruchamia promocję. Stary trigger v* musi zostać przełączony w tej samej zmianie, aby stabilny tag nie uruchomił rebuilda.
5. A8 wykonuje odbiór. Wydanie i decyzja wdrożenia do danego Laboratorium mają oddzielne zapisy.

## Decyzje, skutki i alternatywy

| Decyzja do potwierdzenia | Skutek | Alternatywa |
|---|---|---|
| Wszystkie cztery obrazy obowiązkowe | Awaria jednego blokuje wydanie zestawu | Wersjonowane profile zestawu zatwierdzane przed budową. Brakujący wariant nie może zostać usunięty z gotowego kandydata tylko dla zielonej bramki |
| Runner Proxmox wewnątrz sieci | Krótsza droga transferu, ale kod buildu wymaga izolacji od infrastruktury i sekretów | Hostowany CI i tymczasowy magazyn z kontrolowanym pobraniem, kosztem transferu i ekspozycji dodatkowego serwisu |
| Minisign offline, rekomendacja #71 | Potrzebny opiekun klucza i dystrybucja zaufania | Podpis z kluczem przez standaryzowaną platformę podpisu. Potwierdzić wsparcie przed wyborem sprzętowego klucza |
| Stała wersja docelowa w RC | VM może pokazywać X.Y.Z przed stabilną promocją | Osobny candidate_id w rejestrze dostawy i widoczny status środowiska |
| Retencja poprzedników | Koszt miejsca i utrzymania starszych wersji | Zatwierdzony okres wsparcia i plan wycofania. Kopia qcow2 nie zastępuje backupu danych |
| Odtwarzalne źródła APT | Koszt utrzymania snapshotów, w tym repo zewnętrznych | Najpierw zachować testowane bajty i pełny inwentarz. Snapshoty wdrażać jako osobny kontrakt bez deklaracji bitowej reprodukowalności |
| Wymagane testy w kandydacie | Więcej minut i dłuższy cykl niż dla PR | Opt-in zachować dla PR, pełną macierz stosować tylko do kandydata. Koszt ustalić pomiarem |

Nie ustalono tu retencji, RPO/RTO, miejsca przechowania klucza ani zatwierdzających. Właściciel operacyjny musi wskazać ich wartości przed odbiorem odpowiednich pakietów. UAT/PROD oraz realny stan magazynu wymagają potwierdzenia przez operatora.

## Priorytety

1. Zamrozić kontrakt i obsadzić ownerów A0.
2. Zapisać rzeczywiste wejście bazy oraz powiązać testy z digestami i próbami.
3. Składać pełny kandydat przez wspólny tor #317, bez autodetekcji resztek.
4. Odebrać przerwanie publikacji, podpis, import i migrację z poprzednika.
5. Przełączyć stable na promocję tych samych bajtów oraz zatwierdzić retencję i wsparcie.

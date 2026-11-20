# Plan wdrożenia kontrolowanego wydania eksportu (#20)

[Niezweryfikowane — propozycja procesu i kontraktów do zatwierdzenia, poza opisanym przeglądem kodu.]

Przegląd 2026-11-18, main `476b8adc12bc5d1b341e85f8d72dd96c55f6ca97`. Powiązania #4, #33, #102, #18, #162, #208, #333, #19, #32, #81 i #193. #297 jest scalony, ale [runbook wydania](../runbooks/RB-sluza-wydanie-tymczasowe.md) nadal ma status DRAFT i wymaga zatwierdzenia przed użyciem operacyjnym. Zatwierdzenia przez właściwe osoby i kanału docelowego nie mogę zweryfikować na podstawie repozytorium.

## Co działa w źródłach i co wymaga dostarczenia

[Snapshot](../../ansible/roles/storage/files/wlb-export-snapshot) tworzy prywatny pakiet z payloadem i manifestem v1. Czytnik wymaga dokładnego zbioru pól i stanu pending_review. Mover przygotowuje kolejkę, zwrot oraz zdarzenia przyjęcia. Kontrakt obserwowalności opisuje przyjęcie i błędy, ale nie zawiera docelowego workflow decyzji i publikacji.

W tej analizie uruchomiono dwa sprawdzenia na syntetycznym pliku z aktualnym helperem. verify przechodzi dla utworzonego pakietu, a po zmianie state na approved odmawia. Dla pojedynczego pliku payload jest plikiem bezpośrednio pod bundle/payload. Nie wykonano transferu danych rzeczywistych, odbioru SIEM ani próby na docelowej VM.

[Wniosek] Najmniejszy użyteczny produkt to kolejka spraw z autoryzowanymi decyzjami i jedna kontrolowana trasa publikacji. Operator powinien otrzymać gotową dyspozycję zweryfikowanego wydania, a Kontroler pracować w interfejsie projektu bez root i szukania plików po VM. W pierwszym pilotażu wykonanie dyspozycji może być operatorskie. Zmniejsza to zakres pierwszej dostawy przy zachowaniu jawnego ręcznego kroku.

## Problemy propozycji interim i konkretne poprawki

| Cytat | Problem | Propozycja |
|---|---|---|
| „przełączające stan manifestu na approved” | Aktualny validate_manifest odrzuca taki stan. Zmiana niszczy zgodność czytnika v1 | Osobny rejestr decyzji i wykonania odnosi się do niezmienionego manifestu v1 oraz jego digestu |
| „--approver <id> […] Wymusza dwuosobowość” | Operator może wpisać cudzy identyfikator. Sam tekst nie jest dowodem działania zatwierdzającego | Uwierzytelniona sesja decydenta albo weryfikowalny rekord decyzji z zaufanego systemu. CLI operatora jedynie importuje tę decyzję |
| „Lider/IOD” / „Kontroler/Lider” | Łączy role wymagające osobnego rozstrzygnięcia. Załączony Regulamin §14 wymienia zgodę Lidera oraz weryfikację Kontrolera | Osobne dowody zgody Lidera i decyzji Kontrolera. Rolę IOD oraz dopuszczalne łączenie funkcji potwierdza właściciel procesu |
| „sudo grep -rl […] \"$QUEUE\"/*/manifest.json” | Globbing wykonuje powłoka operatora przed sudo, a katalog jest root-only. Dopasowanie tekstu zależy od formatu JSON i nie wykrywa jednoznaczności UUID | Narzędzie po stronie uprawnionego czytnika parsuje JSON, waliduje UUID i wymaga dokładnie jednego zgodnego pakietu |
| „sudo rsync -a operator@VM…” | Lokalne sudo nie nadaje uprawnień zdalnemu rsync do root-only kolejki. BUNDLE z sesji zdalnej nie staje się automatycznie zmienną lokalną | Jedno kontrolowane narzędzie eksportu po stronie WLB z autoryzowaną dyspozycją i jawnie wybranym odbiornikiem |
| „sha256sum payload/<nazwa>” | Dla pojedynczego pliku payload jest plikiem. Weryfikacja katalogu wymaga dokładnego algorytmu inventory-v1 | Uruchomić zgodną wersję verify na odebranym pakiecie lub identyczny, odebrany adapter. Nie zastępować go find/sha256sum |
| „Zgodność […] z potwierdzeniem badacza = ten sam, kompletny wniosek” | Potwierdzenie należące do UID badacza nie jest autorytatywnym dowodem decyzji i kompletności wyniku aplikacji | Decyzja wiąże zweryfikowany pakiet, hash manifestu, zakres i odbiorcę. Potwierdzenie służy badaczowi do korelacji |
| „Zaloguj wydanie […] niezaprzeczalność” | Logger nie dowodzi odbioru SIEM ani wykonania publikacji. Root może zmienić lokalny stan | Trwały zapis dyspozycji przed wydaniem, dowód odbiornika po publikacji i odrębne monitorowanie dostarczenia zdarzeń |
| „Skopiuj […] na stację operatora (poza VM)” | W tych bajtach już następuje przekroczenie granicy. Kanał administracyjny i brak egress badacza nie zatwierdzają celu | Zatwierdzić urządzenie/obszar stagingowy i trasę przed pierwszym bajtem. Szyfrowanie, dostęp i sprzątanie obejmują też kopię operatora |
| „nie da się dograć na żywo […] trzeba redeploy” | Brak dowodu, że wszystkie elementy wymagają zmiany VM. #193 rozróżnia klasy aktualizacji | Interfejs decyzji może powstać poza VM. Adapter VM wdrażać kontrolowaną zmianą. Zmiany wspólnych usług wymagają okna i odbioru |
| „do czasu wdrożenia #20” / „z chwilą scalenia #20” | Merge może poprzedzać instalację i odbiór. Natychmiastowe wycofanie procedury może pozostawić brak działającego kanału | Wycofać interim po odbiorze konkretnego wdrożenia i sprawdzeniu wznowienia oraz komunikacji dla operatorów |
| „Pełna ścieżka […] kompletny ślad” | Brak jednoznacznych etapów, warunków i scenariuszy awarii | Jedna macierz odbioru obejmuje zgodę, doprecyzowanie, odmowę, publikację, ponowienie, odbiór i odtworzenie |

Fragmenty z pytania częściowo różnią się od scalonego runbooka #297. W szczególności aktualny runbook już używa verify i jawnie wymaga zatwierdzenia procedury. Wymienione błędy poleceń z pytania nie są wynikiem odtworzenia działającej procedury na VM.

## Model procesu do uzgodnienia

[Wniosek] Granica WLB obejmuje VM i zatwierdzony obszar przeglądu Kontrolera. Podgląd poza VM wymaga osobno autoryzowanego transferu do tego obszaru, praw dostępu, retencji i rejestracji. Obszar przeglądu nie jest docelowym odbiorcą eksportu. Test zero bajtów przed zgodami dotyczy odbiornika końcowego. Osobna próba sprawdza, że dane do przeglądu trafiają wyłącznie do uprawnionej strefy i osoby. Bez potwierdzenia tej granicy zdalnego podglądu nie można uznać za dopuszczony.

[Wniosek] Rozdzielić niezmienny pakiet v1, decyzje osób i stan operacji publikacji. Nie dodawać pól do v1 ad hoc.

1. Badacz przygotowuje wynik i zgłasza gotowość według uzgodnionego #33. Przyjęcie nadaje request_id i tworzy prywatny pakiet.
2. Rejestr spraw wiąże request_id, lab_id, project_id, historyczne assignment_id oraz hash manifestu i payloadu.
3. Lider podejmuje decyzję o zakresie. Kontroler przegląda tę samą wersję danych w ograniczonym, izolowanym środowisku bez automatycznego uruchamiania zawartości i pobierania zasobów zewnętrznych.
4. Kontroler zapisuje approved, rejected albo needs_information. Uwierzytelnienie, uprawnienie projektowe i rozdział ról są sprawdzane po stronie usługi. Nazwa roli w argumencie CLI nie jest źródłem uprawnień.
5. Gdy oba wymagane dowody są ważne, wykonawca rezerwuje operation_id i zapisuje dyspozycję z destination_id oraz digestami. Następnie pobiera zweryfikowane bajty do prywatnego stagingu i publikuje je przez jeden odebrany adapter.
6. Stan published wymaga potwierdzenia docelowego systemu, object_id i digestu opublikowanych danych. Odbiór przez człowieka jest osobnym stanem, jeśli kanał potrafi go zmierzyć.
7. Utrata odpowiedzi daje publication_unknown. Wykonawca uzgadnia operation_id z odbiornikiem przed kolejną próbą. Restore lokalnej bazy także wymaga tego uzgodnienia.
8. Badacz widzi status własnej sprawy i dozwolony powód. Dostęp opiera się na tożsamości, a UUID sam nie jest tokenem uprawnień.

[Wniosek] Cykl decyzji może obejmować pending_review → needs_information/rejected/approved, a wykonanie approved → publishing → published lub publication_unknown/failed. Decyzje zapisujemy historycznie. Zmiana payloadu, odbiorcy albo celu wymaga ponownego zatwierdzenia. Nowe dane tworzą nowy pakiet z relacją do poprzedniego. Dopuszczalność wycofania zgody w trakcie publikacji wymaga jawnej polityki i testu punktu przekroczenia granicy. Zawieszenie konta lub zmiana przypisania przed wydaniem wymaga ponownej oceny uprawnień.

[Wniosek] Przed publikacją wymagamy trwałego lokalnego zapisu decyzji i dyspozycji. Podczas awarii SIEM zdarzenia mogą czekać w outboxie, a stan dostarczenia jest widoczny. Czy brak zdalnego potwierdzenia SIEM ma zatrzymać wydanie, musi rozstrzygnąć właściciel w zgodzie z IMG-007. Awaria zapisu rejestru zatrzymuje nowe wydanie. Uzgodnienie operacji po przerwaniu jest wymagane przed ponowieniem.

## Kontrakty proponowanego pierwszego inkrementu

| Element | Typ i zakres | Producent / konsument |
|---|---|---|
| request_id | kanoniczny UUID v4 z istniejącego manifestu | Mover → rejestr spraw. Identyfikator obejmuje też namespace lab_id |
| manifest_sha256 | str, 64 małe hex, suma dokładnych bajtów v1 | Zaufany ingest → decyzja i worker. Zmiana metadanych po decyzji wymaga wyjaśnienia |
| payload_digest, digest_algorithm | istniejące typy v1 | verify → decyzja, staging i odbiornik |
| assignment_id | niezmienna referencja do historycznego przypisania, schema do uzgodnienia z #102 | Rejestr platformy → ingest i audyt, bez odgadywania z obecnego loginu |
| Decision | osobny wersjonowany rekord: decision_id, actor_ref, role, project_id, request_id, manifest_sha256, destination_id, purpose_ref, outcome, reason_ref, timestamp, policy_version | Uwierzytelniony interfejs → ledger. Actor_ref pochodzi z zaufanego uwierzytelnienia |
| destination_id | identyfikator wcześniej skonfigurowanego celu i odbiorcy, str | Administrator kanału → decyzja i adapter. Żądanie nie podaje dowolnej ścieżki, hosta ani URL |
| operation_id | UUID operacji publikacji i klucz idempotencji | Rejestr spraw → worker i odbiornik. Jedna aktywna rezerwacja na wersję zatwierdzonego wydania |
| Receipt | operation_id, destination_object_id, digest, size, status, czas, dowód źródła | Zaufany adapter odbiornika → potwierdzenie publikacji i uzgodnienie po restore |

Proponowane funkcje implementacyjne do przeglądu:
- resolve_request(queue: Path, request_id: UUID) -> VerifiedRequest. Parsuje v1 i odrzuca brak, duplikat, legacy, symlink lub konflikt. Nie przyjmuje dowolnej ścieżki bundle od roli Kontrolera.
- record_decision(request: VerifiedRequest, actor: AuthenticatedActor, command: DecisionCommand) -> Decision. Sprawdza projekt, rolę, digest oraz wersję sprawy w transakcji i trwale zapisuje decyzję wraz ze zdarzeniem outbox.
- prepare_release(request_id: UUID, decision_ids: list[UUID], destination_id: str) -> ReleaseOperation. Ponownie sprawdza ważność zgód i tworzy pojedynczą dyspozycję.
- reconcile_publication(operation_id: UUID) -> PublicationState. Odczytuje dowód odbiornika i dopiero potem zezwala na wznowienie lub eskaluje do operatora.

[Wniosek] Parser i model transakcji można rozwijać przed wyborem UI. Dane uwierzytelnienia i ledger nie powinny być kontrolowane przez badacza ani opierać się na jego ścieżkach. Gdy wybrany backend nie potrafi obsłużyć idempotencji i uzgadniania wyniku, automatyczne ponowienie powinno być zastąpione stanem wymagającym operatora.

## Pakiety do przydzielenia

| Pakiet | Właściciel do wyznaczenia | PR i kryteria odbioru |
|---|---|---|
| E0 — polityka i interim | Właściciel procesu + Lider + Kontroler + operator, konsultacja IOD | Role, zatwierdzony cel, klasy danych, SLA, prywatność, retencja i ścieżka awaryjna. Wskazanie rzeczywistego zatwierdzenia runbooka |
| E1 — kontrakt i czytnik | Agent storage | VerifiedRequest i zgodność v1. Test pliku/katalogu, kilku UUID, niejednoznaczności, podmiany i legacy |
| E2 — rejestr decyzji | Agent backend + recenzent IAM | Uwierzytelnione role per projekt, historia decyzji, optimistic concurrency i outbox. Test samozatwierdzania, konfliktu i brakującej zgody |
| E3 — interfejs spraw | Agent UI/produkt + Kontroler | Lista ograniczona projektem, podgląd izolowany, approve/reject/needs_information, status właściciela. Kontroler nie szuka pakietów przez SSH |
| E4 — jedna trasa wydania | Agent transportu + operator infrastruktury | Ograniczony adapter VM i rejestr dozwolonych celów. Test odbioru bajtów, praw, odbiorcy i digestu |
| E5 — worker i recovery | Agent workflow | Dyspozycja, prywatny staging, publikacja i reconcile. Zabicie procesu na każdym etapie oraz konkurencyjne ponowienie |
| E6 — audyt/status/SLA | Agent obserwowalności + właściciel procesu | Schemat nowych zdarzeń, odbiór SIEM, alarm, status prywatny. Jawny kalendarz i moment rozpoczęcia zegara |
| E7 — odbiór i przełączenie | Niezależny tester + operator | E2E na docelowym storage, canary #333, restore po publikacji, podstawowe aplikacje i wycofanie interim po wdrożeniu |

E0/E1 poprzedzają zamrożenie kontraktu. E2, prototyp E3 i przygotowanie E4 można prowadzić równolegle po uzgodnieniu danych. E5 scala kontrakty. Jeden integrator utrzymuje granicę snapshot/mover, a drugi odpowiada za usługę decyzji/publikacji. Żaden pakiet nie nadaje a01 ogólnego sudo ani nie wykorzystuje obecnego helpera jako dowolnego uprzywilejowanego API.

## Macierz testów przed publikacją danych rzeczywistych

- Przyjęto plik lub katalog, ale brakuje zgody Lidera, decyzji Kontrolera albo dozwolonego celu → zero bajtów u kontrolowanego odbiornika.
- Obcy projekt, fałszywe actor_ref, to samo konto w różnych Labach, ponownie przydzielone u01 → odmowa lub jawny konflikt.
- Zmiana manifestu/payloadu, odbiorcy i celu po zgodzie → brak publikacji, ponowny przegląd.
- Poprawny proces → dokładnie zatwierdzony payload u właściwego odbiorcy i weryfikowalne potwierdzenie.
- Utrata odpowiedzi po publikacji, dwa workery, replay starego polecenia → rozpoznanie istniejącego wyniku bez niekontrolowanej ponownej wysyłki.
- Niekompletny transfer → obiekt niedostępny odbiorcy do odbioru kompletności.
- Pełny dysk rejestru/stagingu, zanik sieci/SIEM i restart VM → jawny stan, zachowane dowody i procedura wznowienia.
- Restore kopii sprzed publikacji → uzgodnienie z docelowym rejestrem przed wznowieniem.
- Podgląd złośliwego HTML/archiwum/makra → brak wykonania treści i nieautoryzowanych połączeń. Limity dekompresji i zasobów.
- Rejestr/status/log nie ujawniają obcych nazw, treści wyników ani tokenów odbioru.
- Normalne notebooki, RStudio, GUI, zapis home i śluza nadal przechodzą regresję podczas i po wydaniu.
- Zamknięcie projektu, odrzucenie, retencja i backup → osobne zaakceptowane scenariusze bez automatycznego zgadywania okresów.

## Wymagania dokumentów i decyzje otwarte

W załączonym SLA §4, strona 2, zapisano 24 godziny robocze dla weryfikacji Output, trzy decyzje i przedział 08:00–16:00. Wyznaczenie startu zegara eksportu, strefy czasowej, świąt i wpływu doprecyzowania wymaga potwierdzenia właściciela. Nie zakładamy automatycznego pauzowania zegara.

Załączony Regulamin, §14 na stronie 8, wymienia zgodę Lidera oraz kontrolę Kontrolera, zakaz eksportu danych źródłowych i ograniczenia urządzeń osobistych. Ustępy 4 i 9 mają odmienne zapisy dotyczące uzasadnienia odmowy. Ujednolicenie zakresu uzasadnienia i roli IOD należy do właściciela dokumentu. Wersji prawnie obowiązującej i faktycznej akceptacji tych plików nie mogę zweryfikować. To odczyt wymagań, bez oceny prawnej.

[Wniosek] Najpierw należy potwierdzić: zatwierdzony kanał i obszar stagingowy, tożsamość/rolę decydentów, wymagany rozdział osób, autorytatywny rejestr spraw i przypisań, zasady retencji i dostępność operatora. Można przygotować testy kontraktów bez rozstrzygania wyboru panelu.

## Priorytety

1. P1 — poprawić plan zmiany v1 i powiązać decyzję z uwierzytelnioną osobą, projektem oraz konkretnymi bajtami.
2. P1 — zatwierdzić kanał/staging i udostępnić Kontrolerowi listę oraz podgląd spraw bez dostępu root.
3. P1 — dostarczyć rejestr decyzji i wykonania z idempotencją oraz uzgodnieniem po przerwaniu i restore.
4. P1 — odebrać canary, negatywne decyzje, ponowienia i podstawowe aplikacje na właściwej VM i storage.
5. P2 — wdrożyć prywatny status, audyt/SLA/retencję i wycofać interim po odbiorze konkretnego wdrożenia.

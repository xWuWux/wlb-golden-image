# CD na żywą VM Laboratorium — propozycja polityki L/D

Status: **do decyzji, nie wdrożono**. Zgłoszenie: [#193](https://github.com/xWuWux/wlb-golden-image/issues/193).
Dokument nie jest przyjętym ADR i nie upoważnia do aktualizacji produkcji.

## Kontekst i zakres

Podstawa sprawdzona na `main` przy commicie `2671ddd`:

- `ansible/roles/base/tasks/main.yml` aktualizuje system podczas budowania obrazu;
  zadanie jawnie zaznacza, że VM nie aktualizuje się sama.
- [RB-05](../runbooks/RB-05-aktualizacja-i-rollback.md) opisuje wymianę dysku systemowego,
  zachowanie dysku roboczego, kopię bazy oraz weryfikację migracji. Wymaga okna
  ogłoszonego co najmniej 24 h wcześniej. Nie dowodzi to zakazu awaryjnej procedury CVE.
- [IMG-004](../adr/IMG-004-instalacja-pakietow-badacz.md) przyjmuje kuratorowaną
  allowlistę i `RESEARCHER_PACKAGE_INSTALL=deny|mirror`; nie definiuje CD systemu.
- [#96](https://github.com/xWuWux/wlb-golden-image/issues/96) proponuje oddzielną warstwę
  aplikacji. Ten dokument uzupełnia ją o bezpieczny moment aktywacji.

Cel: dodawać zatwierdzone narzędzia bez restartu istniejących obliczeń i bez zapisu
przez mechanizm wdrożenia do danych badacza. Nie obiecujemy zerowego wpływu na
wydajność: pobieranie i rozpakowywanie zużywa CPU, RAM, sieć i I/O.
Warstwa systemowa pozostaje zarządzana przez wydania obrazu; nowe środowiska aplikacji
muszą mieć własny rejestr wersji, żeby stan VM był odtwarzalny.

## Dlaczego sam weryfikator nie wystarczy

`ps`, `top`, `lsof`, `fuser` i mapowania w `/proc` pokazują stan chwilowy.
Proces może później otworzyć plik, załadować moduł albo uruchomić podproces.
`dpkg -L` nie opisuje pełnych skutków skryptów instalacyjnych, triggerów i restartów.
Brak konfliktu w skanie nie uprawnia do aktualizacji in-place.

Przełączenie dowiązania też nie wystarcza: późny import przez wspólną ścieżkę może
pobrać nową bibliotekę do starego procesu. Start sesji musi rozwiązać wersję raz
oraz przypiąć rzeczywiste ścieżki interpretera, bibliotek, zasobów i podprocesów.
Stara wersja pozostaje dostępna do zakończenia wszystkich jej użytkowników.

Hub, `loginctl`, jednostki systemd i cgroups dostarczają sygnałów pomocniczych.
Brak sesji, cull i wylogowanie nie dowodzą zakończenia zadania w tle.
PSI służy do odraczania pracy pod presją, nie do gwarantowania izolacji.
Brak telemetrii nie może awansować zmiany do toru L.

## Proponowana polityka

| Warunek | Tor L — na żywo | Tor D — odroczony |
|---|---|---|
| Zakres | Nowe, samodzielne środowisko w wersjonowanym katalogu | OS, jądro, TLJH, wspólne biblioteki, restarty i nieznany wpływ |
| Istniejące procesy | Pozostają przypięte do starej wersji | Kontrolowane zakończenie według zatwierdzonej polityki |
| Aktywacja | Atomowa publikacja wersji dla nowych startów | Blokada nowych startów, ponowne sprawdzenie aktywności, okno |
| Pakiety systemowe | Wykluczone w pierwszej wersji | RB-05; staging nie oznacza instalacji |
| Niepewność | Odroczenie | Oczekiwanie na decyzję/operatora |

Podpis i zatwierdzenie wymagane są w obu torach. Podpis potwierdza pochodzenie,
a nie bezpieczeństwo zawartości. Nieznany lub niepoprawny bundle jest odrzucany,
a nie wykonywany później w D.

## Agent i granice zaufania — projekt, nie gotowy interfejs

Proponowana nazwa: `wlb-cd-agent`, transport pull z kuratorowanego kanału.
Pull nie jest sam w sobie zabezpieczeniem: przejęty podpisujący lub instalator root
pozostaje zagrożeniem. Rozdzielić pobieranie/weryfikację bez uprawnień od minimalnej
operacji publikacji. Wykluczyć dowolne skrypty instalacyjne w torze L.

Dane (`/workspace`, `/projekt`, `/home`, śluzy i `/data-mart`) nie są celami instalacji.
Allowlista tekstowych prefiksów to za mało: odrzucać traversal, ścieżki absolutne,
ucieczki przez symlinki/hardlinki, pliki urządzeń i nieoczekiwane punkty montowania.
Wymagana izolacja zapisu na poziomie uprawnień i przestrzeni montowań; osobny dysk
nie chroni danych przed uprzywilejowanym procesem.

Trwały stan agenta na dysku roboczym wymaga osobnego, chronionego katalogu platformy.
To jawny wyjątek od zakazu zapisu na całym `/workspace`, a nie pozwolenie na zapis do
katalogów badaczy. Ścieżka, właściciel, limity, backup i zachowanie przy braku montowania
pozostają decyzją storage. Nie używać kolejki eksportu jako kolejki wdrożeń.

Manifest powinien wersjonować schemat oraz obejmować: identyfikator i digest artefaktu,
rozmiar pobrania i rozpakowania, architekturę, kompatybilne obrazy/ABI, pliki i ich sumy,
zależności, SBOM, wynik skanowania, dozwolony zakres, wymagane restarty i ważność podpisu.
Przed implementacją potrzebny jest ścisły schemat typów i wartości oraz zasady rotacji,
unieważniania kluczy, ochrony przed replay i nieautoryzowanym downgrade.

Cykl: pobranie do staging → weryfikacja → kwalifikacja L/D → trwały zapis decyzji →
aktywacja albo oczekiwanie. Każda operacja ma identyfikator i stany umożliwiające
idempotentne wznowienie. Atomowe przemianowanie nie zastępuje synchronizacji danych,
dziennika i uzgodnienia stanu po utracie zasilania. Błąd pozostawia poprzednią wersję aktywną.

Budżety CPU, RAM, I/O, sieci i miejsca obejmują także rozpakowywanie, stare wersje
oraz staging. Nie usuwać wersji nadal używanej. Do audytu trafiają identyfikatory,
wersje, digest, powód decyzji i wynik; nie listy procesów, argumenty ani dane badacza.
Zasady awarii audytu i retencji uzgodnić z IMG-007; nie utożsamiać sukcesu loggera
z potwierdzeniem odbioru przez SIEM.

## Tor D, rollback i RB-05

Boot jest bezpiecznym punktem dopiero po zapewnieniu zależności systemd, montowań
oraz blokady huba i innych wykonawców. Zgoda jednego badacza nie zastępuje zgody
na przerwanie pracy pozostałych. Kafel powinien wskazywać planowane okno i wymagany
restart, bez obietnicy instalacji przy następnym logowaniu.

Po wymianie obrazu ponownie sprawdzić podpis, zgodność i sens każdego oczekującego
artefaktu: może być już zawarty w obrazie albo z nim niezgodny. „Drenowanie” nie może
oznaczać bezwarunkowego wykonania kolejki. Aktualizację RB-05 dostarczyć razem z kodem.

Dla L rozważyć powrót wskaźnika dla nowych startów z zachowaniem istniejących sesji.
Nie deklarować cofnięcia skutków działania aplikacji w danych. Dla systemu pozostaje
RB-05. Awaryjna łata krytycznej CVE może wymagać przerwania pracy — priorytet i tryb
komunikacji muszą być zatwierdzone, nie ukryte pod gwarancją „bez wpływu”.

## Decyzje Właściciela Platformy

1. Zatwierdzenie wąskiego L i procedury pilnej CVE, wraz z czasem reakcji.
2. Zgoda, wymuszone okno, blokada nowych startów i obsługa zadań poza Hubem.
3. Kurator, osobny zakres klucza, atestacje i kompatybilność wydań (#12/#71).
4. Storage stanu, kwoty, retencja i odtwarzanie po wymianie obrazu (#19).
5. Obsługa GUI/noVNC, rollback i kryteria usuwania nieużywanych wersji.

## Weryfikowalne kryteria przed wdrożeniem

- ADR zatwierdza powyższe decyzje; kontrakty i model zagrożeń podlegają przeglądowi (#26).
- Test L utrzymuje kernel i wyniki obliczeń; późny import, odczyt zasobów i podproces
  nadal korzystają ze starej wersji, a nowa sesja otrzymuje nową.
- Wyścig startu sesji z aktywacją D nie omija blokady; zadanie w tle blokuje wykonanie.
- Niepoprawny podpis, replay, niezgodny obraz, traversal i linki są odrzucane.
- ENOSPC, częściowe pobranie, awaria audytu, restart oraz przerwanie każdego etapu
  nie aktywują częściowej wersji; ponowienie nie powiela skutków.
- Izolacja odrzuca próbę zapisu do danych badacza. Hashowanie kontrolnego drzewa
  uzupełnia test; porównanie aktywnie zmienianych danych badacza nie jest miarodajne.
- Testy na VM obejmują budżety zasobów, stan montowań, GUI oraz wymianę obrazu.
- Kontrakt obserwowalności, runbook awarii i rollbacku są dostarczone z implementacją.

## Alternatywy i zależności

RB-05 dla wszystkich zmian pozostaje prostszy, lecz przerywa sesje. Mirror IMG-004
obsługuje instalacje badacza, ale nie aktualizuje systemu. Oddzielna warstwa #96
jest zależnością projektową. Push SSH wymaga osobnej oceny zgodności z IMG-003;
propozycja preferuje pull, nie uznając go za automatycznie bezpieczny.

Powiązania: #96, #16, #19, #23, #12, #71, #3, #11, #97, #149, #153,
#30, #20, #147, #26, #27 oraz IMG-003, IMG-004, IMG-007.

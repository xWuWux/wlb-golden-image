# Kontrakt testów sieci i utwardzenia (#63, #16)

## Co jest bramką

- Etap 4: regresje harnessu (pytest/BATS), bez VM i bez zmiany sysctl hosta.
- Etap 5 przed scaleniem: zmiany ról `base`, `lab_config`, `tljh`, `cloud-init/`,
  testów akceptacji, biblioteki testowej, proxy testowego i bramek CI uruchamiają KVM.
  Dla pozostałych zmian nadal obowiązuje opt-in `run-integration` (#86).
  Dotyczy również `merge_group`; brak/błędna baza diff wymusza integrację.
- Uruchomienie proxy w etapie 5 jest obowiązkowe. Jego awaria kończy etap błędem,
  sprząta uruchomione odbiorniki i nie uruchamia VM. Ręczna akceptacja bez fixture
  nadal może zwrócić SKIP; nie jest wtedy pełnym dowodem odbioru #16.
- Akceptacja #63 sprawdza wszystkie 30 wartości przypiętych w `60-wlb.conf`
  (w tym `all` i `default`), nie tylko dziewięć wybranych wartości.
  Wartości oczekiwane są zapisane niezależnie od pliku konfiguracyjnego.
  Błąd odczytu sysctl oznacza FAIL nawet przy poprawnym stdout.
- HTTP 200/403 i jawna odmowa HTTPS CONNECT (403) są testami **atrapy** proxy.
  Odmowa CONNECT wymaga kodu curl 56 i `http_connect=403`: brak sieci, timeout,
  błąd certyfikatu albo 502 nie zaliczają tego testu. `--noproxy ''` wymusza
  przejście przez fixture niezależnie od środowiska testera.

To nie jest dowód zgodności z całym CIS ani dowód izolacji produkcyjnej sieci.
Sprawdzenie tekstu plików coredump nie zastępuje próby z procesu notebooka.
Testy bezpośredniego egress w istniejącym rdzeniu nadal opierają się na błędzie
curl do internetu: same nie rozróżniają działania zapory od awarii internetu.

## Kontrakty kodu

Nie wprowadzamy nowych zmiennych konfiguracji obrazu ani zmiany polityki routingu.

| Element | Argumenty / wynik | Użycie |
|---|---|---|
| `network_change BASE` | SHA/ref jako napis; 0 = wymagaj integracji, 1 = brak pasującej zmiany | `ci/changes.sh`, PR i merge queue; błąd git daje 0 |
| `BASE` (istniejąca) | dla PR `pull_request.base.sha`, merge queue `merge_group.base_sha`, push `before` | workflow → klasyfikacja → `image` → `ci/ready.sh` |
| `check_sysctl KEY EXPECTED` | dwa napisy; 0 = poprawny odczyt i dokładna zgodność | wyłącznie fragment akceptacji #63 |
| `proxy_denies_connect URL` | HTTPS URL; 0 = curl 56 oraz CONNECT 403 | wyłącznie akceptacja z flagą `--proxy-allowlist`; korzysta z istniejących `R1` i `P` |
| `WLB_TEST_PROXY` (istniejąca) | etap 5 przekazuje `1` po starcie fixture | `tests/acceptance.sh` → `--proxy-allowlist`; usunięto stan pusty po awarii fixture |
| `key`, `expected`, `target` | lokalne dla przebiegu skryptu napisy | iteracja po kontrakcie sysctl / URL testowych; nie są interfejsem obrazu |

Rozszerzenie bramki zwiększa koszt CI dla powyższych ścieżek. To świadomy koszt:
sprawdzenie sysctl na jądrze runnera lub w kontenerze nie testuje gotowego obrazu.
Nie kopiujemy stosu Postgres/Kafka ani blokady GPL z innego projektu.

## Wymagane dalsze dowody przed odbiorem produkcyjnym

| Obszar | Test pozytywny | Test negatywny / degradacja | Gdzie |
|---|---|---|---|
| Routing IPv4 | badacz → proxy, baza, hub; duży transfer | spoofing; wariant asymetryczny z jawną decyzją o obsłudze | izolowana topologia VM + OpenStack |
| IPv6 | zadeklarowany sposób adresacji i trasa; ND/PMTU | bezpośredni TCP/UDP IPv6 nie omija egress; rogue RA | VM z rzeczywistym IPv6, nie sam QEMU user networking |
| Proxy/TLS | rzeczywisty Squid + lokalny origin TLS, zaufane CA, pobranie i hash pakietu | domena/IP/port poza allowlistą; błędne CA/nazwa; przekierowanie poza allowlistę | hermetyczna integracja i smoke na platformie |
| Awaria proxy | odzyskanie pobierania po restarcie | connection refused i blackhole z limitem czasu, brak fallbacku bezpośredniego | VM + kontrolowany fixture |
| Zapora UID | ten sam lokalny cel osiągalny jako kontrolny klient | badacz z wyczyszczonym proxy nie dociera; IPv4 i IPv6, TCP i UDP | VM; pozytywna kontrola osiągalności przed odmową |
| DNS | wewnętrzna nazwa działa | zewnętrzna nazwa nie jest rekursywnie przekazywana wbrew polityce | resolver Laboratorium; sam filtr UID nie wystarcza |
| Core dump | notebook i kernel startują i pracują | kontrolowany crash procesu potomnego, brak zapisanego core; limit w rzeczywistej jednostce | VM po boot i reboot |
| SIEM | dostarczenie logów oraz opróżnienie kolejki po powrocie odbiornika | bounded burst + niedostępny SIEM; zmierzone zajęcie dysku, utrata i czas drain | VM, oddzielny scenariusz #32 |

Każdy test musi zapisać SHA kodu, identyfikator/hash obrazu, wynik i log diagnostyczny.
Brak wymaganego fixture albo możliwości wykonania scenariusza blokuje odbiór;
nie wolno zastępować go zielonym SKIP. Powtórzyć wymagane testy po restarcie VM.
Nie skanować publicznych API: używać lokalnych originów i zarezerwowanych nazw/adresów.

## Korekty specyfikacji

1. „Bez wpływu na pracę badaczy (VM ... nie jest routerem)” nie wynika z przesłanki.
   `rp_filter=1` może odrzucić prawidłowy ruch asymetryczny; `accept_ra=0` wyłącza
   uczenie konfiguracji z RA. Zapis zastępczy: „Profil wymaga symetrycznego routingu
   IPv4 i adresacji IPv6 niewymagającej RA; zgodność potwierdza test topologii Laboratorium”.
2. „Test akceptacyjny na sysctl -a” opisuje narzędzie, nie wynik.
   Zapis zastępczy: „Każdy wymagany klucz ma oczekiwaną wartość po boot/reboot;
   kontrolujemy też efektywną konfigurację interfejsów i działanie ścieżek aplikacji”.
   Obecny PR rozszerza odczyty; testy interfejsów/reboot pozostają do wykonania.
3. „Wpływ ... pomijalny”, „nie zaleje kolejki” w komentarzu #63 to twierdzenia bez pomiaru.
   Rate limit ogranicza dopływ, ale nie czas awarii odbiornika ani inne źródła logów.
   Zapis zastępczy: „Pozostawić log_martians=1; odbiór #32 wymaga pomiaru przy
   określonym burst, czasie niedostępności i limicie dysku oraz sprawdzenia recovery”.
4. „Test ... na prawdziwym proxy” w #16 nie opisuje `proxy_sink.py`, który nie forwarduje.
   Zapis zastępczy: „Atrapa potwierdza kontrakt klienta HTTP i odmowy CONNECT;
   oddzielny test produkcyjnego proxy weryfikuje TLS, mirrory i politykę platformy”.
5. „26 reguł ... zielone w raporcie” wymaga identyfikacji wersji benchmarku, profilu,
   narzędzia i listy reguł. Raport Lynis jest obecnie informacyjny, nie bramką CIS.
   Zapis zastępczy: „Zarchiwizować raport wskazanego skanera/profilu z wynikami
   wymaganych reguł i zatwierdzonymi wyjątkami; niezależnie zaliczyć testy funkcjonalne”.
6. Komentarz „Domknie się przez ... #99” jest nieaktualny: #99 zamknięto bez scalenia.
   Zapis zastępczy: „Odbiór odnosi się do konkretnego SHA main i wyników jego CI,
   nie do historycznej liczby PASS z innej gałęzi”.

Źródło semantyki parametrów: https://www.kernel.org/doc/html/latest/networking/ip-sysctl.html
Przed zmianą wartości należy sprawdzić dokumentację docelowego jądra obrazu.

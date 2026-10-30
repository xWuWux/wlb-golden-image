# Wazuh: strumień WLB (#17)

Dekodery `wlb_decoders.xml` i reguły `wlb_rules.xml` obsługują strumień RFC 5424
z szablonu rsyslog WLB oraz zdarzenia opisane w `observability/contract.yml`.
Zakres identyfikatorów reguł: 100100–100199; przed instalacją sprawdź kolizje
z lokalnymi regułami menedżera. Rozwiązanie wymaga weryfikacji w docelowej
instancji — test w kontenerze nie jest wdrożeniem ani akceptacją produkcyjną.

## Instalacja i weryfikacja

Administrator menedżera kopiuje odpowiednio dekodery do
`/var/ossec/etc/decoders/wlb_decoders.xml`, a reguły do
`/var/ossec/etc/rules/wlb_rules.xml`, zachowując właściwe prawa dostępu i
istniejące konfiguracje. Po wykonaniu kopii zapasowej sprawdza konfigurację
`/var/ossec/bin/wazuh-analysisd -t` i zgodnie z procedurą środowiska przeładowuje
menedżer. Nie nadpisuj cudzych reguł ani nie restartuj produkcji bez uzgodnienia.
Upewnij się, że właściwe źródło kieruje oryginalne wiersze RFC 5424 do analysisd;
same pliki XML nie konfigurują odbioru, autoryzacji transportu ani retencji.
Sprawdź w rzeczywistym pipeline dekodowanie, poziomy alertów, korelacje i
widoczność zdarzeń na panelu; nie zakładaj, że logtest dowodzi ich dostarczenia.

Lokalnie uruchom `ci/observability.sh` (Docker) albo bezpośrednio
`ci/wazuh-logtest.sh tests/fixtures/siem-sample.log --require-all
--expect-untrusted sluza_out.export_request --expect-untrusted hub.login
--expect-untrusted shell.command`. Test używa przypiętego obrazu Wazuh 4.14.9;
można jawnie podać `WAZUH_IMAGE`, lecz zgodność z inną wersją należy osobno
sprawdzić. Etap 5 dodatkowo testuje log odebrany z testowej VM. Wyniki JSONL w
`build/wazuh/` zawierają oryginalne wiersze — traktuj je jak logi wrażliwe,
nie publikuj danych produkcyjnych ani nie używaj ich jako publicznych fixture.
Próbka obejmuje zarówno odkażone dane testowe, jak i zdarzenia syntetyczne.

## Granice zaufania i interpretacja

`wlb.sender_uid`, `wlb.sender_gid`, `wlb.sender_pid` i `wlb.input` pochodzą
z metadanych rsyslog po lokalnym odbiorze. UID 0 i `imuxsock` nie dowodzą,
że komunikat pochodzi z konkretnej jednostki systemd: inny proces root może
nadać taki sam tag i treść. Badacz też może podać własną treść i tag; reguły
podszycia wykrywają wybrane niezgodności, nie wszystkie fałszerstwa. Zaufanie
do metadanych wymaga ochrony hosta, konfiguracji i uwierzytelnionego,
chronionego transportu do SIEM. Nie traktuj ich jako dowodu w razie kompromitacji
roota lub transportu. `wlb-shell` jest śladem dostarczanym przez powłokę, nie
pełnym ani odpornym na manipulacje audytem wykonania poleceń.

Poziomy 0–3 są śladem, 5 wymaga przeglądu, 7–8 wskazuje nietypowe zdarzenie,
a 10+ kandydata do reakcji; progi i odbiorców trzeba uzgodnić z operatorem.
Godziny reguł eksportu liczone są w strefie menedżera, a wartości częstotliwości
są progami początkowymi do walidacji. Ustawienia Wazuh mogą nie zapisywać
alertów niskiego poziomu: jeśli wymagany jest pełny ślad, skonfiguruj i sprawdź
archiwizację oryginalnych zdarzeń niezależnie od alertów, z kontrolą dostępu.
`POST /hub/api/users/.../activity` ma obniżony poziom 2, ale nie jest usuwany
ze strumienia; nie należy mylić braku alertu z brakiem zdarzenia.

Audyt `SYSCALL` i związane z nim `PATH`, `PROCTITLE` oraz inne rekordy są
osobnymi wierszami; korelacja wymaga identyfikatora `wlb.audit_id`, a pliki
reguł nie sklejają ich automatycznie. Pola auditd ze spacjami mogą pozostać
w postaci szesnastkowej. `auid=4294967295` oznacza brak ustawionego audit login
UID, a nie dowód, że operację wykonała usługa; reguły traktują ten przypadek
jako niższy priorytet i wymagają strojenia. Zdarzenia logout, server_start i cull
nie są obecnie zapewnione przez kontrakt. Przy pierwszym spawnie rzeczywisty
`session_start` może zawierać puste `uid`, niezgodne z obecnym kontraktem;
syntetyczny poprawny wpis w teście nie usuwa tej luki.

## Retencja

Okresy i politykę archiwizacji, ochrony, dostępu, usuwania i ewentualnej
anonimizacji musi zatwierdzić właściciel polityki IP_CMC. Dokument §21 nie
podaje liczby dni; te pliki nie ustawiają okresu retencji i nie należy go
wywodzić z progów Wazuh. Przed produkcją uzgodnij także pojemność, odtwarzanie,
odpowiedzialność za alerty oraz test działania całego łańcucha.

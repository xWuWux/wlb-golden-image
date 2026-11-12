# IMG-010: Monitoring metryk VM — model zbierania i ekspozycja eksportera

* **Status:** Proponowana (do zatwierdzenia przez Właściciela Platformy; wdrożenie wyłącznie testowe)
* **Data:** 2026-11-05 (rewizja 2026-11-10 po przeglądzie #234)
* **Autorzy / decyduje:** Właściciel Platformy (obraz) + administratorzy infrastruktury GUMed
* **Powiązania:** OPZ: CH.8 (integracja z Zabbix/Wazuh), CH.14 (metryki zdrowia komponentów), F-OBS-009 · Regulamin: §21 (monitorowanie), §20 (dane medyczne) · IP_CMC: ADR 1.6 Observability · Zgłoszenia/PR: #22, #234, #32, #27, #17, #14 · Pliki: `ansible/roles/monitoring/`, `observability/contract.yml`, `ci/metrics_check.py`, `ansible/roles/lab_config/files/wlb-firstboot`, `docs/runbooks/RB-monitoring.md`

## Kontekst i problem

Wybór systemu monitoringu jest decyzją platformową, nie obrazową. Obraz ma już jednak **format
Prometheus**: `prometheus-node-exporter` (metryki systemowe) i timer `wlb-health` (metryki stanu
mechanizmów WLB w textfile collectorze), z kontraktem w `observability/contract.yml` i bramką CI na
odpowiedzi eksportera. Eksporter słucha wyłącznie na `127.0.0.1:9100`, więc kryterium #22 „metryki
widoczne w systemie monitoringu" nie jest spełnione.

Do rozstrzygnięcia: czy i jak obrazy Laboratoriów mają oddawać metryki do istniejącego stacku oraz czy
przyjęty format stanowi odstępstwo od specyfikacji.

## Stan zastany (fakty wejściowe, nie wynik tej decyzji)

Na podstawie repozytorium infrastruktury i odbioru z **2026-10-14** — **nie** jest to test dostępności
ani łączności z VM Laboratorium:

* działa centralny stack **Prometheus 3.15 + Grafana + Loki** na VM `ipcmc-cortex-monitoring-01`
  (`172.16.25.58`); etap podstawowy, bez deklaracji gotowości produkcyjnej/SLA,
* model **pull co 30 s**, scrape `node_exporter` po **HTTP bez TLS i bez auth**; na hostach
  infrastruktury zapora dopuszcza pojedynczy adres kolektora,
* brak Alertmanagera, powiadomień i ustalonego odbiorcy alertów; progi na dashboardach są orientacyjne,
* generator celów nadaje etykiety `host` i `env`, **bez `lab`**,
* routing między siecią Laboratoriów a `172.16.25.58` — **nieznany**; adres źródłowy po NAT —
  **niezweryfikowany**,
* Zabbix w GUMed — wzmianka w IC20-298, stan niepotwierdzony; OPZ CH.8 wskazuje go jako system istniejący.

## Rozważane opcje

1. **A — agent Zabbix 2 (push).** Zgodne z CH.8, bez portu na wejściu VM. Koszt: nowa usługa
   w obrazie, PKI/PSK, drugi system, jeśli standardem jest Prometheus; metryki WLB jako `UserParameter`.
2. **B — Prometheus pull (istniejący stack).** Wykorzystuje to, co działa; metryki systemowe i `wlb_*`
   na jednym `:9100`. Koszt: otwarty port i scrape bez uwierzytelnienia — cała kontrola to adres źródłowy.
3. **C — push/remote-write.** Bez portu na wejściu, ale dodatkowy komponent i jego zaufanie.
4. **D — metryki jako zdarzenia w SIEM.** Istniejący kanał, ale zawodzi dokładnie przy awarii SIEM
   i nie daje historii.

## Decyzja (proponowana)

**Wariant B wyłącznie dla wdrożeń testowych**, z warunkami:

1. Domyślnie brak ekspozycji (`127.0.0.1:9100`). Ekspozycję włącza jawnie `MONITORING_CIDR` w `lab.env`
   albo `wlb-monitoring apply` — dla **jednego kanonicznego adresu IPv4 `/32`**; sieci, listy, zera
   wiodące i `0.0.0.0` są odrzucane przed zmianą zapory.
2. **Warunek wstępny:** adres `/32` musi należeć wyłącznie do monitoringu. Wspólny adres NAT innych
   klientów oznacza, że `/32` nie identyfikuje Prometheusa — wtedy ekspozycji nie włączamy.
3. Zmiana na działającej VM nie przechodzi przez `wlb-firstboot --force` (który zamyka port huba
   na czas przebiegu): `wlb-monitoring` dotyka tylko reguły portu 9100 (osobny łańcuch, `nft -f`, bez
   restartu zapory) i eksportera. Przy pierwszym starcie firstboot stosuje ekspozycję na końcu, po
   otwarciu huba, a jej błąd jest niekrytyczny.
4. Nasłuch poza pętlą zależy od zapory: `After=`/`PartOf=nftables.service` i `ExecStartPre` (guard)
   sprawdzający aktywną regułę w jądrze; `apply`/`disable` kończą się sukcesem dopiero po weryfikacji
   reguły i faktycznego gniazda, a błąd cofa do stanu bezpiecznego.
5. Kontrakt metryk pozostaje w `observability/contract.yml`; etap 5 CI sprawdza pełną odpowiedź
   eksportera pod kątem identyfikatorów badaczy oraz — prawdziwą próbą sieciową — dostęp z dozwolonego
   i odrzucenie innego źródła.
6. Przed produkcją: potwierdzenie standardu GUMed (Zabbix vs Prometheus). Jeśli Zabbix — wariant A,
   a ten ADR zostaje zastąpiony.

## Odstępstwo od specyfikacji

* **Czy stanowi odstępstwo:** Tak (warunkowo, do potwierdzenia standardu platformy)
* **Uzasadnienie / cytat:** OPZ CH.8: „platforma chmurowa powinna umożliwiać integrację z zewnętrznym
  systemem zabbix oraz wazuh". Obraz używa formatu **Prometheus**, a nie agenta Zabbix, bo ten format
  jest już w obrazie i w stacku platformy. Po potwierdzeniu stanu Zabbixa odstępstwo wymaga świadomej
  akceptacji albo migracji do wariantu A. Wpis do rejestru odstępstw: #22.

## Konsekwencje

* **Pozytywne (oczekiwane po onboardingu):** metryki systemowe i stanu WLB dostępne w istniejącym
  stacku bez nowych usług w obrazie; domyślnie obraz zachowuje się jak dotąd.
* **Negatywne / dług techniczny:** scrape bez TLS i auth; endpoint ujawnia metadane systemu (nazwa
  hosta, jądro, interfejsy, punkty montowania) każdemu, kto mieści się w regule — kontrola CI wyklucza
  tylko identyfikatory badaczy; ręczne `nft flush ruleset` poza systemd zostawia nasłuch bez filtra do
  restartu eksportera; brak alertingu; brak etykiety `lab`.
* **Świadomie pominięte:** agent Zabbix, `/hub/metrics` JupyterHuba, push/remote-write, TLS i basic
  auth na eksporterze, SLI/SLO i progi alertów.

## Wynik odbioru (do uzupełnienia — dziś niepotwierdzony)

Widoczność metryk w monitoringu uznajemy za potwierdzoną **dopiero** po: udanym scrape'ie po stronie
Prometheusa z VM testowej, z etykietą pozwalającą rozpoznać Laboratorium; potwierdzeniu, że inny adres
nie łączy się z `:9100`; powtórzeniu po restarcie VM i po `wlb-monitoring disable`; przeglądzie pełnej
odpowiedzi `/metrics` z reprezentatywnej VM. Do tego czasu ten ADR opisuje mechanizm, nie osiągnięty
efekt. Procedura: `docs/runbooks/RB-monitoring.md`.

## Punkty otwarte (warunki zamknięcia #22)

1. Standard monitoringu GUMed (Zabbix vs Prometheus) — decyzja platformowa.
2. Routing do `172.16.25.58`, obserwowany adres źródłowy i potwierdzenie, że należy wyłącznie do
   monitoringu.
3. Właściciel alertów i progi (dysk, spool SIEM, wiek próbki `wlb-health`) — #32, #27.
4. Etykieta `lab` w generatorze celów po stronie infrastruktury.
5. `/hub/metrics` z tokenem `read:metrics` — osobne zgłoszenie.
6. Wynik odbioru (sekcja wyżej).

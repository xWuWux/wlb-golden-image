# IMG-010: Monitoring metryk VM — model zbierania i ekspozycja eksportera

* **Status:** Proponowana (do zatwierdzenia przez Właściciela Platformy; wdrożenie wyłącznie testowe)
* **Data:** 2026-11-05
* **Autorzy / decyduje:** Właściciel Platformy (obraz) + administratorzy infrastruktury GUMed
* **Powiązania:** OPZ: CH.8 (integracja z Zabbix/Wazuh), CH.14 (metryki zdrowia komponentów), F-OBS-009 · Regulamin: §21 (monitorowanie), §9.5 (sesje), §20 (dane medyczne) · IP_CMC: ADR 1.6 Observability · Zgłoszenia/PR: #22, #32, #27, #17, #14 · Pliki: `ansible/roles/monitoring/`, `observability/contract.yml`, `ci/metrics_check.py`, `ansible/roles/lab_config/files/wlb-firstboot`, `docs/runbooks/RB-monitoring.md`

## Kontekst i problem

Obraz przez długi czas nie wystawiał żadnych metryk, bo wybór systemu monitoringu jest decyzją
platformową, a nie obrazową. Dziś w obrazie jest już **format Prometheus**: `prometheus-node-exporter`
(metryki systemowe) plus timer `wlb-health` (metryki stanu mechanizmów WLB w textfile collectorze),
z kontraktem w `observability/contract.yml` i bramką CI na odpowiedzi eksportera. Eksporter słucha
jednak **wyłącznie na `127.0.0.1:9100`** — metryki nie wychodzą z VM, więc kryterium „widoczne
w systemie monitoringu" z #22 nie jest spełnione.

Stan infrastruktury (odbiór z 2026-10-14, nie bieżący test dostępności): działa centralny stack
**Prometheus 3.15 + Grafana + Loki** na VM `ipcmc-cortex-monitoring-01` (`172.16.25.58`), model
**pull co 30 s**, zapora po stronie monitoringu dopuszcza **pojedynczy adres**, scrape jest po
**HTTP bez TLS i bez auth**. Brak Alertmanagera i powiadomień. Obecności Zabbixa w GUMed nie
potwierdzono (wzmianka w IC20-298); OPZ CH.8 wskazuje go jako system istniejący.

Problem do rozstrzygnięcia: **czy i jak obrazy Laboratoriów mają oddawać metryki do tego stacku**,
oraz czy przyjęty format jest zgodny ze specyfikacją, czy stanowi odstępstwo.

## Rozważane opcje

1. **A — agent Zabbix 2 (push).** Zgodne z CH.8, nie otwiera portu na VM, jedno narzędzie, jeśli
   GUMed ma Zabbix. Koszt: nowa usługa w obrazie, PKI/PSK, drugi system do utrzymania, jeśli
   standardem okaże się Prometheus; metryki WLB wymagają własnych `UserParameter`.
2. **B — Prometheus pull (istniejący stack).** Wykorzystuje to, co już działa; metryki systemowe
   i `wlb_*` na jednym `:9100`; brak nowych usług w obrazie. Koszt: nowy otwarty port (ograniczony
   do `/32`), scrape po HTTP bez uwierzytelnienia, zależność od routingu między sieciami.
3. **C — push/remote-write do Prometheusa.** Brak portu na wejściu, ale wymaga dodatkowego
   komponentu (agent/collector) i zaufania do niego; więcej ruchu i konfiguracji niż pull.
4. **D — metryki jako zdarzenia w SIEM.** Istniejący kanał, ale nie działa dokładnie wtedy, gdy
   potrzebny (awaria SIEM = brak metryk), i nie daje historii/wykresów.

## Decyzja

**Wariant B dla wdrożeń testowych**, z następującymi warunkami:

1. Obraz wystawia metryki **tylko po jawnym ustawieniu `MONITORING_CIDR`** w `lab.env` (puste =
   zachowanie dotychczasowe: `127.0.0.1:9100`). Wartość to **pojedyncza sieć** (zwykle `/32`
   serwera monitoringu), walidowana przed zmianą zapory; `/0`, listy i IPv6 są odrzucane.
2. Port `9100` dopuszcza wyłącznie reguła `ip saddr ${MONITORING_CIDR} tcp dport 9100 accept`
   w łańcuchu `input` o polityce `drop`; bindowanie eksportera następuje **po** załadowaniu zapory.
3. Kontrakt metryk pozostaje w `observability/contract.yml` (format Prometheus), a zgodność odpowiedzi
   eksportera jest sprawdzana w etapie 5 CI — metryki są weryfikowane tym samym mechanizmem co logi.
4. Metryki nie zawierają danych badaczy ani nazw plików (kontrakt `wlb_*`).
5. **Zastrzeżenie:** decyzja obowiązuje dla środowiska testowego. Przed produkcją wymagane jest
   potwierdzenie standardu GUMed (Zabbix vs Prometheus) i rozstrzygnięcie punktów otwartych niżej.
   Jeśli standardem jest Zabbix — wracamy do wariantu A i ten ADR zostaje zastąpiony.

## Odstępstwo od specyfikacji

* **Czy stanowi odstępstwo:** Tak (warunkowo, do potwierdzenia standardu platformy)
* **Uzasadnienie / cytat:** OPZ CH.8: „platforma chmurowa powinna umożliwiać integrację z zewnętrznym
  systemem zabbix oraz wazuh". Obraz używa formatu **Prometheus** (`node_exporter` + textfile),
  a nie agenta Zabbix. Powód: format ten jest już w obrazie i w działającym stacku monitoringu
  platformy, a wdrożenie agenta Zabbix wymaga nowej usługi i PKI. Stan Zabbixa w GUMed jest
  niepotwierdzony — po potwierdzeniu odstępstwo wymaga świadomej akceptacji albo migracji do
  wariantu A. Wpis do rejestru odstępstw: #22.

## Konsekwencje

* **Pozytywne:** metryki VM i stanu mechanizmów WLB (kolejka eksportu, spool SIEM, wolne miejsce,
  `auditd`, `chrony`) są widoczne w istniejącym stacku bez nowych usług w obrazie; jedno źródło
  (`:9100`) dla metryk systemowych i WLB; domyślnie obraz zachowuje się jak dotąd (brak ekspozycji).
* **Negatywne / dług techniczny:** scrape po HTTP bez TLS i auth — kontrola wyłącznie siecią,
  więc `MONITORING_CIDR` musi być wąski; eksporter ujawnia wersję jądra, interfejsy i punkty
  montowania; wymagana empiryczna weryfikacja adresu źródłowego (NAT); brak alertingu po stronie
  monitoringu (dashboardy i progi orientacyjne bez odbiorcy); `env`/`host` to jedyne etykiety
  w generatorze celów — brak `lab` utrudnia rozdzielenie Laboratoriów.
* **Świadomie pominięte:** agent Zabbix (do potwierdzenia standardu), `/hub/metrics` JupyterHuba
  (aktywni badacze, czas spawnu — osobne zadanie), push/remote-write, TLS i basic auth na eksporterze,
  definicja SLI/SLO i progów alertów (zależne od ustalenia odbiorcy alertów).

## Punkty otwarte (warunki zamknięcia #22)

1. Potwierdzenie przez administratorów GUMed standardu monitoringu (Zabbix vs Prometheus) — decyzja
   platformowa, nie obrazowa.
2. Weryfikacja routingu między siecią Laboratoriów a `172.16.25.58` i ustalenie obserwowanego adresu
   źródłowego (procedura w `docs/runbooks/RB-monitoring.md`).
3. Ustalenie właściciela alertów i progów (dysk, spool SIEM, wiek próbki `wlb-health`) — powiązane
   z #32 i #27.
4. Etykieta `lab` w generatorze celów po stronie infrastruktury.
5. `/hub/metrics` z tokenem `read:metrics` — osobne zgłoszenie.

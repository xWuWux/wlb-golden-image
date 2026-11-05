# RB: metryki VM dla centralnego monitoringu (#22)

**Odniesienia:** #22 (metryki VM), `observability/contract.yml` (sekcja `metrics`), rola `monitoring`
(`prometheus-node-exporter` + `wlb-health`), `wlb-firstboot` (opcja `MONITORING_CIDR`),
[RB-wlb-health](RB-wlb-health.md). **Zakres:** `wlb-golden-image`.

Domyślnie obraz **nie wystawia metryk na sieć**: `prometheus-node-exporter` słucha wyłącznie na
`127.0.0.1:9100`, a zapora przepuszcza na wejściu tylko SSH, hub i DHCP. `MONITORING_CIDR` zdejmuje
to ograniczenie dla **jednego** źródła scrape'a — bez niego nic się nie zmienia.

Uzgodniony stos monitoringu (stan infrastruktury, nie bieżący test dostępności): Prometheus 3.15 +
Grafana + Loki na VM `ipcmc-cortex-monitoring-01` (`172.16.25.58`), **pull co 30 s**, zapora po ich
stronie dopuszcza pojedynczy adres, scrape jest po **HTTP bez TLS i bez auth** — kontrola wyłącznie
siecią. Dlatego `MONITORING_CIDR` ma być **wąskie** (zwykle `/32`), a nie cały LAN.

## Co obraz udostępnia na `:9100`

- metryki systemowe `node_*` (CPU, RAM, dyski, sieć, wersja jądra),
- własne metryki WLB `wlb_*` z timera `wlb-health` (kolejka eksportu, spool SIEM, wolne miejsce,
  `auditd`, `chrony`) — szczegóły i ograniczenia: [RB-wlb-health](RB-wlb-health.md).

Metryki **nie zawierają** danych badaczy ani nazw plików; kontrakt i selektory są w
`observability/contract.yml`, a odpowiedź eksportera jest sprawdzana w etapie 5 CI
(`ci/metrics_check.py`). Wystawienie portu nie wymaga osobnej konfiguracji scrape po stronie
monitoringu: metryki WLB są na tym samym `:9100` co systemowe.

## A. Włączenie — `MONITORING_CIDR` w `lab.env`

W `/etc/wlb/lab.env` (cloud-init `write_files`) ustaw **obserwowany** adres źródłowy scrape'a:

```sh
MONITORING_CIDR=172.16.25.58/32
```

Zasady:

- puste = brak ekspozycji (zachowanie domyślne obrazu),
- pojedyncza kanoniczna sieć IPv4 `A.B.C.D/prefiks`, prefiks 1–32; listy, spacje, IPv6 i `/0` są
  odrzucane **przed** zmianą zapory (fail-secure),
- wartość jest walidowana tak jak `ADMIN_SSH_CIDR`/`HUB_ALLOWED_CIDR`,
- zmiana wymaga ponownego uruchomienia: `sudo wlb-firstboot --force` (nowa VM — wystarczy cloud-init).

Po ustawieniu `wlb-firstboot`:

1. dopisuje regułę zapory `ip saddr ${MONITORING_CIDR} tcp dport 9100 accept` (polityka wejścia
   pozostaje `drop`),
2. tworzy drop-in `20-wlb-monitoring.conf` nadpisujący `ExecStart` eksportera na
   `--web.listen-address=0.0.0.0:9100` (flagi `textfile` zostają z obrazu),
3. przeładowuje jednostki i restartuje eksporter.

Bindowanie następuje **po** załadowaniu zapory — odwrotna kolejność wystawiłaby metryki na sieć,
zanim reguły zdążą zadziałać.

## B. Weryfikacja adresu źródłowego (NAT!) — zrób to przed pierwszym scrape'em

Adres widziany przez VM nie musi być adresem serwera Prometheus: jeśli Laboratorium jest w innej
sieci albo za NAT-em, źródło może być podmienione. Sprawdź to empirycznie, zamiast zakładać:

1. Wdróż VM z `MONITORING_CIDR` ustawionym na adres **przypuszczany** (albo bez niego).
2. Z serwera monitoringu spróbuj odpytać VM: `curl -sS http://<adres-vm>:9100/metrics | head`.
3. Na VM podejrzyj odrzucone pakiety (reguła `wlb-in-deny` loguje źródło):

```sh
sudo journalctl -k --since "10 min ago" | grep 'wlb-in-deny'
```

W polu `SRC=` jest **rzeczywisty** adres, z którego przyszedł scrape. Ustaw `MONITORING_CIDR`
dokładnie na niego (`/32`) i uruchom `sudo wlb-firstboot --force`.

Jeśli scrape w ogóle nie dociera (brak wpisu `wlb-in-deny`, brak połączenia) — to problem routingu,
nie zapory: zgłoś do administratorów platformy i **nie** poszerzaj CIDR „na próbę”. Przy sieci
niezaufanej CIDR bez szyfrowania nie jest wystarczającą kontrolą; alternatywą jest tunel/VPN albo
push (np. remote-write) zamiast pull.

## C. Weryfikacja po wdrożeniu (na VM)

```sh
# reguła zapory i brak 0.0.0.0/0
sudo nft list ruleset | grep -E 'dport 9100|0\.0\.0\.0/0'
# nasłuch i lokalna odpowiedź eksportera
ss -H -ltn 'sport = :9100'
curl --noproxy '*' -fsS http://127.0.0.1:9100/metrics | grep -c '^wlb_'
# override z firstboot
cat /etc/systemd/system/prometheus-node-exporter.service.d/20-wlb-monitoring.conf
```

Z serwera monitoringu:

```sh
curl -sS http://<adres-vm>:9100/metrics | grep -E '^(node_cpu_seconds_total|wlb_health_timestamp_seconds)'
```

## D. Co przekazać zespołowi infrastruktury (onboarding)

1. Nazwa VM i adres IP z sieci, z której monitoring ma prowadzić scrape.
2. Port `9100`, ścieżka `/metrics`, interwał 30 s (jak dla pozostałych hostów).
3. Prośba o etykietę `lab` (wartość = `LAB_NAME`). Dziś generator `targets.json.j2` nadaje tylko
   `host` i `env`; przy kilku Laboratoriach na jednym Prometheusie `env` nie rozdzieli Labów, więc
   bez tej etykiety dashboardy i alerty trzeba budować na nazwie hosta.
4. Informacja, że metryki WLB (`wlb_*`) są na tym samym endpointcie — **nie** trzeba osobnego
   `monitoring_extra_scrape_configs`.

## Rollback

```sh
sudo sed -i '/^MONITORING_CIDR=/d' /etc/wlb/lab.env
sudo wlb-firstboot --force      # usuwa drop-in 20-wlb-monitoring.conf i regułę 9100
```

Natychmiastowe cofnięcie bez `firstboot` (np. gdy trzeba zamknąć port teraz):

```sh
sudo rm -f /etc/systemd/system/prometheus-node-exporter.service.d/20-wlb-monitoring.conf
sudo systemctl daemon-reload && sudo systemctl restart prometheus-node-exporter.service
sudo nft list ruleset | grep 9100   # reguła zostaje do najbliższego przebiegu firstboot
```

## Uwagi i ograniczenia

- **Brak alertingu po stronie monitoringu.** Stack ma dashboardy i orientacyjne progi (CPU/RAM/dysk
  80/95%), ale nie ma Alertmanagera ani ustalonego odbiorcy powiadomień. Metryki będą więc
  **widoczne**, ale nikt nie dostanie alertu o zapełnionym dysku czy przepełnionej kolejce SIEM —
  to osobna praca (SLO/progi, #32, #22).
- **HTTP bez TLS i bez auth.** Każdy, kto znajdzie się w `MONITORING_CIDR`, czyta metryki bez
  uwierzytelnienia. Eksporter ujawnia wersję jądra, interfejsy i punkty montowania — nie dane
  badaczy. Utrzymuj CIDR wąski; TLS/basic auth (`--web.config.file`) wymagałby zmiany po stronie
  scrape'ującego.
- **`/hub/metrics` JupyterHuba nie jest wystawiony.** Aktywni badacze, liczba serwerów i czas spawnu
  pozostają niemierzalne poza logami w SIEM — osobne zadanie.
- **Zmiana na działającej VM nie przeżyje wymiany obrazu.** Docelowo ustaw `MONITORING_CIDR`
  w `lab.env` (cloud-init), żeby przetrwała aktualizację.
- **Retencja** metryk po stronie monitoringu: 90 dni / limit 150 GB (może skrócić historię).

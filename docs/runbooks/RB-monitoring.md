# RB: metryki VM dla centralnego monitoringu (#22)

**Odniesienia:** #22 (metryki VM), [IMG-010](../adr/IMG-010-monitoring.md) (model zbierania),
`observability/contract.yml` (sekcja `metrics`), rola `monitoring` (`prometheus-node-exporter`,
`wlb-health`, `wlb-monitoring`), `wlb-firstboot` (opcja `MONITORING_CIDR`),
[RB-wlb-health](RB-wlb-health.md). **Zakres:** `wlb-golden-image`, wdrożenia testowe.

Domyślnie obraz **nie wystawia metryk na sieć**: `prometheus-node-exporter` słucha wyłącznie na
`127.0.0.1:9100`, a zapora przepuszcza na wejściu tylko SSH, hub i DHCP. Ekspozycję dla **jednego**
adresu źródłowego włącza `MONITORING_CIDR` w `lab.env` (przy pierwszym starcie) albo
`wlb-monitoring apply` (na działającej VM).

Stan zastany infrastruktury (odbiór z 2026-10-14, **nie** test łączności z tą VM): Prometheus 3.15 +
Grafana + Loki na VM `ipcmc-cortex-monitoring-01` (`172.16.25.58`), pull co 30 s, scrape po **HTTP bez
TLS i bez auth** — kontrola wyłącznie siecią.

## Warunek wstępny: adres jednoznacznie identyfikuje monitoring

Scrape nie jest uwierzytelniony, więc reguła `ip saddr <adres>/32` jest **całą** kontrolą dostępu.
Przed włączeniem ustal z zespołem infrastruktury:

1. **Jaki adres źródłowy widzi VM** (przy NAT/SNAT to nie musi być adres Prometheusa — patrz B).
2. **Czy ten adres należy wyłącznie do monitoringu.** Jeśli to wspólny adres NAT, z którego korzystają
   też inni klienci (np. cała sieć administracyjna), `/32` nie identyfikuje Prometheusa — **nie włączaj
   ekspozycji**; potrzebny jest osobny adres, tunel/VPN albo TLS z uwierzytelnieniem.

Obraz akceptuje wyłącznie **jeden kanoniczny adres IPv4 z prefiksem `/32`** (bez zer wiodących, bez list
i sieci). Wartości typu `0.0.0.0/1`, `192.0.2.58/24` czy `010.000.000.001/32` są odrzucane przed
jakąkolwiek zmianą zapory.

## Co obraz udostępnia na `:9100`

- metryki systemowe `node_*` — w tym **metadane systemu**: wersja jądra i nazwa hosta
  (`node_uname_info`), interfejsy sieciowe, punkty montowania i typy systemów plików, urządzenia blokowe,
  statystyki CPU/pamięci/dysków/sieci,
- własne metryki WLB `wlb_*` z timera `wlb-health` (kolejka eksportu, spool SIEM, wolne miejsce,
  `auditd`, `chrony`) — [RB-wlb-health](RB-wlb-health.md).

Kolektor `systemd` jest w obrazie **wyłączony** (`--no-collector.systemd`): pakiet Debiana go włącza,
a wypisuje on stan każdej jednostki, w tym `jupyter-<login>.service` badaczy — wykryła to kontrola
poniżej na pierwszym przebiegu etapu 5.

Kontrola w CI (etap 5, `ci/metrics_check.py` na pełnej odpowiedzi eksportera z VM testowej, po testach
z kontami badaczy) odrzuca odpowiedź zawierającą: konta `jupyter-*` i `uNN`, ścieżki **wewnątrz**
udziałów (`/workspace/…`, `/sluza-out/…` itd.) i sesje logind w zakresie UID badaczy. To kontrola
regresji, **nie** dowód braku innych metadanych: zakres wyżej (nazwa hosta, jądro, montowania) jest
widoczny dla każdego, kto mieści się w regule zapory. Przed dopuszczeniem odczytu w produkcji przejrzyj
pełną odpowiedź z reprezentatywnej VM: `curl --noproxy '*' -fsS http://127.0.0.1:9100/metrics`.

Metryki WLB są na tym samym `:9100` co systemowe — po stronie monitoringu nie trzeba osobnego
`monitoring_extra_scrape_configs`.

## Jak to działa (dlaczego nie `wlb-firstboot --force`)

`wlb-firstboot --force` przy każdym przebiegu ładuje zaporę **bez** portu huba (faza 1) i otwiera go
dopiero po potwierdzeniu TLS i gotowości huba — błąd w trakcie zostawiłby badaczy bez dostępu. Dlatego
**zmiana monitoringu na działającej VM idzie wyłącznie przez `wlb-monitoring`**, które dotyka tylko
reguły portu 9100 i eksportera:

- reguła `ip saddr <adres> tcp dport 9100 accept` w osobnym łańcuchu `monitoring_in` (skok z `input`,
  polityka `drop` bez zmian), dokładana atomowo przez `nft -f` — **bez** restartu zapory,
- utrwalenie w `/etc/nftables.d/50-wlb-monitoring.nft`, włączanym przez `include` z `/etc/nftables.conf`
  (reguła przeżywa restart zapory i VM),
- drop-in `20-wlb-monitoring.conf` nadpisujący adres nasłuchu na `0.0.0.0:9100`; pozostałe flagi
  kolektorów są przepisywane z pliku obrazu,
- eksporter z ekspozycją ma `After=`/`Wants=`/`PartOf=nftables.service` oraz `ExecStartPre` (guard):
  nie wystartuje poza pętlą bez aktywnej zapory i aktywnej reguły w jądrze, a stop/restart zapory
  najpierw zatrzymuje eksporter,
- `apply` po restarcie eksportera weryfikuje regułę w jądrze i faktyczne gniazdo; przy błędzie sam
  cofa ekspozycję (stan bezpieczny: tylko pętla). Hub, proxy i śluza nie są dotykane.

Przy pierwszym starcie `wlb-firstboot` woła `wlb-monitoring apply` **na samym końcu** — po otwarciu
portu huba i założeniu kont. Błąd metryk jest wtedy niekrytyczny (wpis `BŁĄD` w logu, metryki tylko
lokalnie), żeby nie pominąć reguł audytu.

## A. Nowa VM — `MONITORING_CIDR` w `lab.env`

```sh
MONITORING_CIDR=172.16.25.58/32   # obserwowany adres źródłowy scrape'a (patrz B)
```

## B. Ustalenie obserwowanego adresu źródłowego (NAT)

Adres widziany przez VM może różnić się od adresu Prometheusa. Ustal go po obu stronach:

1. Na VM, przy wyłączonej ekspozycji, dodaj **tymczasową** regułę logowania prób połączeń z portem
   9100 (obraz nie zawiera `tcpdump`; reguła niczego nie przepuszcza, tylko loguje):

   ```sh
   sudo nft insert rule inet wlb input tcp dport 9100 ct state new log prefix '"wlb-mon-probe "' level info
   # poczekaj na próbę scrape'a (30 s)
   sudo journalctl -k --since '5 min ago' | grep wlb-mon-probe     # pole SRC= to obserwowany adres
   sudo systemctl restart nftables                                # usuwa regułę tymczasową (wczytuje /etc/nftables.conf)
   ```

   Pomocniczo zapora loguje też wszystkie odrzucenia (`wlb-in-deny`), ale ten log jest **ograniczony
   do 5 wpisów/s** — brak wpisu niczego nie przesądza.
2. Po stronie Prometheusa sprawdź stan celu (`up`, ostatni błąd scrape'a).
3. Jeśli na VM **nie widać żadnych pakietów**, przyczyna jest nierozstrzygnięta: filtr przed VM
   (security group, zapora sieciowa, routing), inny adres docelowy w konfiguracji Prometheusa albo
   brak łączności. Ustal ją z infrastrukturą; **nie** poszerzaj zakresu „na próbę".

## C. Działająca VM — włączenie i zmiana adresu (bez przerywania badań)

```sh
sudo wlb-monitoring apply 172.16.25.58/32
sudo wlb-monitoring status
```

Dla trwałości przy wymianie obrazu wpisz tę samą wartość do `MONITORING_CIDR` w `lab.env`
(cloud-init). `wlb-firstboot --force` **nie** jest potrzebne i nie powinno być używane do tej zmiany.

## D. Weryfikacja

Na VM:

```sh
sudo wlb-monitoring status                                   # plik reguły, override, reguła w jądrze, nasłuch
sudo nft list ruleset | grep 'dport 9100'                    # dokładnie jedna reguła, w monitoring_in
ps -o args= -C prometheus-node-exporter                      # efektywna komenda: 0.0.0.0:9100 + flagi z obrazu
```

Z serwera monitoringu (dozwolony adres) i z dowolnego innego hosta (oczekiwany brak połączenia):

```sh
curl -sS --max-time 5 http://<adres-vm>:9100/metrics | grep -E '^(node_cpu_seconds_total|wlb_health_timestamp_seconds)'
```

**Widoczność w monitoringu uznaj za potwierdzoną dopiero po udanym scrape'ie po stronie Prometheusa**
z etykietą pozwalającą rozpoznać Laboratorium (patrz E). Sam lokalny `curl` tego nie dowodzi.

Etap 5 CI (`tests/acceptance.d/67-monitoring-siec.sh`) sprawdza na VM testowej z prawdziwą zaporą:
pobranie z dozwolonego źródła i odrzucenie innego (dwa źródła przez veth), zachowanie dostępu do huba,
restart zapory, zatrzymanie zapory (eksporter staje i nie startuje), wyłączenie i ponowienie przerwanego
wyłączenia. **Restart całej VM** nie jest tam testowany — po pierwszym wdrożeniu testowym sprawdź ręcznie:
`sudo reboot`, potem D.

## E. Onboarding po stronie infrastruktury

1. Nazwa VM i adres, pod którym monitoring ma prowadzić scrape; port `9100`, ścieżka `/metrics`, 30 s.
2. Prośba o etykietę `lab` (wartość = `LAB_NAME`): generator celów nadaje dziś tylko `host` i `env`,
   więc przy wielu Laboratoriach `env` ich nie rozdzieli.
3. Potwierdzenie warunku wstępnego (adres źródłowy należy wyłącznie do monitoringu).

## Rollback

```sh
sudo wlb-monitoring disable
sudo sed -i '/^MONITORING_CIDR=/d' /etc/wlb/lab.env   # żeby kolejne wdrożenie nie włączyło ponownie
```

`disable` najpierw usuwa regułę (port 9100 od razu odrzucany przez politykę `drop`), potem plik reguły
i override, restartuje eksporter i **kończy się sukcesem dopiero po potwierdzeniu** nasłuchu wyłącznie
na `127.0.0.1:9100`. Ponowienie naprawia stan także wtedy, gdy poprzedni przebieg przerwano po usunięciu
pliku (proces nadal słuchał na `0.0.0.0`).

## Ograniczenia

- **Brak alertingu po stronie monitoringu.** Stack nie ma Alertmanagera ani ustalonego odbiorcy
  powiadomień; metryki będą widoczne, ale nikt nie dostanie alertu o zapełnionym dysku czy przepełnionej
  kolejce SIEM (#32).
- **HTTP bez TLS i bez auth** — patrz warunek wstępny.
- **Ręczne `nft flush ruleset`** (poza systemd) usuwa regułę, ale nie zatrzymuje eksportera; nasłuch
  zostaje bez filtra do następnego restartu zapory albo eksportera. Do zmian zapory używaj
  `systemctl restart nftables` (eksporter jest zatrzymywany razem z nią).
- **`/hub/metrics` JupyterHuba nie jest wystawiony** (aktywni badacze, czas spawnu) — osobne zadanie.
- **Retencja** po stronie monitoringu: 90 dni / limit 150 GB.

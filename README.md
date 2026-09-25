# WLB — golden image VM Laboratorium (JupyterHub)

Obraz bazowy VM dla Wirtualnych Laboratoriów Badawczych GUMed IP_CMC, zgodny ze
„Specyfikacją VM z JupyterHub dla badacza — MVP”. Jedna VM na Laboratorium,
The Littlest JupyterHub, kategoria **ogólnego przeznaczenia** (bez GPU).

Obraz budujemy raz Packerem z Ansible, a wynikiem jest `qcow2` dla Proxmoxa i OpenStacka.
Wszystko, co zależy od konkretnego Laboratorium (hostname, klucz SSH, udziały, proxy, SIEM,
administrator huba), przychodzi przy starcie przez cloud-init. Na żywej VM nic nie
zmieniamy ręcznie.

## Struktura

```
packer/                 definicja budowania (QEMU/KVM, obraz chmurowy Ubuntu 24.04 z przypiętego wydania)
ansible/                playbook i role instalujące zawartość obrazu
  roles/base            aktualizacja, pakiety, SSH tylko dla administratorów platformy, utwardzenie
  roles/storage         katalogi §10, katalogi domowe w /workspace, śluza wyjściowa
  roles/tljh            TLJH, Native Authenticator, idle culling 30 min, limit 12 h, izolacja sesji
  roles/python_env      kernel Python (envs/python)
  roles/r_env           R, IRkernel, HADES, sterownik JDBC PostgreSQL (envs/r)
  roles/rstudio         RStudio przez JupyterLab (opcjonalnie, domyślnie wyłączone)
  roles/audit           reguły auditd (śluzy, polecenia badaczy, odmowy dostępu), blokada -e 2
  roles/logging         journald -> rsyslog, historia poleceń powłoki
  roles/lab_config      wlb-firstboot: konfiguracja per-Lab przy pierwszym starcie
envs/python/            environment.yml (+ environment.lock.yml po zamrożeniu)
envs/r/                 hades-packages.txt, renv.lock, skrypt instalacji
cloud-init/             przykładowy user-data i opis zmiennych Laboratorium (lab.env)
tests/                  lokalne uruchomienie obrazu i kryteria akceptacji MVP
```

## Wymagania (WSL2 / Linux)

- QEMU/KVM z dostępem do `/dev/kvm` (użytkownik w grupie `kvm`; w WSL po dodaniu grupy
  uruchom `wsl --shutdown`)
- Packer ≥ 1.10, Ansible ≥ 2.15, `cloud-image-utils`, `genisoimage`
- ok. 40 GB miejsca, 6 GB RAM dla maszyny budującej

## Budowanie

```bash
make init                       # wtyczki Packera (raz)
make validate
make build IMAGE_VERSION=0.1.0  # -> output/wlb-general-0.1.0-<data>/*.qcow2 + sha256 + manifest
```

Pierwsze budowanie trwa długo: kompilacja i instalacja pakietów HADES może zająć godzinę albo dłużej.

### Zamrożone wersje pakietów

Po pierwszym budowaniu w `build/artifacts/<obraz>/` lądują `environment.lock.yml`
i `renv.lock` z dokładnymi wersjami. Przenieś je do repozytorium:

```bash
make freeze && git add envs/ && git commit -m "Zamrożenie środowisk dla 0.1.0"
```

Od tej chwili każde budowanie odtwarza te same wersje. Zmiana pakietów wygląda tak:
edycja `environment.yml` lub `hades-packages.txt`, usunięcie locka, budowanie, `make freeze`, commit.
Wersje CRAN wyznacza też data snapshotu Posit Package Managera (`r_cran_snapshot_date`).

## Test lokalny

```bash
make test-up     # VM z obrazu + cloud-init Laboratorium testowego (tests/cloud-init/)
make test        # kryteria akceptacji MVP
make test-down
```

Hub jest dostępny pod `http://localhost:8080`, a SSH przez
`ssh -p 2222 -i build/test/id_ed25519 wlbadmin@127.0.0.1`.
Hasło początkowe administratora huba (`admin-klienta`) leży w VM w
`/root/wlb-hub-admin-initial-password`.

W teście nie ma udziałów sieciowych, proxy ani SIEM. Katalogi §10 są lokalne, a
`EGRESS_ALLOW` wskazuje nieistniejący adres, więc każde wyjście badacza musi się nie udać.

## Wdrożenie obrazu

OpenStack:
```bash
openstack image create wlb-general-0.1.0 --disk-format qcow2 --container-format bare \
  --file output/wlb-general-0.1.0-*/wlb-general-0.1.0-*.qcow2 \
  --property hw_disk_bus=virtio --property hw_qemu_guest_agent=yes --private
openstack server create lab-example01 --image wlb-general-0.1.0 --flavor wlb.general \
  --network lab-example01-net --user-data cloud-init/lab-user-data.example.yaml \
  --block-device source_type=blank,destination_type=volume,volume_size=200,delete_on_termination=false
```

Proxmox: `qm importdisk <vmid> <obraz>.qcow2 <storage>`, dysk cloud-init oraz
`qm set <vmid> --cicustom user=snippets:lab-example01.yaml`.

Każda nowa instancja potrzebuje własnego user-data według wzoru `cloud-init/lab-user-data.example.yaml`
(zmienne opisuje `cloud-init/lab.env.example`). Do czasu zakończenia `wlb-firstboot`
VM przyjmuje z sieci wyłącznie SSH.

## Kryteria akceptacji MVP

| Kryterium | Realizacja | Test lokalny |
|---|---|---|
| Badacz loguje się swoim kontem i widzi tylko własny katalog | Native Authenticator; `HOME=/workspace`, `HOME_MODE 0700`, `/workspace` 0711 | tak |
| Notebook Python i R w tej samej sesji | kernel `python3` + `ir` (IRkernel, HADES) w jednym JupyterLab | tak (nbconvert) |
| Odczyt `/data-mart` bez modyfikacji | udział `ro` + prawa 0750 + `ReadOnlyPaths` w jednostce systemd | tak |
| Zapis do `/sluza-in` kończy się odmową | jw. | tak |
| Plik w `/sluza-out` znika i trafia do kolejki | katalog 1730 (bez listowania) + `wlb-sluza-out` przenosi do kolejki | tak |
| Połączenie poza allowlistą się nie udaje | nftables per UID badacza (obrona w głębi) + proxy i sieć Laboratorium | częściowo (brak proxy) |
| Po 12 h sesja kończy się niezależnie od aktywności | culler `--max-age=43200`, ciasteczko i tokeny 12 h | konfiguracja; faktyczny czas — ręcznie |
| Zdarzenia widoczne w logu centralnym | auditd + journald -> rsyslog -> SIEM (`SIEM_HOST`) | lokalnie tak, SIEM — na klastrze |

Test ręczny 12 h: ustaw w VM testowej
`tljh-config set services.cull.max_age 300 && tljh-config reload hub`, zaloguj się
i sprawdź, czy serwer zostanie zatrzymany po 5 minutach mimo aktywności.

## Decyzje i odstępstwa od specyfikacji

- **TLJH 2.0.0** (JupyterHub 5) zamiast 1.x. To aktualne wydanie, wersja przypięta w `group_vars/all.yml`.
- **Admini huba bez sudo.** TLJH domyślnie daje administratorom huba pełne sudo. Wyłączyliśmy to, bo
  Administrator Klienta nie powinien móc zmieniać logów (§21) ani instalować oprogramowania (§24.c).
- **Konta badaczy** zakłada Administrator Klienta, zatwierdzając wniosek w `/hub/authorize`,
  albo administrator platformy przez `wlb-hub-user <login>`. Samodzielna rejestracja
  (`open_signup`) jest wyłączona.
- **UID badaczy od 10000.** Reguły audytu i zapory odróżniają w ten sposób badaczy od
  administratorów platformy (w user-data `uid: 1001`).
- **RStudio** działa przez JupyterLab (`jupyter-rsession-proxy`), a nie na osobnym porcie. Konta
  tworzone przez TLJH nie mają haseł systemowych, więc logowanie PAM do samodzielnego RStudio
  Server nie zadziała. Dzięki temu limity sesji obejmują też RStudio.
- **Reguły audytu** są ładowane po zamontowaniu udziałów i blokowane (`auditctl -e 2`).
  Zmiana reguł wymaga restartu VM.
- **Brak automatycznych aktualizacji.** Poprawki bezpieczeństwa wchodzą przez nową wersję obrazu.

## Otwarte kwestie

- Historia poleceń obejmuje terminal (syslog `wlb-shell`) i każde uruchomienie procesu (auditd
  `execve`). Kod wykonywany w komórkach notebooków nie jest osobno logowany.
- DNS: procesy badaczy rozwiązują nazwy przez lokalny `systemd-resolved`. Filtrowanie DNS
  (ochrona przed tunelowaniem) trzeba zrobić na poziomie sieci Laboratorium.
- `pip install --user` przez mirror PyPI jest technicznie możliwe. Trzeba zdecydować, czy mirror
  ma być dostępny dla badaczy (§24.c), czy tylko dla budowania obrazu.
- HTTPS: hub nasłuchuje na porcie 80 i zakłada TLS na portalu WLB lub bramce VDI. Ewentualnie
  można włączyć `https.*` w TLJH.
- GPU (RTX PRO 6000, passthrough), wybór Proxmox vs OpenStack, dostęp testera (portal czy
  bezpośrednio), rozmiar `/workspace` i `/data-mart` — zgodnie z listą otwartych pytań w specyfikacji.

#!/usr/bin/env bats
# Testy jednostkowe wlb-firstboot w piaskownicy (WLB_ROOT) z atrapami poleceń systemowych.

load helpers

setup() {
  setup_sandbox
  cat >"$SANDBOX/etc/wlb/image.conf" <<'EOF'
WLB_RESEARCHER_UID_MIN=10000
WLB_RESEARCHER_UID_MAX=59999
WLB_RESEARCHER_GROUP=jupyterhub-users
WLB_TLJH_ADMIN_SUDO=0
EOF
  cat >"$SANDBOX/etc/wlb/directories.conf" <<'EOF'
# ścieżka właściciel grupa tryb
/workspace root root 0711
/workspace/.wlb-hub root root 0700
/sluza-in root jupyterhub-users 0750
/sluza-out root jupyterhub-users 1730
/data-mart root jupyterhub-users 0750
EOF
  cat >"$SANDBOX/etc/wlb/lab.env" <<'EOF'
LAB_NAME=lab-unit01
HUB_ADMIN_USER=admin-klienta
PROXY_URL=http://10.20.0.10:3128
PYPI_INDEX_URL=https://pypi.wlb.local/simple
CRAN_MIRROR_URL=https://cran.wlb.local
EGRESS_ALLOW="10.20.0.10:3128 10.30.0.0/24:5432"
NTP_SERVERS="10.10.0.2 ntp.wlb.local"
ADMIN_SSH_CIDR=10.10.0.0/24
SIEM_HOST=10.40.0.20
SIEM_TLS_NAME=siem.wlb.local
EOF
  mkdir -p "$SANDBOX/etc/sudoers.d"
  touch "$SANDBOX/etc/sudoers.d/jupyterhub-admins"
  for cmd in logger systemctl nft rsyslogd chown curl groupadd useradd sleep chronyc openssl; do stub "$cmd"; done
  # TLS do SIEM (#6): moduł rsyslog i CA z cloud-init; openssl (atrapa) "potwierdza" poprawny PEM
  mkdir -p "$SANDBOX/usr/lib/x86_64-linux-gnu/rsyslog"
  touch "$SANDBOX/usr/lib/x86_64-linux-gnu/rsyslog/lmnsd_gtls.so" "$SANDBOX/etc/wlb/siem-ca.pem"
  stub getent 2
  stub tljh-config 0 "users:"
  stub wlb-hub-user 0 "haslo-poczatkowe-123"
  export WLB_TLJH_CONFIG="$STUBS/tljh-config" WLB_HUB_USER_TOOL="$STUBS/wlb-hub-user" WLB_HUB_WAIT_SECONDS=4
  # zasoby VM (#30): domyślnie 16 GiB RAM, 8 vCPU
  meminfo 16384
  stub nproc 0 8
  export WLB_MEMINFO="$SANDBOX/proc/meminfo"
}

@test "brak lab.env kończy się błędem" {
  rm "$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"brak $SANDBOX/etc/wlb/lab.env"* ]]
}

@test "brak LAB_NAME kończy się błędem" {
  sed -i '/^LAB_NAME=/d' "$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -ne 0 ]
  [[ $output == *"LAB_NAME jest wymagane"* ]]
}

@test "pełna konfiguracja Laboratorium" {
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  [[ $output == *"Laboratorium lab-unit01 skonfigurowane"* ]]

  # katalogi i prawa
  [ -d "$SANDBOX/sluza-out" ] && [ -d "$SANDBOX/workspace/.wlb-hub" ]
  [ "$(stat -c %a "$SANDBOX/sluza-out")" = 1730 ]
  calls | grep -q "chown root:jupyterhub-users $SANDBOX/sluza-in"

  # proxy i mirrory
  grep -qx 'https_proxy=http://10.20.0.10:3128' "$SANDBOX/etc/environment"
  grep -qx 'no_proxy=localhost,127.0.0.1' "$SANDBOX/etc/environment"
  grep -qx 'index-url = https://pypi.wlb.local/simple' "$SANDBOX/etc/pip.conf"
  grep -q 'CRAN = "https://cran.wlb.local"' "$SANDBOX/etc/wlb/r-repos.R"

  # środowisko serwerów notebooków to poprawny Python z proxy
  hubcfg="$SANDBOX/opt/tljh/config/jupyterhub_config.d/50-wlb-lab.py"
  python3 -m py_compile "$hubcfg"
  grep -q '"WLB_LAB_NAME": "lab-unit01"' "$hubcfg"
  grep -q '"HTTPS_PROXY": "http://10.20.0.10:3128"' "$hubcfg"

  # zapora
  nftcfg="$SANDBOX/etc/nftables.conf"
  grep -q 'ip daddr 10.20.0.10 tcp dport 3128 accept' "$nftcfg"
  grep -q 'ip daddr 10.30.0.0/24 tcp dport 5432 accept' "$nftcfg"
  grep -q 'meta skuid 10000-59999 jump researcher_egress' "$nftcfg"
  grep -q 'ip saddr 10.10.0.0/24 tcp dport 22 accept' "$nftcfg"
  grep -q 'ip saddr 0.0.0.0/0 tcp dport { 80, 443 } accept' "$nftcfg"
  calls | grep -q "nft -c -f $nftcfg"

  # SIEM
  grep -q 'target="10.40.0.20" port="6514" protocol="tcp"' "$SANDBOX/etc/rsyslog.d/60-wlb-siem.conf"
  # TLS z weryfikacją nazwy serwera (#6)
  grep -q 'StreamDriver="gtls" StreamDriverMode="1" StreamDriverAuthMode="x509/name"' "$SANDBOX/etc/rsyslog.d/60-wlb-siem.conf"
  grep -q 'StreamDriverPermittedPeers="siem.wlb.local" streamDriver.CAFile="/etc/wlb/siem-ca.pem"' "$SANDBOX/etc/rsyslog.d/60-wlb-siem.conf"
  calls | grep -q "openssl x509 -noout -in $SANDBOX/etc/wlb/siem-ca.pem"
  [[ $output == *"logi przekazywane do 10.40.0.20:6514/tcp (TLS, serwer siem.wlb.local)"* ]]
  # pola zaufane nadawcy w każdym wpisie (#44)
  grep -q 'template="WLB_SyslogProtocol23Trusted"' "$SANDBOX/etc/rsyslog.d/60-wlb-siem.conf"
  grep -qF '[wlb@32473 input=\"%inputname%\" uid=\"%$!uid%\" gid=\"%$!gid%\" pid=\"%$!pid%\"]' "$SANDBOX/etc/rsyslog.d/60-wlb-siem.conf"

  # NTP (#5): źródła z lab.env, przeładowanie chrony
  grep -qx 'server 10.10.0.2 iburst' "$SANDBOX/etc/chrony/sources.d/wlb.sources"
  grep -qx 'server ntp.wlb.local iburst' "$SANDBOX/etc/chrony/sources.d/wlb.sources"
  calls | grep -qx 'chronyc reload sources'

  # śluza wyjściowa restartowana po montowaniach (#4)
  calls | grep -qx 'systemctl restart wlb-sluza-out.service'

  # hub: admin, brak sudo, hasło początkowe tylko dla roota
  calls | grep -qx 'tljh-config add-item users.admin admin-klienta'
  calls | grep -qx 'tljh-config reload hub'
  [ ! -e "$SANDBOX/etc/sudoers.d/jupyterhub-admins" ]
  [ "$(cat "$SANDBOX/root/wlb-hub-admin-initial-password")" = haslo-poczatkowe-123 ]
  [ "$(stat -c %a "$SANDBOX/root/wlb-hub-admin-initial-password")" = 600 ]

  # koniec: znacznik i reguły audytu
  [ -s "$SANDBOX/var/lib/wlb/firstboot.done" ]
  calls | grep -qx 'systemctl start wlb-audit-rules.service'
  # dane testowe tylko w LOCAL_TEST_MODE
  [ ! -e "$SANDBOX/data-mart/wlb-test-cohort.csv" ]
}

@test "drugie uruchomienie nic nie robi" {
  "$FIRSTBOOT" >/dev/null
  : >"$CALLS"
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  [[ $output == *"już wykonane"* ]]
  refute called tljh-config
}

@test "--force nie dubluje admina i nie nadpisuje hasła" {
  "$FIRSTBOOT" >/dev/null
  stub tljh-config 0 $'users:\n  admin:\n  - admin-klienta'
  stub wlb-hub-user 0 "inne-haslo-456789"
  : >"$CALLS"
  run "$FIRSTBOOT" --force
  [ "$status" -eq 0 ]
  refute called add-item
  [ "$(cat "$SANDBOX/root/wlb-hub-admin-initial-password")" = haslo-poczatkowe-123 ]
}

@test "ponowne uruchomienie usuwa stare ustawienia proxy" {
  "$FIRSTBOOT" >/dev/null
  sed -i '/^PROXY_URL=/d' "$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT" --force
  [ "$status" -eq 0 ]
  refute grep -q proxy "$SANDBOX/etc/environment"
  refute grep -q PROXY "$SANDBOX/opt/tljh/config/jupyterhub_config.d/50-wlb-lab.py"
}

@test "nieprawidłowy wpis EGRESS_ALLOW przerywa konfigurację" {
  sed -i 's/^EGRESS_ALLOW=.*/EGRESS_ALLOW="10.20.0.10"/' "$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"nieprawidłowy wpis EGRESS_ALLOW: '10.20.0.10'"* ]]
  [ ! -e "$SANDBOX/var/lib/wlb/firstboot.done" ]
}

@test "błędne reguły nftables przerywają konfigurację" {
  stub nft 1
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"błędne reguły nftables"* ]]
}

@test "bez NTP_SERVERS: ostrzeżenie i brak źródeł z obrazu" {
  mkdir -p "$SANDBOX/etc/chrony/sources.d"
  touch "$SANDBOX/etc/chrony/sources.d/wlb.sources"
  sed -i '/^NTP_SERVERS=/d' "$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  [ ! -e "$SANDBOX/etc/chrony/sources.d/wlb.sources" ]
  [[ $output == *"NTP_SERVERS nie ustawione"* ]]
}

@test "nieprawidłowy serwer NTP przerywa konfigurację" {
  sed -i 's/^NTP_SERVERS=.*/NTP_SERVERS="10.10.0.2 ;rm"/' "$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"nieprawidłowy serwer w NTP_SERVERS: ';rm'"* ]]
  [ ! -e "$SANDBOX/etc/chrony/sources.d/wlb.sources" ] # bez połowicznego pliku
}

@test "chronyc niedostępny: restart usługi chrony z przyczyną w logu" {
  stub chronyc 1 "506 Cannot talk to daemon"
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  calls | grep -qx 'systemctl restart chrony'
  calls | grep -q 'logger -t wlb-firstboot -- chronyc reload sources nieudane (506 Cannot talk to daemon) — restart usługi chrony'
}

@test "NTP_SERVERS: nazwy hostów, IPv4 i IPv6 są przyjmowane" {
  sed -i 's/^NTP_SERVERS=.*/NTP_SERVERS="ntp.example.com 10.0.0.1 2001:db8::1 ::ffff:10.0.0.1 ntp-1"/' "$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  for s in ntp.example.com 10.0.0.1 2001:db8::1 ::ffff:10.0.0.1 ntp-1; do
    grep -qx "server $s iburst" "$SANDBOX/etc/chrony/sources.d/wlb.sources"
  done
}

@test "NTP_SERVERS: zapis host:port jest odrzucany z wyjaśnieniem" {
  for s in 10.0.0.1:123 ntp.example.com:123; do
    sed -i "s/^NTP_SERVERS=.*/NTP_SERVERS=\"$s\"/" "$SANDBOX/etc/wlb/lab.env"
    run "$FIRSTBOOT"
    [ "$status" -eq 1 ]
    [[ $output == *"'$s' — zapis host:port nie jest obsługiwany"* ]]
    [ ! -e "$SANDBOX/etc/chrony/sources.d/wlb.sources" ]
  done
}

@test "NTP_SERVERS: niepoprawne nazwy są odrzucane" {
  for s in -ntp.example ntp..example ntp_1 2001:db8::zz; do
    sed -i "s/^NTP_SERVERS=.*/NTP_SERVERS=\"$s\"/" "$SANDBOX/etc/wlb/lab.env"
    run "$FIRSTBOOT"
    [ "$status" -eq 1 ]
    [[ $output == *"nieprawidłowy serwer w NTP_SERVERS: '$s'"* ]]
  done
}

@test "bez SIEM_HOST logi zostają lokalnie" {
  mkdir -p "$SANDBOX/etc/rsyslog.d"
  touch "$SANDBOX/etc/rsyslog.d/60-wlb-siem.conf"
  sed -i '/^SIEM_HOST=/d' "$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  [ ! -e "$SANDBOX/etc/rsyslog.d/60-wlb-siem.conf" ]
  [[ $output == *"SIEM_HOST nie ustawiony"* ]]
}

@test "błędna konfiguracja rsyslog przerywa konfigurację" {
  stub rsyslogd 1
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"błędna konfiguracja rsyslog"* ]]
}

@test "konto admina z dysku roboczego — hasło bez zmian" {
  stub wlb-hub-user 0 ""
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  calls | grep -qx 'wlb-hub-user --if-missing admin-klienta'
  [ ! -e "$SANDBOX/root/wlb-hub-admin-initial-password" ]
  [[ $output == *"admin-klienta już istnieje (dysk roboczy)"* ]]
}

@test "WLB_TLJH_ADMIN_SUDO=1 zostawia sudo adminom huba" {
  sed -i 's/^WLB_TLJH_ADMIN_SUDO=0/WLB_TLJH_ADMIN_SUDO=1/' "$SANDBOX/etc/wlb/image.conf"
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  [ -e "$SANDBOX/etc/sudoers.d/jupyterhub-admins" ]
}

@test "hub nie odpowiada — błąd" {
  stub curl 7
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"JupyterHub nie odpowiada"* ]]
  calls | grep -q '^sleep 2'
}

@test "nie da się ustawić praw katalogu — ostrzeżenie, bez przerywania" {
  stub chown 1
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  [[ $output == *"nie można ustawić praw /sluza-in"* ]]
}

@test "LOCAL_TEST_MODE zasiewa dane przykładowe" {
  echo LOCAL_TEST_MODE=1 >>"$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  head -1 "$SANDBOX/data-mart/wlb-test-cohort.csv" | grep -q person_id
  [ -s "$SANDBOX/sluza-in/wlb-test-input.txt" ]
}

@test "odtwarza konta badaczy z dysku roboczego z tym samym UID" {
  # właścicielem katalogu w piaskownicy jest bieżący użytkownik — ustawiamy zakres UID pod niego
  me=$(id -u)
  sed -i "s/^WLB_RESEARCHER_UID_MIN=.*/WLB_RESEARCHER_UID_MIN=$me/" "$SANDBOX/etc/wlb/image.conf"
  mkdir -p "$SANDBOX/workspace/jupyter-anna"
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  calls | grep -qx "groupadd -g $(id -g) jupyter-anna"
  calls | grep -qx "useradd -u $me -g jupyter-anna -G jupyterhub-users -d /workspace/jupyter-anna -M -s /bin/bash jupyter-anna"
  [[ $output == *"odtworzono konto jupyter-anna (UID $me)"* ]]
}

@test "GID katalogu domowego zajęty — grupa badacza z nowym GID" {
  me=$(id -u)
  sed -i "s/^WLB_RESEARCHER_UID_MIN=.*/WLB_RESEARCHER_UID_MIN=$me/" "$SANDBOX/etc/wlb/image.conf"
  mkdir -p "$SANDBOX/workspace/jupyter-anna"
  # getent passwd/group po nazwie -> brak; getent group <GID> -> zajęty
  cat >"$STUBS/getent" <<'EOF'
#!/usr/bin/env bash
echo "getent $*" >>"$CALLS"
[[ $1 == group && $2 =~ ^[0-9]+$ ]]
EOF
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  calls | grep -qx "groupadd jupyter-anna"
  called "useradd -u $me -g jupyter-anna"
  [[ $output == *"GID $(id -g)"*"jest zajęty"* ]]
}

@test "istniejące konto badacza nie jest zakładane ponownie" {
  mkdir -p "$SANDBOX/workspace/jupyter-anna"
  stub getent 0
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  refute called useradd
}

@test "katalog domowy z UID spoza zakresu badaczy jest pomijany" {
  sed -i 's/^WLB_RESEARCHER_UID_MIN=.*/WLB_RESEARCHER_UID_MIN=4000000000/' "$SANDBOX/etc/wlb/image.conf"
  mkdir -p "$SANDBOX/workspace/jupyter-obcy"
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  [[ $output == *"spoza zakresu badaczy"* ]]
  refute called useradd
}

@test "UID zajęty przez inne konto — pomijany" {
  me=$(id -u)
  sed -i "s/^WLB_RESEARCHER_UID_MIN=.*/WLB_RESEARCHER_UID_MIN=$me/" "$SANDBOX/etc/wlb/image.conf"
  mkdir -p "$SANDBOX/workspace/jupyter-anna"
  # getent passwd jupyter-anna -> brak; getent passwd <UID> -> istnieje
  cat >"$STUBS/getent" <<'EOF'
#!/usr/bin/env bash
echo "getent $*" >>"$CALLS"
[[ $2 =~ ^[0-9]+$ ]]
EOF
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  [[ $output == *"jest zajęty przez inne konto"* ]]
  refute called useradd
}

@test "konto huba: trwała blokada bazy przerywa firstboot czytelnym błędem (#31)" {
  stub wlb-hub-user 1 # narzędzie zawsze zawodzi (np. baza huba stale zablokowana)
  export WLB_HUB_USER_RETRY_SLEEP=0
  run "$FIRSTBOOT"
  [ "$status" -ne 0 ]
  [[ $output == *"nie udało się założyć konta huba"* ]]
  [ ! -e "$SANDBOX/var/lib/wlb/firstboot.done" ] # bez znacznika → reguły audytu nie są cicho pomijane
}

# --- TLS do SIEM (#6) ------------------------------------------------------------------------

siem_env() { # siem_env KLUCZ=WARTOŚĆ... — nadpisuje lub dopisuje zmienne w lab.env
  local kv
  for kv in "$@"; do
    sed -i "/^${kv%%=*}=/d" "$SANDBOX/etc/wlb/lab.env"
    echo "$kv" >>"$SANDBOX/etc/wlb/lab.env"
  done
}

@test "SIEM TLS: brak certyfikatu CA przerywa konfigurację (fail-secure)" {
  rm "$SANDBOX/etc/wlb/siem-ca.pem"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"brak certyfikatu CA SIEM /etc/wlb/siem-ca.pem"* ]]
  [ ! -e "$SANDBOX/etc/rsyslog.d/60-wlb-siem.conf" ]
}

@test "SIEM TLS: certyfikat CA poza /etc/wlb/*.pem jest odrzucany (AppArmor rsyslogd)" {
  mkdir -p "$SANDBOX/etc/ssl"
  touch "$SANDBOX/etc/ssl/siem-ca.pem"
  siem_env SIEM_CA_CERT=/etc/ssl/siem-ca.pem
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"certyfikat CA musi leżeć w /etc/wlb/*.pem (AppArmor rsyslogd)"* ]]
}

@test "SIEM TLS: nieczytelny certyfikat CA przerywa konfigurację" {
  stub openssl 1
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"nie jest poprawnym certyfikatem PEM"* ]]
}

@test "SIEM TLS: brak modułu lmnsd_gtls przerywa konfigurację" {
  rm "$SANDBOX/usr/lib/x86_64-linux-gnu/rsyslog/lmnsd_gtls.so"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"brak modułu TLS rsyslog (lmnsd_gtls.so, pakiet rsyslog-gnutls)"* ]]
}

@test "SIEM TLS: adres IP bez SIEM_TLS_NAME przerywa konfigurację" {
  sed -i '/^SIEM_TLS_NAME=/d' "$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"SIEM_HOST=10.40.0.20 to adres IP — ustaw SIEM_TLS_NAME"* ]]
}

@test "SIEM TLS: nazwa serwera domyślnie z SIEM_HOST, gdy to nazwa DNS" {
  sed -i '/^SIEM_TLS_NAME=/d' "$SANDBOX/etc/wlb/lab.env"
  siem_env SIEM_HOST=siem.gumed.local
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  grep -q 'StreamDriverPermittedPeers="siem.gumed.local"' "$SANDBOX/etc/rsyslog.d/60-wlb-siem.conf"
}

@test "SIEM TLS: nieprawidłowa nazwa serwera i UDP są odrzucane" {
  siem_env 'SIEM_TLS_NAME="siem.local\" x=\"1"'
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"nieprawidłowe SIEM_TLS_NAME"* ]]
  siem_env SIEM_TLS_NAME=siem.wlb.local SIEM_PROTOCOL=udp
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"SIEM_TLS=1 wymaga SIEM_PROTOCOL=tcp"* ]]
}

@test "SIEM_TLS=0: bez TLS, port 514 i wyraźne ostrzeżenie" {
  siem_env SIEM_TLS=0
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  grep -q 'target="10.40.0.20" port="514" protocol="tcp"' "$SANDBOX/etc/rsyslog.d/60-wlb-siem.conf"
  refute grep -q StreamDriver "$SANDBOX/etc/rsyslog.d/60-wlb-siem.conf"
  [[ $output == *"uwaga: SIEM_TLS=0 — logi (polecenia badaczy, loginy, eksporty) idą do SIEM otwartym tekstem"* ]]
  calls | grep -q "logger -t wlb-firstboot -- uwaga: SIEM_TLS=0"
}

@test "SIEM_TLS: wartość inna niż 0/1 jest odrzucana" {
  siem_env SIEM_TLS=tak
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"SIEM_TLS musi być 0 albo 1, jest 'tak'"* ]]
}

# --- Limity zasobów badaczy (#30) --------------------------------------------------------------

meminfo() { # meminfo MiB — MemTotal w piaskownicy
  mkdir -p "$SANDBOX/proc"
  printf 'MemTotal:       %d kB\nMemFree:        1000 kB\n' $(($1 * 1024)) >"$SANDBOX/proc/meminfo"
}
limits() { cat "$SANDBOX/opt/tljh/config/jupyterhub_config.d/60-wlb-limits.py"; }
slice_conf() { cat "$SANDBOX/etc/systemd/system/wlb-badacze.slice.d/50-wlb-limits.conf"; }
lab_env() { # lab_env KLUCZ=WARTOŚĆ...
  local kv
  for kv in "$@"; do echo "$kv" >>"$SANDBOX/etc/wlb/lab.env"; done
}

@test "limity: 16 GiB / 8 vCPU, jeden badacz (domyślnie) — rezerwa 3 GiB, cała pula i wszystkie vCPU" {
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  slice_conf | grep -qx 'MemoryMax=13312M'
  limits | grep -qx 'c.SystemdSpawner.mem_limit = "13312M"'
  limits | grep -qx 'c.SystemdSpawner.cpu_limit = float("8")'
  limits | grep -q '"TasksMax": "2048"'
  limits | grep -q '"OOMScoreAdjust": "500"'
  limits | grep -q '"OOMPolicy": "continue"'
  calls | grep -qx 'systemctl daemon-reload'
  [[ $output == *"limity: RAM 16384 MiB, rezerwa 3072 MiB, badacze razem 13312 MiB (1 równolegle); na badacza 13312 MiB, CPU 8, procesy 2048"* ]]
  python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$SANDBOX/opt/tljh/config/jupyterhub_config.d/60-wlb-limits.py"
}

@test "limity: duża VM — rezerwa 10% RAM" {
  meminfo 65536
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  slice_conf | grep -qx 'MemoryMax=58983M'
  limits | grep -qx 'c.SystemdSpawner.mem_limit = "58983M"'
}

@test "limity: kilku badaczy na VM (RESEARCHERS_PER_VM) dzieli pulę i vCPU" {
  lab_env RESEARCHERS_PER_VM=4
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  slice_conf | grep -qx 'MemoryMax=13312M'
  limits | grep -qx 'c.SystemdSpawner.mem_limit = "3328M"'
  limits | grep -qx 'c.SystemdSpawner.cpu_limit = float("2")'
  [[ $output == *"(4 równolegle); na badacza 3328 MiB, CPU 2"* ]]
}

@test "limity: 1 vCPU — co najmniej jeden rdzeń na badacza" {
  stub nproc 0 1
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  limits | grep -qx 'c.SystemdSpawner.cpu_limit = float("1")'
}

@test "limity: nadpisania z lab.env" {
  lab_env SYSTEM_MEM_RESERVE=4G RESEARCHER_MEM_LIMIT=8192M RESEARCHER_CPU_LIMIT=1.5 RESEARCHER_TASKS_MAX=512
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  slice_conf | grep -qx 'MemoryMax=12288M'
  limits | grep -qx 'c.SystemdSpawner.mem_limit = "8192M"'
  limits | grep -qx 'c.SystemdSpawner.cpu_limit = float("1.5")'
  limits | grep -q '"TasksMax": "512"'
}

@test "limity: za mała VM przerywa konfigurację" {
  meminfo 3584
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"za mało pamięci dla badaczy: 3584 MiB RAM, rezerwa 3072 MiB"* ]]
}

@test "limity: nieprawidłowe wartości w lab.env są odrzucane" {
  lab_env RESEARCHER_MEM_LIMIT=8GB
  run "$FIRSTBOOT"
  [ "$status" -ne 0 ]
  [[ $output == *"RESEARCHER_MEM_LIMIT: nieprawidłowy rozmiar '8GB'"* ]]
  sed -i '/^RESEARCHER_MEM_LIMIT=/d' "$SANDBOX/etc/wlb/lab.env"

  lab_env RESEARCHER_MEM_LIMIT=20G
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"RESEARCHER_MEM_LIMIT=20G większe niż pula badaczy (13312 MiB)"* ]]
  sed -i '/^RESEARCHER_MEM_LIMIT=/d' "$SANDBOX/etc/wlb/lab.env"

  lab_env RESEARCHER_CPU_LIMIT=dwa
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"nieprawidłowe RESEARCHER_CPU_LIMIT: 'dwa'"* ]]
  sed -i '/^RESEARCHER_CPU_LIMIT=/d' "$SANDBOX/etc/wlb/lab.env"

  lab_env RESEARCHER_TASKS_MAX=10
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"RESEARCHER_TASKS_MAX musi być liczbą >= 64, jest '10'"* ]]
  sed -i '/^RESEARCHER_TASKS_MAX=/d' "$SANDBOX/etc/wlb/lab.env"

  lab_env RESEARCHERS_PER_VM=0
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"RESEARCHERS_PER_VM musi być liczbą 1–64, jest '0'"* ]]
}

# --- Uwierzytelnianie: native / OIDC (#18) ---------------------------------------------------

oidc_env() {
  cat >>"$SANDBOX/etc/wlb/lab.env" <<EOF
AUTH_MODE=oidc
OIDC_CLIENT_ID=klient-wlb
OIDC_CLIENT_SECRET=sekret-123
OIDC_AUTHORIZE_URL=https://login.example.com/oauth2/authorize
OIDC_TOKEN_URL=https://login.example.com/oauth2/token
OIDC_USERDATA_URL=https://login.example.com/oauth2/userinfo
OIDC_CALLBACK_URL=https://portal.wlb.local/hub/oauth_callback
EOF
}
authconf() { cat "$SANDBOX/opt/tljh/config/jupyterhub_config.d/70-wlb-auth.py"; }

@test "AUTH_MODE native (domyślnie): bez pliku OIDC" {
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  [ ! -e "$SANDBOX/opt/tljh/config/jupyterhub_config.d/70-wlb-auth.py" ]
  [[ $output == *"uwierzytelnianie: native"* ]]
}

@test "AUTH_MODE oidc: poprawny config GenericOAuthenticator (allow_all bez grup)" {
  oidc_env
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  python3 -m py_compile "$SANDBOX/opt/tljh/config/jupyterhub_config.d/70-wlb-auth.py"
  authconf | grep -qx "c.JupyterHub.authenticator_class = 'generic-oauth'"
  authconf | grep -qx "c.GenericOAuthenticator.client_id = 'klient-wlb'"
  authconf | grep -qx "c.GenericOAuthenticator.authorize_url = 'https://login.example.com/oauth2/authorize'"
  authconf | grep -qx "c.GenericOAuthenticator.oauth_callback_url = 'https://portal.wlb.local/hub/oauth_callback'"
  authconf | grep -qxF "c.GenericOAuthenticator.scope = ['openid', 'email', 'profile']"
  authconf | grep -qx "c.GenericOAuthenticator.username_claim = 'preferred_username'"
  authconf | grep -qx "c.GenericOAuthenticator.allow_all = True"
  [ "$(stat -c %a "$SANDBOX/opt/tljh/config/jupyterhub_config.d/70-wlb-auth.py")" = 600 ]
  [[ $output == *"uwierzytelnianie: OIDC"* ]]
}

@test "AUTH_MODE oidc: grupy IdP zamiast allow_all" {
  oidc_env
  cat >>"$SANDBOX/etc/wlb/lab.env" <<'EOF'
OIDC_ALLOWED_GROUPS="wlb-lab01, wlb-wszyscy"
OIDC_ADMIN_GROUPS=wlb-admini
OIDC_USERNAME_CLAIM=email
EOF
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  authconf | grep -qxF "c.GenericOAuthenticator.allowed_groups = ['wlb-lab01', 'wlb-wszyscy']"
  authconf | grep -qxF "c.GenericOAuthenticator.admin_groups = ['wlb-admini']"
  authconf | grep -qx "c.GenericOAuthenticator.username_claim = 'email'"
  refute grep -q "allow_all" "$SANDBOX/opt/tljh/config/jupyterhub_config.d/70-wlb-auth.py"
}

@test "AUTH_MODE oidc: brak wymaganej zmiennej przerywa (fail-secure)" {
  oidc_env
  sed -i '/^OIDC_CLIENT_SECRET=/d' "$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"brak wymaganej zmiennej OIDC_CLIENT_SECRET"* ]]
  [ ! -e "$SANDBOX/opt/tljh/config/jupyterhub_config.d/70-wlb-auth.py" ]
}

@test "AUTH_MODE oidc: punkty końcowe i callback muszą być https" {
  oidc_env
  sed -i 's#^OIDC_AUTHORIZE_URL=.*#OIDC_AUTHORIZE_URL=http://login.example.com/oauth2/authorize#' "$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"punkty końcowe OIDC muszą być https"* ]]
  sed -i 's#^OIDC_AUTHORIZE_URL=.*#OIDC_AUTHORIZE_URL=https://login.example.com/oauth2/authorize#' "$SANDBOX/etc/wlb/lab.env"
  sed -i 's#^OIDC_CALLBACK_URL=.*#OIDC_CALLBACK_URL=http://portal.wlb.local/hub/oauth_callback#' "$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"OIDC_CALLBACK_URL musi być https"* ]]
}

@test "AUTH_MODE: wartość inna niż native/oidc jest odrzucana" {
  echo "AUTH_MODE=ldap" >>"$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"AUTH_MODE musi być native albo oidc, jest 'ldap'"* ]]
}

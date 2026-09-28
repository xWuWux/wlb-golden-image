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
EOF
  mkdir -p "$SANDBOX/etc/sudoers.d"
  touch "$SANDBOX/etc/sudoers.d/jupyterhub-admins"
  for cmd in logger systemctl nft rsyslogd chown curl groupadd useradd sleep chronyc; do stub "$cmd"; done
  stub getent 2
  stub tljh-config 0 "users:"
  stub wlb-hub-user 0 "haslo-poczatkowe-123"
  export WLB_TLJH_CONFIG="$STUBS/tljh-config" WLB_HUB_USER_TOOL="$STUBS/wlb-hub-user" WLB_HUB_WAIT_SECONDS=4
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
  grep -q 'target="10.40.0.20" port="514" protocol="tcp"' "$SANDBOX/etc/rsyslog.d/60-wlb-siem.conf"

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

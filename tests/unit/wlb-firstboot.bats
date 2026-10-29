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
HUB_ADMIN_USER=a01
PROXY_URL=http://10.20.0.10:3128
RESEARCHER_PACKAGE_INSTALL=mirror
PYPI_INDEX_URL=https://pypi.wlb.local/simple
CRAN_MIRROR_URL=https://cran.wlb.local
EGRESS_ALLOW="10.20.0.10:3128 10.30.0.0/24:5432"
NTP_SERVERS="10.10.0.2 ntp.wlb.local"
ADMIN_SSH_CIDR=10.10.0.0/24
HUB_ALLOWED_CIDR=10.10.1.0/24
SIEM_HOST=10.40.0.20
SIEM_TLS_NAME=siem.wlb.local
EOF
  mkdir -p "$SANDBOX/etc/sudoers.d"
  touch "$SANDBOX/etc/sudoers.d/jupyterhub-admins"
  for cmd in logger systemctl nft rsyslogd chown curl groupadd useradd sleep chronyc; do stub "$cmd"; done
  # openssl (atrapa): spójne niepuste wyjście, by walidacja TLS huba (#18) i SIEM CA (#6) przeszły
  # happy-path. Kontrola pary klucz–cert porównuje skróty — przy tej samej treści dla certu i klucza
  # obie strony są równe. Testy negatywne re-stubują openssl (kod 1). Realny TLS sprawdza E2E na VM.
  stub openssl 0 "wlb-tls-pubkey-der-digest"
  # TLS do SIEM (#6): moduł rsyslog i CA z cloud-init; TLS huba (#18): cert i klucz (klucz 0600)
  mkdir -p "$SANDBOX/usr/lib/x86_64-linux-gnu/rsyslog"
  touch "$SANDBOX/usr/lib/x86_64-linux-gnu/rsyslog/lmnsd_gtls.so" "$SANDBOX/etc/wlb/siem-ca.pem"
  touch "$SANDBOX/etc/wlb/hub-tls.crt" "$SANDBOX/etc/wlb/hub-tls.key"
  chmod 0600 "$SANDBOX/etc/wlb/hub-tls.key"
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

@test "HUB_ADMIN_USER o nieprawidłowym formacie jest odrzucany (#51)" {
  # login trafia do pliku roli huba (15-wlb-admin-role.py) -> chronimy przed wstrzyknięciem do Pythona;
  # wielkie litery łamią format loginu (^[a-z0-9]...), a są bezpieczne dla sourcowania lab.env
  sed -i 's/^HUB_ADMIN_USER=.*/HUB_ADMIN_USER=Admin-Klienta/' "$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -ne 0 ]
  [[ $output == *"HUB_ADMIN_USER ma nieprawidłowy format"* ]]
}

@test "pre-provisioning kont stanowiskowych uNN wg RESEARCHER_ACCOUNTS (IMG-002/#102)" {
  lab_env RESEARCHER_ACCOUNTS=3
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  for n in u01 u02 u03; do
    calls | grep -qx "wlb-hub-user --if-missing $n"
    [ -s "$SANDBOX/root/wlb-hub-$n-initial-password" ]
    [ "$(stat -c %a "$SANDBOX/root/wlb-hub-$n-initial-password")" = 600 ]
  done
  [ ! -e "$SANDBOX/root/wlb-hub-u04-initial-password" ]  # nie tworzymy ponad limit
}

@test "RESEARCHER_ACCOUNTS=0: tylko admin, zero kont badaczy (IMG-002)" {
  lab_env RESEARCHER_ACCOUNTS=0
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  [ ! -e "$SANDBOX/root/wlb-hub-u01-initial-password" ]
  refute called 'wlb-hub-user --if-missing u01'
}

@test "RESEARCHER_ACCOUNTS spoza zakresu 0–64 jest odrzucane (IMG-002)" {
  lab_env RESEARCHER_ACCOUNTS=65
  run "$FIRSTBOOT"
  [ "$status" -ne 0 ]
  [[ $output == *"RESEARCHER_ACCOUNTS musi być liczbą 0–64"* ]]
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
  # tryb mirror (IMG-004): pakiety użytkownika ładowane, zasady w /docs/pakiety.md
  refute grep -q 'PYTHONNOUSERSITE' "$SANDBOX/etc/environment"
  refute grep -q 'PYTHONNOUSERSITE' "$SANDBOX/opt/tljh/config/jupyterhub_config.d/50-wlb-lab.py"
  grep -q 'kuratorowany mirror' "$SANDBOX/docs/pakiety.md"

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
  # Hub otwierany na realny HUB_ALLOWED_CIDR (nigdy 0.0.0.0/0) i dopiero w fazie 2, po potwierdzeniu TLS (#18)
  grep -q 'ip saddr 10.10.1.0/24 tcp dport { 80, 443 } accept' "$nftcfg"
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

  # hub: rola OGRANICZONA zamiast pełnego admina (IMG-003/#51), brak sudo, hasło tylko dla roota
  refute called 'add-item users.admin'
  grep -q 'wlb-admin-klienta' "$SANDBOX/opt/tljh/config/jupyterhub_config.d/15-wlb-admin-role.py"
  grep -q '"a01"' "$SANDBOX/opt/tljh/config/jupyterhub_config.d/15-wlb-admin-role.py"
  calls | grep -qx 'tljh-config reload hub'
  [ ! -e "$SANDBOX/etc/sudoers.d/jupyterhub-admins" ]
  [ "$(cat "$SANDBOX/root/wlb-hub-admin-initial-password")" = haslo-poczatkowe-123 ]
  [ "$(stat -c %a "$SANDBOX/root/wlb-hub-admin-initial-password")" = 600 ]
  # pre-provisioning kont stanowiskowych uNN (IMG-002/#102); RESEARCHER_ACCOUNTS domyślnie = RESEARCHERS_PER_VM (1)
  calls | grep -qx 'wlb-hub-user --if-missing u01'
  [ "$(cat "$SANDBOX/root/wlb-hub-u01-initial-password")" = haslo-poczatkowe-123 ]
  [ "$(stat -c %a "$SANDBOX/root/wlb-hub-u01-initial-password")" = 600 ]

  # koniec: znacznik i reguły audytu
  [ -s "$SANDBOX/var/lib/wlb/firstboot.done" ]
  calls | grep -qx 'systemctl start wlb-audit-rules.service'
  # dane testowe tylko w LOCAL_TEST_MODE
  [ ! -e "$SANDBOX/data-mart/wlb-test-cohort.csv" ]
}

# --- #18: dostęp (CIDR fail-secure, TLS huba) ---------------------------------------

@test "#18 dostęp: HUB_TLS domyślnie 1 — HTTPS włączone, cert i klucz ustawione" {
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  calls | grep -qx 'tljh-config set https.enabled true'
  calls | grep -qx 'tljh-config set https.tls.cert /etc/wlb/hub-tls.crt'
  calls | grep -qx 'tljh-config set https.tls.key /etc/wlb/hub-tls.key'
}

@test "#18 dostęp: HUB_TLS=0 — hub tylko po HTTP (port 80, bez 443), z ostrzeżeniem" {
  echo 'HUB_TLS=0' >>"$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  # kontrole $output/calls PRZED kolejnym `run` (run nadpisuje $output/$status)
  [[ $output == *"OSTRZEŻENIE: HUB_TLS=0"* ]]
  calls | grep -qx 'tljh-config set https.enabled false'
  nftcfg="$SANDBOX/etc/nftables.conf"
  grep -q 'ip saddr 10.10.1.0/24 tcp dport 80 accept' "$nftcfg"
  run grep -q '443' "$nftcfg"
  [ "$status" -ne 0 ]
}

@test "#18 fail-secure: błąd TLS huba nie otwiera portu huba ani nie kończy firstboot" {
  rm "$SANDBOX/etc/wlb/hub-tls.crt"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"brak certyfikatu huba"* ]]
  # przerwanie nastąpiło przed otwarciem portu huba: reguła portu huba nie została zapisana
  nftcfg="$SANDBOX/etc/nftables.conf"
  [ ! -e "$nftcfg" ] || ! grep -qE 'tcp dport (80|\{ 80, 443 \}) accept' "$nftcfg"
  [ ! -e "$SANDBOX/var/lib/wlb/firstboot.done" ]
}

@test "#18 TLS: klucz huba o zbyt szerokich prawach jest odrzucany" {
  chmod 0644 "$SANDBOX/etc/wlb/hub-tls.key"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"zbyt szerokie prawa"* ]]
}

@test "#18 TLS: certyfikat i klucz nie są parą — odrzucone" {
  # openssl rozróżnia klucz publiczny certu (CERTPUB) od publicznego klucza prywatnego (KEYPUB),
  # dgst/pkey -pubin przepuszczają wejście — skróty się różnią, więc para nie pasuje.
  cat >"$STUBS/openssl" <<'OS'
#!/usr/bin/env bash
echo "openssl $*" >>"$CALLS"
case "$*" in
  *-pubkey*) echo CERTPUB ;;
  *-pubout*) echo KEYPUB ;;
  *-pubin*)  cat ;;
  *dgst*)    cat ;;
  *)         : ;;
esac
exit 0
OS
  chmod +x "$STUBS/openssl"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"certyfikat i klucz nie są parą"* ]]
}

@test "#18 CIDR: HUB_ALLOWED_CIDR=0.0.0.0/0 jest odrzucane (/0)" {
  sed -i 's#^HUB_ALLOWED_CIDR=.*#HUB_ALLOWED_CIDR=0.0.0.0/0#' "$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"prefiks musi być 1–32"* ]]
}

@test "#18 CIDR: końcowa spacja w HUB_ALLOWED_CIDR jest odrzucana" {
  sed -i 's#^HUB_ALLOWED_CIDR=.*#HUB_ALLOWED_CIDR="10.10.1.0/24 "#' "$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"pojedynczej sieci IPv4"* ]]
}

@test "#18 CIDR: lista adresów w ADMIN_SSH_CIDR jest odrzucana" {
  sed -i 's#^ADMIN_SSH_CIDR=.*#ADMIN_SSH_CIDR=10.10.0.0/24,10.20.0.0/24#' "$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"pojedynczej sieci IPv4"* ]]
}

@test "#18 CIDR: prefiks > 32 jest odrzucany" {
  sed -i 's#^ADMIN_SSH_CIDR=.*#ADMIN_SSH_CIDR=10.10.0.0/33#' "$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"prefiks musi być 1–32"* ]]
}

@test "#18 CIDR: brak HUB_ALLOWED_CIDR przerywa konfigurację" {
  sed -i '/^HUB_ALLOWED_CIDR=/d' "$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"HUB_ALLOWED_CIDR jest wymagane"* ]]
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
  stub tljh-config 0 $'users:\n  admin:\n  - a01'
  stub wlb-hub-user 0 "inne-haslo-456789"
  : >"$CALLS"
  run "$FIRSTBOOT" --force
  [ "$status" -eq 0 ]
  refute called add-item
  # konto było wcześniej pełnym adminem (stub users.admin) -> firstboot je degraduje (IMG-003/#51)
  calls | grep -q 'remove-item users.admin a01'
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
  calls | grep -qx 'wlb-hub-user --if-missing a01'
  [ ! -e "$SANDBOX/root/wlb-hub-admin-initial-password" ]
  [[ $output == *"a01 już istnieje (dysk roboczy)"* ]]
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
  # HUB_TLS=0, by openssl 1 trafiał w ścieżkę SIEM CA, nie w wcześniejszą walidację certu huba (#18)
  echo 'HUB_TLS=0' >>"$SANDBOX/etc/wlb/lab.env"
  stub openssl 1
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"SIEM_TLS=1: /etc/wlb/siem-ca.pem nie jest poprawnym certyfikatem PEM"* ]]
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

# --- Instalacja pakietów przez badacza (#23, IMG-004) ---------------------------------------

pkg_mode() { # pkg_mode deny|mirror|'' — ustawia (lub usuwa) przełącznik w lab.env
  sed -i '/^RESEARCHER_PACKAGE_INSTALL=/d' "$SANDBOX/etc/wlb/lab.env"
  [[ -n ${1:-} ]] && echo "RESEARCHER_PACKAGE_INSTALL=$1" >>"$SANDBOX/etc/wlb/lab.env"
  return 0
}
hub_env() { cat "$SANDBOX/opt/tljh/config/jupyterhub_config.d/50-wlb-lab.py"; }

@test "RESEARCHER_PACKAGE_INSTALL: wartość inna niż deny/mirror jest odrzucana" {
  pkg_mode zgoda
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"RESEARCHER_PACKAGE_INSTALL musi być deny albo mirror, jest 'zgoda' (IMG-004)"* ]]
  [ ! -e "$SANDBOX/etc/pip.conf" ]
  [ ! -e "$SANDBOX/var/lib/wlb/firstboot.done" ]
}

@test "deny bez przełącznika (domyślnie): obraz realizuje zakaz z §24.c" {
  pkg_mode ''
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  [ ! -e "$SANDBOX/etc/pip.conf" ]
  grep -q 'options(repos = character(0))' "$SANDBOX/etc/wlb/r-repos.R"
  grep -qx 'PYTHONNOUSERSITE=1' "$SANDBOX/etc/environment"
  hub_env | grep -q '"PYTHONNOUSERSITE": "1"'
  grep -q 'Tryb: \*\*zakaz\*\*' "$SANDBOX/docs/pakiety.md"
  [[ $output == *"instalacja pakietów przez badacza: deny (IMG-004)"* ]]
}

@test "deny sygnalizuje sprzeczności w lab.env: mirrory ustawione i proxy w EGRESS_ALLOW" {
  pkg_mode deny
  run "$FIRSTBOOT"
  [ "$status" -eq 0 ]
  [[ $output == *"deny, ale lab.env ustawia PYPI_INDEX_URL/CRAN_MIRROR_URL — mirrory będą zignorowane"* ]]
  [[ $output == *"tryb deny, ale proxy pozostaje w EGRESS_ALLOW"* ]]
}

@test "mirror bez adresu mirrora przerywa konfigurację (fail-secure, IMG-004)" {
  pkg_mode mirror
  sed -i '/^PYPI_INDEX_URL=/d' "$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"mirror wymaga kuratorowanego PYPI_INDEX_URL (IMG-004)"* ]]
  [ ! -e "$SANDBOX/etc/pip.conf" ]
  sed -i '/^CRAN_MIRROR_URL=/d' "$SANDBOX/etc/wlb/lab.env"
  echo 'PYPI_INDEX_URL=https://pypi.wlb.local/simple' >>"$SANDBOX/etc/wlb/lab.env"
  run "$FIRSTBOOT"
  [ "$status" -eq 1 ]
  [[ $output == *"mirror wymaga kuratorowanego CRAN_MIRROR_URL (IMG-004)"* ]]
  [ ! -e "$SANDBOX/etc/wlb/r-repos.R" ] || grep -q 'character(0)' "$SANDBOX/etc/wlb/r-repos.R"
}

@test "--force mirror -> deny sprząta po trybie lustrzanym" {
  "$FIRSTBOOT" >/dev/null # mirror z setupu
  [ -e "$SANDBOX/etc/pip.conf" ]
  pkg_mode deny
  run "$FIRSTBOOT" --force
  [ "$status" -eq 0 ]
  [ ! -e "$SANDBOX/etc/pip.conf" ]
  grep -q 'options(repos = character(0))' "$SANDBOX/etc/wlb/r-repos.R"
  grep -qx 'PYTHONNOUSERSITE=1' "$SANDBOX/etc/environment"
  hub_env | grep -q '"PYTHONNOUSERSITE": "1"'
}

@test "--force deny -> mirror przywraca ładowanie ~/.local" {
  pkg_mode deny
  "$FIRSTBOOT" >/dev/null
  grep -qx 'PYTHONNOUSERSITE=1' "$SANDBOX/etc/environment"
  pkg_mode mirror
  run "$FIRSTBOOT" --force
  [ "$status" -eq 0 ]
  grep -qx 'index-url = https://pypi.wlb.local/simple' "$SANDBOX/etc/pip.conf"
  refute grep -q 'PYTHONNOUSERSITE' "$SANDBOX/etc/environment"
  hub_env | grep -q '"https_proxy"'
  refute grep -q 'PYTHONNOUSERSITE' "$SANDBOX/opt/tljh/config/jupyterhub_config.d/50-wlb-lab.py"
}

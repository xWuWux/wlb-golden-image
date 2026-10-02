# shellcheck shell=bash
# Kryteria akceptacji MVP — wykonywane wewnątrz VM testowej jako root (przez tests/acceptance.sh,
# z funkcjami z tests/lib/remote-common.sh).
# Numeracja odpowiada liście kryteriów w specyfikacji.
set -uo pipefail

R1=tester1
R2=tester2
QUEUE=$(sed -n 's/^WLB_EXPORT_QUEUE=//p' /etc/wlb/image.conf)

echo "== Przygotowanie: konta testowe w hubie =="
declare -A PW
for u in $R1 $R2; do PW[$u]=$(/usr/local/sbin/wlb-hub-user "$u"); done

echo "== 1. Logowanie do TLJH i izolacja katalogów domowych =="
expect_ok "Hub odpowiada" curl -sf "$HUB/hub/api"
expect_ok "Logowanie $R1 poprawnym hasłem" test "$(hub_login $R1 "${PW[$R1]}")" = 302
expect_fail "Odmowa przy błędnym haśle" test "$(hub_login $R2 "zle-haslo-123456")" = 302
hub_login $R2 "${PW[$R2]}" >/dev/null
hub_spawn $R1
hub_spawn $R2
expect_ok "Serwer notebooków uruchomiony ($R1)" systemctl is-active --quiet jupyter-$R1
expect_ok "Katalog domowy w /workspace" test "$(getent passwd jupyter-$R1 | cut -d: -f6)" = /workspace/jupyter-$R1
expect_ok "Badacz widzi własny katalog" as $R1 ls /workspace/jupyter-$R1
expect_fail "Badacz nie widzi katalogu innego badacza" as $R1 ls /workspace/jupyter-$R2
expect_fail "Badacz nie listuje /workspace" as $R1 ls /workspace
expect_fail "Badacz nie ma sudo" as $R1 sudo -n true
expect_fail "Badacz nie jest adminem huba" bash -c "id -nG jupyter-$R1 | grep -qw jupyterhub-admins"
expect_fail "Admini huba nie mają sudo (§24.c)" test -e /etc/sudoers.d/jupyterhub-admins

echo "== 2. Notebook Python i notebook R =="
python3 - "/workspace/jupyter-$R1" <<'PY'
import json, sys
notebooks = {
    "test-py": ("python3", "python",
                "import pandas, numpy, scipy, sklearn, matplotlib, seaborn, statsmodels, inspectomop"),
    "test-r": ("ir", "R",
               'for (p in c("DatabaseConnector", "SqlRender", "FeatureExtraction", "CohortGenerator", '
               '"CohortMethod", "PatientLevelPrediction")) library(p, character.only = TRUE)'),
}
for name, (kernel, language, source) in notebooks.items():
    nb = {
        "cells": [{"cell_type": "code", "execution_count": None, "id": "c1",
                   "metadata": {}, "outputs": [], "source": [source]}],
        "metadata": {"kernelspec": {"name": kernel, "display_name": kernel, "language": language}},
        "nbformat": 4, "nbformat_minor": 5,
    }
    with open(f"{sys.argv[1]}/{name}.ipynb", "w") as f:
        json.dump(nb, f)
PY
chown "jupyter-$R1:" /workspace/jupyter-$R1/test-*.ipynb
expect_ok "Notebook Python (pakiety analityczne + inspectomop)" \
  as $R1 bash -c "cd ~ && /opt/tljh/user/bin/jupyter nbconvert --to notebook --execute --output test-py.out.ipynb test-py.ipynb"
expect_ok "Notebook R (pakiety HADES)" \
  as $R1 bash -c "cd ~ && /opt/tljh/user/bin/jupyter nbconvert --to notebook --execute --output test-r.out.ipynb test-r.ipynb"
expect_ok "Sterownik JDBC PostgreSQL" bash -c 'ls /opt/wlb/jdbc/ | grep -qi postgres'

echo "== 3. /data-mart tylko do odczytu =="
expect_ok "Odczyt /data-mart" as $R1 cat /data-mart/wlb-test-cohort.csv
expect_fail "Zapis do /data-mart" as $R1 touch /data-mart/proba
expect_fail "Modyfikacja pliku w /data-mart" as $R1 sh -c 'echo x >> /data-mart/wlb-test-cohort.csv'

echo "== 4. /sluza-in tylko do odczytu =="
expect_ok "Odczyt /sluza-in" as $R1 cat /sluza-in/wlb-test-input.txt
expect_fail "Zapis do /sluza-in" as $R1 touch /sluza-in/proba

echo "== 5. /sluza-out tylko do zapisu =="
expect_ok "Zapis do /sluza-out" as $R1 sh -c 'echo "wynik" > /sluza-out/wynik-test.csv'
sleep 5
expect_fail "Plik w /sluza-out nie jest już widoczny" as $R1 cat /sluza-out/wynik-test.csv
expect_fail "Listowanie /sluza-out zabronione" as $R1 ls /sluza-out
expect_ok "Plik trafił do kolejki zatwierdzenia" bash -c "ls '$QUEUE' | grep -q '_jupyter-tester1_wynik-test.csv\$'"
expect_fail "Badacz nie ma dostępu do kolejki" as $R1 ls "$QUEUE"
# kolejka na dysku roboczym (przeżywa wymianę dysku systemowego, #4)
expect_ok "Kolejka eksportu na dysku roboczym" test "$(findmnt -no TARGET --target "$QUEUE")" = /workspace
# dowiązanie do pliku systemowego: odrzucone, a root nie zmienia praw celu (#29)
passwd_mode=$(stat -c %a /etc/passwd)
as $R1 ln -s /etc/passwd /sluza-out/link-test
for _ in $(seq 1 15); do
  journalctl -t wlb-sluza-out | grep -q 'entry=link-test ' && break
  sleep 1
done
expect_ok "Dowiązanie w /sluza-out odrzucone (#29)" \
  bash -c "journalctl -t wlb-sluza-out | grep -q 'rejected user=jupyter-$R1 entry=link-test reason=unsupported_type'"
expect_ok "Prawa /etc/passwd bez zmian (#29)" test "$(stat -c %a /etc/passwd)" = "$passwd_mode"
expect_fail "W kolejce nie ma dowiązań ani plików specjalnych (#29)" bash -c "find '$QUEUE' ! -type f ! -type d | grep -q ."

echo "== 5b. Identyfikacja IP_CMC i pomoc (#53, #54) =="
expect_ok "Logo na stronie logowania wskazuje /hub/logo (#53)" bash -c "curl -s '$HUB/hub/login' | grep -qE \"src=['\\\"]/hub/logo['\\\"]\""
expect_ok "Nazwa platformy na stronie logowania (#53)" bash -c "curl -s '$HUB/hub/login' | grep -q 'Wirtualne Laboratorium Badawcze IP_CMC'"
expect_ok "Logo to przesłany plik PNG IP_CMC (#53)" \
  bash -c "curl -s '$HUB/hub/logo' | cmp -s - /opt/tljh/config/branding/ipcmc-logo.png"
expect_ok "jupyter-app-launcher zainstalowany (#54)" /opt/tljh/user/bin/python -c "import jupyter_app_launcher"
expect_ok "Kafelek pomocy w konfiguracji Launchera (#54)" \
  bash -c "grep -q 'Pomoc i zgłoszenia' /opt/tljh/user/share/jupyter/jupyter_app_launcher/jp_app_launcher.yaml"
expect_ok "Strona pomocy z kontaktem helpdesku (#54)" \
  bash -c "grep -q 'helpdesk@gumed.edu.pl' /opt/tljh/user/share/jupyter/jupyter_app_launcher/pomoc.md"
echo "== 5a. Blokada pobierania plików na urządzenie badacza (#7, §14, §24.e — środek częściowy) =="
# jako zalogowany badacz: najpierw strona serwera notebooków (logowanie OAuth huba -> ciasteczko
# serwera), bo API serwera bez sesji odpowiada 403 zamiast przekierowania — wtedy 403 niżej
# nie odróżniałoby blokady w Traefiku od braku logowania
dl() { curl -s -o /dev/null -w '%{http_code}' -b "/tmp/wlb-test-$R1.jar" -c "/tmp/wlb-test-$R1.jar" -L "$HUB/user/$R1/$1"; }
as $R1 sh -c 'echo "id,wynik" > ~/pobranie-test.csv'
expect_ok "Sesja w serwerze notebooków (JupyterLab)" test "$(dl lab)" = 200
expect_ok "Pobranie przez /files odrzucone (403)" test "$(dl files/pobranie-test.csv)" = 403
expect_ok "Przycisk Download (/files?download=1) odrzucony (403)" test "$(dl 'files/pobranie-test.csv?download=1')" = 403
expect_ok "Eksport nbconvert odrzucony (403)" test "$(dl 'nbconvert/html/test-py.ipynb?download=true')" = 403
expect_ok "Podgląd /view odrzucony (403)" test "$(dl view/pobranie-test.csv)" = 403
expect_ok "Obejście przez wielkość liter (/FILES) odrzucone" bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -b /tmp/wlb-test-$R1.jar -L '$HUB/user/$R1/FILES/pobranie-test.csv')\" != 200 ]"
# edycja i otwieranie plików działa dalej (JupyterLab korzysta z /api/contents)
expect_ok "Otwieranie plików w JupyterLab działa (/api/contents)" \
  bash -c "curl -s -b /tmp/wlb-test-$R1.jar -c /tmp/wlb-test-$R1.jar -L '$HUB/user/$R1/api/contents/pobranie-test.csv?content=1' | grep -q '\"name\": *\"pobranie-test.csv\"'"
expect_ok "Odmowa pobrania w logu (Traefik access log)" \
  bash -c "journalctl -u traefik -b | grep -q '\"RouterName\":\"wlb-block-download@file\"'"
expect_ok "Przyciski pobierania ukryte w JupyterLab" \
  grep -q '"@jupyterlab/filebrowser-extension:download": true' /opt/tljh/user/etc/jupyter/labconfig/page_config.json

echo "== 6. Brak wyjścia poza allowlistę =="
expect_fail "Bezpośrednie połączenie do internetu" as $R1 curl -s --noproxy '*' --max-time 5 https://example.com
expect_fail "Bezpośrednie połączenie po adresie IP" as $R1 curl -s --noproxy '*' --max-time 5 http://1.1.1.1
expect_ok "Reguły egress nftables załadowane" nft list chain inet wlb researcher_egress
skip "Allowlista proxy (mirror PyPI/CRAN) — wymaga proxy Laboratorium"

echo "== 7. Limity sesji (§9.5) =="
expect_ok "Idle culling 30 min" bash -c 'pgrep -af jupyterhub_idle_culler | grep -q -- "--timeout=1800"'
expect_ok "Twardy limit 12 h (culler --max-age)" bash -c 'pgrep -af jupyterhub_idle_culler | grep -q -- "--max-age=43200"'
expect_ok "Wygaśnięcie ciasteczka i tokenów po 12 h" grep -q 'oauth_token_expires_in = 43200' /opt/tljh/config/jupyterhub_config.d/10-wlb.py
skip "Faktyczne wylogowanie po 12 h — test ręczny (zob. README)"

echo "== 7a. Czas (znaczniki audytu, §21) =="
expect_ok "chrony używa serwerów z NTP_SERVERS" bash -c 'chronyc -n sources | grep -q "10\.0\.2\.2"'
expect_fail "Brak publicznych serwerów NTP" bash -c 'grep -hE "^(pool|server)" /etc/chrony/chrony.conf /etc/chrony/sources.d/* | grep -q ubuntu'

echo "== 8. Logi i audyt =="
expect_ok "Log huba: logowanie badacza" bash -c "journalctl -u jupyterhub | grep -q 'User logged in: $R1'"
expect_ok "Log śluzy: wniosek o eksport" bash -c "journalctl -t wlb-sluza-out | grep -q 'user=jupyter-$R1 .*entry=wynik-test.csv'"
expect_ok "Audyt: zapis do /sluza-out" ausearch --input-logs -k wlb_sluza_out -ui "$(id -u jupyter-$R1)"
expect_ok "Audyt: odczyt /sluza-in" ausearch --input-logs -k wlb_sluza_in -ui "$(id -u jupyter-$R1)"
expect_ok "Audyt: odmowa dostępu" ausearch --input-logs -k wlb_access_denied -ui "$(id -u jupyter-$R1)"
expect_ok "Audyt: polecenia badacza (execve)" ausearch --input-logs -k wlb_exec -ui "$(id -u jupyter-$R1)"
expect_ok "Reguły audytu zablokowane (-e 2)" bash -c 'auditctl -s | grep -q "^enabled 2"'
# #44: badacz podszywa się pod śluzę (ten sam tag i treść). Dociera do SIEM, ale z jego UID
# z jądra — ci/observability_contract.py verify-log --expect-untrusted musi go odrzucić
as $R1 logger -t wlb-sluza-out -p authpriv.notice -- "export_request user=jupyter-$R2 uid=0 \
entry=podrobiony-44.csv sha256=$(printf '%064d' 0) queued_as=20260101T000000Z_jupyter-${R2}_podrobiony-44.csv"
# pola zaufane nie mogą powodować odmów AppArmor — każda to zdarzenie audytu, które wraca do rsyslog
# (pętla zalewająca audyt, zob. rola logging)
# odmowy AppArmor przy działającym auditd trafiają do audytu, nie do dziennika jądra (journalctl -k)
expect_fail "rsyslog bez odmów AppArmor (#44, #6)" \
  bash -c "ausearch --input-logs -m AVC </dev/null 2>/dev/null | grep -q 'profile=\"rsyslogd\"'"
expect_fail "Jądro nie gubi zdarzeń audytu (backlog)" bash -c "journalctl -k -b | grep -q 'audit: backlog limit exceeded'"
expect_ok "Wpis podrobiony przez badacza ma w journald jego UID (#44)" \
  bash -c "journalctl -t wlb-sluza-out _UID=$(id -u jupyter-$R1) -o cat | grep -q podrobiony-44.csv"
if grep -q '^SIEM_HOST=.' /etc/wlb/lab.env; then
  expect_ok "Przekazywanie do SIEM skonfigurowane" test -s /etc/rsyslog.d/60-wlb-siem.conf
  # rsyslogd -N1 nie wykrywa braku modułu TLS — ładowany dopiero przy pierwszym połączeniu (#6)
  expect_ok "Moduł TLS rsyslog zainstalowany (lmnsd_gtls, #6)" bash -c 'compgen -G "/usr/lib/*/rsyslog/lmnsd_gtls.so"'
  expect_ok "SIEM po TLS z weryfikacją nazwy serwera (#6)" \
    grep -q 'StreamDriverAuthMode="x509/name"' /etc/rsyslog.d/60-wlb-siem.conf
  expect_fail "rsyslog bez błędów TLS (moduł, nazwa i zaufanie certyfikatu, #6)" \
    bash -c "journalctl -u rsyslog -b | grep -qE 'could not load module|lmnsd_gtls.*error|error reading certificate|not permitted to talk|peer name not authorized|not trusted|certificate.*(invalid|expired|revoked)'"
else
  skip "Log centralny (SIEM) — brak SIEM_HOST w teście lokalnym"
fi

summary

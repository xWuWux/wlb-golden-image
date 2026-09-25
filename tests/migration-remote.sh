# shellcheck shell=bash
# Część testu migracji wykonywana w VM (przez tests/migration.sh, z remote-common.sh).
#   prepare              -> konto badacza, dane w katalogu domowym; wypisuje "UID HASŁO HASŁO_ADMINA"
#   verify UID HASŁO HASŁO_ADMINA
set -uo pipefail
USER_NAME=migrant

case $1 in
  prepare)
    password=$(/usr/local/sbin/wlb-hub-user "$USER_NAME")
    [[ $(hub_login "$USER_NAME" "$password") == 302 ]] || exit 1
    hub_spawn "$USER_NAME" || exit 1
    as "$USER_NAME" sh -c 'mkdir -p ~/wyniki && echo migracja-ok > ~/wyniki/dane.csv' || exit 1
    echo "$(id -u "jupyter-$USER_NAME") $password $(cat /root/wlb-hub-admin-initial-password)"
    ;;
  verify)
    uid=$2 password=$3 admin_password=$4
    home=/workspace/jupyter-$USER_NAME
    expect_ok "Konto systemowe odtworzone z tym samym UID" test "$(id -u "jupyter-$USER_NAME")" = "$uid"
    expect_ok "Katalog domowy na miejscu" test "$(getent passwd "jupyter-$USER_NAME" | cut -d: -f6)" = "$home"
    expect_ok "Badacz czyta swoje pliki" test "$(as "$USER_NAME" cat "$home/wyniki/dane.csv")" = migracja-ok
    expect_ok "Badacz zapisuje w swoim katalogu" as "$USER_NAME" touch "$home/po-migracji"
    expect_ok "Logowanie badacza starym hasłem (baza huba na dysku roboczym)" \
      test "$(hub_login "$USER_NAME" "$password")" = 302
    expect_ok "Serwer notebooków startuje po migracji" hub_spawn "$USER_NAME"
    expect_ok "Administrator Klienta loguje się starym hasłem" \
      test "$(hub_login admin-klienta "$admin_password")" = 302
    expect_fail "Nowa VM nie wygenerowała nowego hasła admina" test -s /root/wlb-hub-admin-initial-password
    expect_ok "Hub działa po ewentualnej aktualizacji schematu bazy" curl -sf -o /dev/null "$HUB/hub/api"
    summary
    ;;
  *)
    echo "użycie: prepare | verify UID HASŁO HASŁO_ADMINA" >&2
    exit 2
    ;;
esac

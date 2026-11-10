#!/usr/bin/env bats
# Testy wlb-monitoring (#22) — włączanie/wyłączanie ekspozycji metryk VM.
# Narzędzie działa na jądrze (nft) i systemd, więc w piaskownicy atrapujemy nft/systemctl/ss,
# a stan łańcucha i nasłuchu trzymamy w plikach, które test może ustawić.

load helpers

MONITORING="$REPO_ROOT/ansible/roles/monitoring/files/wlb-monitoring"

setup() {
  SANDBOX="$BATS_TEST_TMPDIR/root"
  STUBS="$BATS_TEST_TMPDIR/stubs"
  CALLS="$BATS_TEST_TMPDIR/calls.log"
  DROPIN_DIR="$SANDBOX/etc/systemd/system/prometheus-node-exporter.service.d"
  mkdir -p "$DROPIN_DIR" "$SANDBOX/etc/nftables.d" "$STUBS"
  : >"$CALLS"
  export CALLS SANDBOX
  # Plik eksportera z obrazu (rola monitoring) — źródło flag, które przenosimy do override'u.
  cat >"$DROPIN_DIR/10-wlb.conf" <<'CONF'
[Service]
Environment="WLB_NODE_EXPORTER_FLAGS=--collector.textfile.directory=/var/lib/wlb-node-exporter --no-collector.systemd"
ExecStart=
ExecStart=/usr/bin/prometheus-node-exporter --web.listen-address=127.0.0.1:9100 $WLB_NODE_EXPORTER_FLAGS
CONF
  # Stan jądra: plik z regułami łańcucha monitoring_in (pusty = łańcuch istnieje, brak pliku = brak łańcucha).
  : >"$SANDBOX/nft-chain"
  # Nasłuch eksportera widziany przez ss; testy zmieniają ten plik.
  echo '127.0.0.1:9100' >"$SANDBOX/ss.out"
  # Stan usług; brak pliku = aktywna.
  : >"$SANDBOX/inactive"

  cat >"$STUBS/nft" <<EOF
#!/usr/bin/env bash
echo "nft \$*" >>"\$CALLS"
chain="$SANDBOX/nft-chain"
case "\$1" in
  list)
    [[ -f \$chain ]] || exit 1
    printf 'table inet wlb {\n\tchain monitoring_in {\n'
    sed 's/^/\t\t/' "\$chain"
    printf '\t}\n}\n'
    exit 0
    ;;
  -f)
    if [[ \${2:-} == - ]]; then input=\$(cat); else input=\$(cat "\${2:?}"); fi
    while IFS= read -r line; do
      case \$line in
        "flush chain"*) : >"\$chain" ;;
        "add rule"*)
          rule=\${line#add rule inet wlb monitoring_in }
          echo "\${rule/\\/32 / }" >>"\$chain"
          ;;
      esac
    done <<<"\$input"
    exit 0
    ;;
  -c) exit 0 ;;
esac
exit 1
EOF
  cat >"$STUBS/systemctl" <<EOF
#!/usr/bin/env bash
echo "systemctl \$*" >>"\$CALLS"
svc=\${!#}
case "\$1" in
  daemon-reload | reset-failed) exit 0 ;;
  is-active) grep -qx "\$svc" "$SANDBOX/inactive" && exit 3; exit 0 ;;
  restart) [[ -f "$SANDBOX/restart.fail" ]] && exit 1; exit 0 ;;
esac
exit 1
EOF
  cat >"$STUBS/ss" <<EOF
#!/usr/bin/env bash
echo "ss \$*" >>"\$CALLS"
while read -r addr; do printf 'LISTEN 0 4096 %s 0.0.0.0:*\n' "\$addr"; done <"$SANDBOX/ss.out"
EOF
  printf '#!/bin/sh\nexit 0\n' >"$STUBS/logger"
  chmod +x "$STUBS"/*
  export WLB_NFT="$STUBS/nft" WLB_SYSTEMCTL="$STUBS/systemctl" WLB_SS="$STUBS/ss"
  export WLB_NFT_DIR="$SANDBOX/etc/nftables.d" WLB_NODE_EXPORTER_DROPIN_DIR="$DROPIN_DIR"
  export WLB_MONITORING_SELF="$MONITORING" PATH="$STUBS:$PATH"
}

include_file() { cat "$SANDBOX/etc/nftables.d/50-wlb-monitoring.nft"; }
monitoring_dropin() { cat "$DROPIN_DIR/20-wlb-monitoring.conf"; }
chain_rules() { cat "$SANDBOX/nft-chain"; }

# --- apply ------------------------------------------------------------------------------------

@test "#22 apply: reguła w jądrze, plik na dysku, override eksportera i weryfikacja nasłuchu" {
  echo '0.0.0.0:9100' >"$SANDBOX/ss.out" # po restarcie eksporter słucha poza pętlą
  run "$MONITORING" apply 172.16.25.58/32
  [ "$status" -eq 0 ]
  # reguła w jądrze (nft normalizuje /32 do nagiego adresu)
  chain_rules | grep -qx 'ip saddr 172.16.25.58 tcp dport 9100 accept'
  # plik utrwalający regułę (include z /etc/nftables.conf)
  include_file | grep -qx 'add rule inet wlb monitoring_in ip saddr 172.16.25.58/32 tcp dport 9100 accept'
  # override ExecStart: flagi kolektorów z obrazu, adres nasłuchu podmieniony, guard przed startem
  # shellcheck disable=SC2016 # $WLB_NODE_EXPORTER_FLAGS rozwija systemd, nie powłoka
  monitoring_dropin | grep -qxF 'ExecStart=/usr/bin/prometheus-node-exporter --web.listen-address=0.0.0.0:9100 $WLB_NODE_EXPORTER_FLAGS'
  # flagi kolektorów zostają jedną definicją w pliku obrazu (Environment), override ich nie kopiuje
  refute grep -q 'Environment=' "$DROPIN_DIR/20-wlb-monitoring.conf"
  monitoring_dropin | grep -qx 'ExecStart='
  monitoring_dropin | grep -qx "ExecStartPre=+${MONITORING} guard"
  monitoring_dropin | grep -qx 'After=nftables.service'
  monitoring_dropin | grep -qx 'Wants=nftables.service'
  monitoring_dropin | grep -qx 'PartOf=nftables.service'
  refute grep -q '127.0.0.1:9100' "$DROPIN_DIR/20-wlb-monitoring.conf"
  calls | grep -qx 'systemctl daemon-reload'
  calls | grep -qx 'systemctl restart prometheus-node-exporter.service'
  # licznik startów zerowany przed restartem (apply + cofnięcie + disable nie trafiają w start-limit)
  [ "$(grep -n 'reset-failed prometheus-node-exporter.service' "$CALLS" | head -1 | cut -d: -f1)" -lt \
    "$(grep -n 'restart prometheus-node-exporter.service' "$CALLS" | head -1 | cut -d: -f1)" ]
  [[ $output == *"nasłuch na 0.0.0.0:9100, dostęp tylko z 172.16.25.58/32"* ]]
}

@test "#22 apply: niekanoniczne wartości są odrzucane i nic nie zmieniają" {
  local value
  for value in 0.0.0.0/1 192.0.2.58/24 010.000.000.001/32 172.16.25.58 172.16.25.0/33 \
    0.0.0.0/32 172.16.25.58/32,10.0.0.0/8 '' 256.1.1.1/32; do
    : >"$CALLS"
    run "$MONITORING" apply "$value"
    [ "$status" -ne 0 ]
    [[ $output == *"kanonicznego adresu IPv4 z prefiksem /32"* || $output == *"0.0.0.0 nie identyfikuje"* ]]
    refute called nft
    refute called 'systemctl restart'
    [ ! -e "$SANDBOX/etc/nftables.d/50-wlb-monitoring.nft" ]
    [ ! -e "$DROPIN_DIR/20-wlb-monitoring.conf" ]
  done
}

@test "#22 apply: brak pliku eksportera z obrazu przerywa bez zmian w jądrze" {
  rm "$DROPIN_DIR/10-wlb.conf"
  run "$MONITORING" apply 172.16.25.58/32
  [ "$status" -ne 0 ]
  [[ $output == *"rola monitoring nie zainstalowała eksportera"* ]]
  refute called 'systemctl restart'
}

@test "#22 apply: plik eksportera z nieoczekiwanym adresem nasłuchu jest odrzucany" {
  cat >"$DROPIN_DIR/10-wlb.conf" <<'CONF'
[Service]
ExecStart=/usr/bin/prometheus-node-exporter --web.listen-address=0.0.0.0:9100
CONF
  run "$MONITORING" apply 172.16.25.58/32
  [ "$status" -ne 0 ]
  [[ $output == *"oczekiwano --web.listen-address=127.0.0.1:9100"* ]]
  refute called 'systemctl restart'
}

@test "#22 apply: gdy nasłuch nie wstaje na 0.0.0.0, ekspozycja jest cofana" {
  echo '127.0.0.1:9100' >"$SANDBOX/ss.out" # eksporter nie wystartował poza pętlą
  run "$MONITORING" apply 172.16.25.58/32
  [ "$status" -ne 0 ]
  [[ $output == *"cofnięto ekspozycję"* ]]
  [ ! -e "$SANDBOX/etc/nftables.d/50-wlb-monitoring.nft" ]
  [ ! -e "$DROPIN_DIR/20-wlb-monitoring.conf" ]
  [ -z "$(chain_rules)" ]
}

@test "#22 apply: nieudany restart eksportera też cofa ekspozycję" {
  touch "$SANDBOX/restart.fail"
  run "$MONITORING" apply 172.16.25.58/32
  [ "$status" -ne 0 ]
  [[ $output == *"cofnięto ekspozycję"* ]]
  [ ! -e "$SANDBOX/etc/nftables.d/50-wlb-monitoring.nft" ]
  [ ! -e "$DROPIN_DIR/20-wlb-monitoring.conf" ]
  [ -z "$(chain_rules)" ]
}

# --- disable ----------------------------------------------------------------------------------

@test "#22 disable: zamyka regułę, usuwa pliki i wraca na pętlę" {
  echo '0.0.0.0:9100' >"$SANDBOX/ss.out"
  "$MONITORING" apply 172.16.25.58/32 >/dev/null
  echo '127.0.0.1:9100' >"$SANDBOX/ss.out"
  : >"$CALLS"
  run "$MONITORING" disable
  [ "$status" -eq 0 ]
  [ -z "$(chain_rules)" ]
  [ ! -e "$SANDBOX/etc/nftables.d/50-wlb-monitoring.nft" ]
  [ ! -e "$DROPIN_DIR/20-wlb-monitoring.conf" ]
  calls | grep -qx 'systemctl restart prometheus-node-exporter.service'
  [[ $output == *"nasłuch tylko na 127.0.0.1:9100"* ]]
}

@test "#22 disable: naprawia stan także wtedy, gdy plik override już zniknął" {
  # przerwany poprzedni przebieg: plik usunięty, proces nadal na 0.0.0.0
  echo 'ip saddr 172.16.25.58 tcp dport 9100 accept' >"$SANDBOX/nft-chain"
  echo '0.0.0.0:9100' >"$SANDBOX/ss.out"
  : >"$CALLS"
  run "$MONITORING" disable
  [ "$status" -ne 0 ]
  [[ $output == *"nadal słucha poza pętlą"* ]]
  # ponowienie po naprawie procesu kończy się sukcesem
  echo '127.0.0.1:9100' >"$SANDBOX/ss.out"
  run "$MONITORING" disable
  [ "$status" -eq 0 ]
  [ -z "$(chain_rules)" ]
}

@test "#22 disable: idempotentne, gdy ekspozycja nigdy nie była włączona" {
  run "$MONITORING" disable
  [ "$status" -eq 0 ]
  calls | grep -qx 'systemctl restart prometheus-node-exporter.service'
  [ -z "$(chain_rules)" ]
}

@test "#22 disable: brak łańcucha monitoring_in (starszy ruleset) nie wywraca wyłączania" {
  rm "$SANDBOX/nft-chain"
  run "$MONITORING" disable
  [ "$status" -eq 0 ]
  refute called 'nft -f'
}

@test "#22 disable: nieaktywny eksporter to niepotwierdzony stan" {
  "$MONITORING" apply 172.16.25.58/32 >/dev/null 2>&1 || true
  echo 'prometheus-node-exporter.service' >"$SANDBOX/inactive"
  run "$MONITORING" disable
  [ "$status" -ne 0 ]
  [[ $output == *"eksporter nie działa po restarcie"* ]]
}

# --- guard (ExecStartPre) ---------------------------------------------------------------------

@test "#22 guard: przepuszcza start tylko przy aktywnej zaporze i utrwalonej regule" {
  echo '0.0.0.0:9100' >"$SANDBOX/ss.out"
  "$MONITORING" apply 172.16.25.58/32 >/dev/null
  run "$MONITORING" guard
  [ "$status" -eq 0 ]
}

@test "#22 guard: brak pliku reguły blokuje nasłuch poza pętlą" {
  echo '0.0.0.0:9100' >"$SANDBOX/ss.out"
  "$MONITORING" apply 172.16.25.58/32 >/dev/null
  rm "$SANDBOX/etc/nftables.d/50-wlb-monitoring.nft"
  run "$MONITORING" guard
  [ "$status" -ne 0 ]
  [[ $output == *"brak utrwalonej reguły"* ]]
}

@test "#22 guard: wyczyszczona reguła w jądrze blokuje nasłuch poza pętlą" {
  echo '0.0.0.0:9100' >"$SANDBOX/ss.out"
  "$MONITORING" apply 172.16.25.58/32 >/dev/null
  : >"$SANDBOX/nft-chain"
  run "$MONITORING" guard
  [ "$status" -ne 0 ]
  [[ $output == *"brak aktywnej reguły portu 9100"* ]]
}

@test "#22 guard: nieaktywna zapora blokuje nasłuch poza pętlą" {
  echo '0.0.0.0:9100' >"$SANDBOX/ss.out"
  "$MONITORING" apply 172.16.25.58/32 >/dev/null
  echo 'nftables.service' >"$SANDBOX/inactive"
  run "$MONITORING" guard
  [ "$status" -ne 0 ]
  [[ $output == *"zapora (nftables.service) nieaktywna"* ]]
}

# --- status i użycie --------------------------------------------------------------------------

@test "#22 status: pokazuje plik reguły, override i nasłuch" {
  echo '0.0.0.0:9100' >"$SANDBOX/ss.out"
  "$MONITORING" apply 172.16.25.58/32 >/dev/null
  run "$MONITORING" status
  [ "$status" -eq 0 ]
  [[ $output == *"plik reguły:"* ]]
  [[ $output == *"ip saddr 172.16.25.58 tcp dport 9100 accept"* ]]
  [[ $output == *"0.0.0.0:9100"* ]]
}

@test "#22 użycie: nieznana komenda kończy się błędem z opisem" {
  run "$MONITORING" enable
  [ "$status" -ne 0 ]
  [[ $output == *"użycie: wlb-monitoring {apply ADRES/32 | disable | status | guard}"* ]]
}

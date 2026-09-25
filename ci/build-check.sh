#!/usr/bin/env bash
# Stage 2: build test — czy definicja obrazu i wszystko, co generujemy, jest poprawne składniowo.
# Bez budowania obrazu: Packer validate, Ansible syntax-check, render szablonów i kompilacja wyników,
# walidacja cloud-init i konfiguracji generowanej przez wlb-firstboot.
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
require packer ansible-playbook python3
OUT=build/rendered
mkdir -p build "$OUT"

# Packer potrzebuje klucza maszyny budującej (tylko do walidacji)
[[ -f build/packer_ed25519 ]] || ssh-keygen -q -t ed25519 -N '' -C wlb-ci -f build/packer_ed25519

packer_validate() {
  packer init packer/ >/dev/null
  packer validate -var image_version=0.0.0-ci -var image_date=20000101 packer/
}

render_templates() {
  ansible-playbook -i localhost, ci/render-templates.yml >/dev/null
  python3 -m py_compile "$OUT/10-wlb.py"
  python3 -c 'import sys, yaml; yaml.safe_load(open(sys.argv[1]))' "$OUT/config.yaml"
  bash -n "$OUT/wlb-shell-audit.sh"
  # reguły audytu: każda linia to komentarz albo -w/-a z kluczem -k
  ! grep -vE '^\s*(#|$|-w .+ -k wlb_|-a always,exit .+ -k wlb_)' "$OUT/50-wlb.rules"
}

r_parse() {
  if ! command -v Rscript >/dev/null; then
    echo "Rscript niedostępny — pomijam (w CI instalowany)"
    return 0
  fi
  Rscript -e 'invisible(parse("envs/r/install-r-env.R")); invisible(parse("build/rendered/Rprofile.site"))'
}

json_yaml_files() {
  python3 -c 'import json; json.load(open("envs/r/renv.lock"))'
  python3 - <<'PY'
import yaml
for f in ["envs/python/environment.yml", "ci/license-policy.yml", "ansible/group_vars/all.yml"]:
    yaml.safe_load(open(f))
PY
}

cloud_init_schema() {
  if ! command -v cloud-init >/dev/null; then
    echo "cloud-init niedostępny — pomijam"
    return 0
  fi
  local tmp
  tmp=$(mktemp -d)
  sed "s|__SSH_PUBKEY__|$(cat build/packer_ed25519.pub)|" tests/cloud-init/user-data.yaml >"$tmp/test-user-data.yaml"
  sed "s|\${ssh_public_key}|$(cat build/packer_ed25519.pub)|" packer/cloud-init/user-data.pkrtpl.yaml >"$tmp/packer-user-data.yaml"
  local f rc=0
  for f in cloud-init/lab-user-data.example.yaml "$tmp/test-user-data.yaml" "$tmp/packer-user-data.yaml"; do
    cloud-init schema --config-file "$f" || rc=1
  done
  rm -rf "$tmp"
  return $rc
}

# wlb-firstboot w piaskownicy na przykładowym lab.env; wynik (nftables, rsyslog, config huba) sprawdzany
# prawdziwymi narzędziami, jeśli są dostępne (nft -c wymaga uprawnień — w CI przez sudo)
firstboot_output() {
  local sb stubs
  sb=$(mktemp -d)
  stubs="$sb/stubs"
  mkdir -p "$sb/root/etc/wlb" "$stubs"
  cat >"$sb/root/etc/wlb/image.conf" <<'EOF'
WLB_RESEARCHER_UID_MIN=10000
WLB_RESEARCHER_UID_MAX=59999
WLB_RESEARCHER_GROUP=jupyterhub-users
EOF
  python3 - "$sb/root/etc/wlb/directories.conf" <<'PY'
import sys, yaml
dirs = yaml.safe_load(open("ansible/group_vars/all.yml"))["wlb_directories"]
open(sys.argv[1], "w").write("".join(f"{d['path']} {d['owner']} {d['group']} {d['mode']}\n" for d in dirs))
PY
  cp cloud-init/lab.env.example "$sb/root/etc/wlb/lab.env"
  local cmd
  for cmd in logger systemctl nft rsyslogd chown chmod curl groupadd useradd sleep tljh-config; do
    printf '#!/bin/sh\nexit 0\n' >"$stubs/$cmd"
  done
  printf '#!/bin/sh\nexit 2\n' >"$stubs/getent"
  printf '#!/bin/sh\necho haslo-testowe-123\n' >"$stubs/wlb-hub-user"
  chmod +x "$stubs"/*
  PATH="$stubs:$PATH" WLB_ROOT="$sb/root" WLB_TLJH_CONFIG="$stubs/tljh-config" \
    WLB_HUB_USER_TOOL="$stubs/wlb-hub-user" ansible/roles/lab_config/files/wlb-firstboot >/dev/null
  cp "$sb/root/etc/nftables.conf" "$sb/root/etc/rsyslog.d/60-wlb-siem.conf" \
    "$sb/root/opt/tljh/config/jupyterhub_config.d/50-wlb-lab.py" "$OUT/"
  rm -rf "$sb"

  python3 -m py_compile "$OUT/50-wlb-lab.py"
  if command -v nft >/dev/null && sudo -n true 2>/dev/null; then
    sudo nft -c -f "$OUT/nftables.conf"
  else
    echo "nft -c wymaga sudo — pomijam (w CI wykonywane)"
  fi
  if command -v rsyslogd >/dev/null && sudo -n true 2>/dev/null; then
    # AppArmor (Ubuntu) pozwala rsyslogd czytać konfigurację tylko z /etc/rsyslog* — sprawdzamy tam
    local check=/etc/rsyslog.d/zz-wlb-ci-check.conf rc=0
    sudo cp "$OUT/60-wlb-siem.conf" "$check"
    sudo rsyslogd -N1 -f "$check" || rc=$?
    sudo rm -f "$check"
    return $rc
  elif command -v rsyslogd >/dev/null; then
    rsyslogd -N1 -f "$OUT/60-wlb-siem.conf"
  else
    echo "rsyslogd niedostępny — pomijam"
  fi
}

run_check "Packer validate" packer_validate
run_check "Ansible syntax-check" bash -c 'cd ansible && ansible-playbook -i localhost, --syntax-check site.yml'
run_check "Szablony ról: render i kompilacja" render_templates
run_check "R: parsowanie skryptów" r_parse
run_check "JSON/YAML: pliki środowisk i polityk" json_yaml_files
run_check "cloud-init: walidacja schematu user-data" cloud_init_schema
run_check "wlb-firstboot: konfiguracja wygenerowana z lab.env.example" firstboot_output
finish

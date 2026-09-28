#!/usr/bin/env bash
# Instaluje przypięte wersje narzędzi CI do $TOOLS_DIR (domyślnie .tools/) — bez sudo.
#
#   ci/install-tools.sh [lint] [unit] [security]   # bez argumentów: wszystko
#
# kcov (pokrycie testów powłoki) instaluje osobno CI (apt) — lokalnie: sudo apt install kcov.
set -euo pipefail
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"

SHELLCHECK_VERSION=0.11.0
SHELLCHECK_SHA256=8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198
SHFMT_VERSION=3.14.1
SHFMT_SHA256=76e77641faa025814b77f153b29796b8e6fa2fca03e0c76a691608b86c7ea7bf
GITLEAKS_VERSION=8.30.1
GITLEAKS_SHA256=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
OSV_SCANNER_VERSION=2.6.0
OSV_SCANNER_SHA256=ca69b3d3cd08f889a49dc0a383122f71cc528b83803671df5fd874d97485b108
ACTIONLINT_VERSION=1.7.12
ACTIONLINT_SHA256=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8
BATS_VERSION=1.13.0
PACKER_VERSION=1.16.1
PACKER_SHA256=af38a9e93e4ed1b9ca68206ae969c64c300c82a3dde46a780dfa629f0867f651

mkdir -p "$TOOLS_DIR/bin"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# download URL SHA256 PLIK — ponawia także przy przejściowych błędach serwera (np. HTTP 504)
download() {
  curl -fsSL --retry 5 --retry-all-errors --retry-delay 5 -o "$3" "$1"
  echo "$2  $3" | sha256sum -c --quiet - || {
    echo "Suma kontrolna się nie zgadza: $1"
    exit 1
  }
}

venv() { # venv NAZWA PLIK_WYMAGAŃ
  [[ -x $TOOLS_DIR/$1/bin/python ]] || python3 -m venv "$TOOLS_DIR/$1"
  "$TOOLS_DIR/$1/bin/pip" install -q --upgrade pip
  "$TOOLS_DIR/$1/bin/pip" install -q -r "$2"
}

install_lint() {
  if [[ ! -x $TOOLS_DIR/bin/shellcheck ]]; then
    download "https://github.com/koalaman/shellcheck/releases/download/v$SHELLCHECK_VERSION/shellcheck-v$SHELLCHECK_VERSION.linux.x86_64.tar.xz" \
      "$SHELLCHECK_SHA256" "$TMP/shellcheck.tar.xz"
    tar -xJf "$TMP/shellcheck.tar.xz" -C "$TOOLS_DIR/bin" --strip-components=1 "shellcheck-v$SHELLCHECK_VERSION/shellcheck"
  fi
  if [[ ! -x $TOOLS_DIR/bin/shfmt ]]; then
    download "https://github.com/mvdan/sh/releases/download/v$SHFMT_VERSION/shfmt_v${SHFMT_VERSION}_linux_amd64" \
      "$SHFMT_SHA256" "$TOOLS_DIR/bin/shfmt"
    chmod +x "$TOOLS_DIR/bin/shfmt"
  fi
  if [[ ! -x $TOOLS_DIR/bin/gitleaks ]]; then
    download "https://github.com/gitleaks/gitleaks/releases/download/v$GITLEAKS_VERSION/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
      "$GITLEAKS_SHA256" "$TMP/gitleaks.tar.gz"
    tar -xzf "$TMP/gitleaks.tar.gz" -C "$TOOLS_DIR/bin" gitleaks
  fi
  if [[ ! -x $TOOLS_DIR/bin/actionlint ]]; then
    download "https://github.com/rhysd/actionlint/releases/download/v$ACTIONLINT_VERSION/actionlint_${ACTIONLINT_VERSION}_linux_amd64.tar.gz" \
      "$ACTIONLINT_SHA256" "$TMP/actionlint.tar.gz"
    tar -xzf "$TMP/actionlint.tar.gz" -C "$TOOLS_DIR/bin" actionlint
  fi
  if [[ ! -x $TOOLS_DIR/bin/packer ]]; then
    download "https://releases.hashicorp.com/packer/$PACKER_VERSION/packer_${PACKER_VERSION}_linux_amd64.zip" \
      "$PACKER_SHA256" "$TMP/packer.zip"
    python3 -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extract("packer", sys.argv[2])' "$TMP/packer.zip" "$TOOLS_DIR/bin"
    chmod +x "$TOOLS_DIR/bin/packer"
  fi
  venv venv-lint ci/requirements-lint.txt
}

install_unit() {
  [[ -x $TOOLS_DIR/bats/bin/bats ]] ||
    git clone -q --depth 1 --branch "v$BATS_VERSION" https://github.com/bats-core/bats-core.git "$TOOLS_DIR/bats"
  venv venv-unit ci/requirements-unit.txt
}

install_security() {
  if [[ ! -x $TOOLS_DIR/bin/osv-scanner ]]; then
    download "https://github.com/google/osv-scanner/releases/download/v$OSV_SCANNER_VERSION/osv-scanner_linux_amd64" \
      "$OSV_SCANNER_SHA256" "$TOOLS_DIR/bin/osv-scanner"
    chmod +x "$TOOLS_DIR/bin/osv-scanner"
  fi
  venv venv-security ci/requirements-security.txt
}

groups=("$@")
((${#groups[@]})) || groups=(lint unit security)
for g in "${groups[@]}"; do
  case $g in
    lint | unit | security) "install_$g" ;;
    *)
      echo "Nieznana grupa: $g (lint | unit | security)"
      exit 2
      ;;
  esac
  echo "Zainstalowano: $g"
done

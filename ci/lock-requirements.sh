#!/usr/bin/env bash
# Regeneruje zahashowane locki CI (ci/requirements-*.txt) z plików ci/requirements-*.in dla wersji
# Pythona używanej w CI (3.12). Instalacja w CI (ci/install-tools.sh) używa --require-hashes: każda
# niezgodna suma pobranego pakietu = twardy błąd, deterministyczny i audytowalny sygnał supply-chain
# (#162 / IMG-008 pkt 5b). Hashe obejmują wszystkie dystrybucje danej wersji (wheels + sdist), więc
# lock działa niezależnie od platformy runnera.
#
# Edytuj piny TYLKO w ci/requirements-*.in (top-level), potem uruchom ten skrypt i zacommituj .txt.
#   ci/lock-requirements.sh
set -euo pipefail

PY=3.12
command -v uv >/dev/null 2>&1 || {
  echo "Wymagane 'uv' (resolver domknięcia dla Pythona $PY bez lokalnego interpretera):" >&2
  echo "  pipx install uv   albo   python3 -m pip install uv" >&2
  exit 1
}

cd "$(dirname "$0")/.."
for name in lint security unit; do
  in="ci/requirements-$name.in"
  out="ci/requirements-$name.txt"
  tmp=$(mktemp)
  uv pip compile "$in" --python-version "$PY" --generate-hashes --no-header --quiet -o "$tmp"
  {
    printf '# WYGENEROWANE przez ci/lock-requirements.sh — NIE edytuj ręcznie (piny w %s).\n' "$in"
    printf '# Lock z hashami dla Pythona %s; instalacja w CI z --require-hashes (#162/IMG-008 5b).\n' "$PY"
    cat "$tmp"
  } >"$out"
  rm -f "$tmp"
  echo "zregenerowano $out ($(grep -cE '^[a-zA-Z0-9]' "$out") pakietów)"
done
echo "OK — locki CI zregenerowane dla Pythona $PY"

#!/usr/bin/env bats
# Testy proweniencji i walidacji wydania (#12).

load helpers

# Bez argumentów; RELEASE_REPO to ścieżka do czystego repozytorium fixture.
# Kopiujemy prawdziwe skrypty, aby zachować bramki produkcyjnego wydania.
setup_release_repo() {
  RELEASE_REPO="$BATS_TEST_TMPDIR/release-repo"
  mkdir -p "$RELEASE_REPO/ci"
  cp "$REPO_ROOT/ci/"{release.sh,common.sh,image_identity.py,e2e_release_gate.py,release_provenance.py,e2e-fixture-paths.txt} "$RELEASE_REPO/ci/"
  git -C "$RELEASE_REPO" init -q
  git -C "$RELEASE_REPO" config user.email t@example.com
  git -C "$RELEASE_REPO" config user.name tester
  git -C "$RELEASE_REPO" add ci
  git -C "$RELEASE_REPO" -c commit.gpgsign=false commit -qm fixture
  git -C "$RELEASE_REPO" tag v9.9.9
}

# write_e2e_provenance ARTYFAKTY OBRAZ [COMMIT] [DATA] [WERSJA] — spójne metadane, manifest
# Packera i suma qcow2. Od #277 release.sh wymaga tego powiązania przed bramką E2E.
write_e2e_provenance() {
  local art=$1 out=$2
  local commit=${3:-$(git -C "$RELEASE_REPO" rev-parse HEAD)}
  local date=${4:-20260101} version=${5:-9.9.9}
  local full="wlb-general-${version}-${date}"
  local size digest
  mkdir -p "$art" "$out"
  printf 'WLB_IMAGE_VERSION=%s\nWLB_GIT_COMMIT=%s\nWLB_GIT_DIRTY=0\nWLB_IMAGE_NAME=wlb-general\nWLB_IMAGE_DATE=%s\nWLB_BUILD_RUN=local\n' \
    "$version" "$commit" "$date" >"$art/image-release"
  printf 'Package: acl\nVersion: 2.3.1\n\n' >"$art/dpkg-status"
  : >"$out/${full}.qcow2"
  size=$(stat -c %s "$out/${full}.qcow2")
  digest=$(sha256sum "$out/${full}.qcow2" | awk '{print $1}')
  printf '%s  %s\n' "$digest" "${full}.qcow2" >"$out/${full}.qcow2.sha256"
  cat >"$out/packer-manifest.json" <<EOF
{"builds":[{"name":"wlb","builder_type":"qemu","files":[{"name":"${full}.qcow2","size":${size}}],"artifact_id":"VM","custom_data":{"image_version":"${version}","image_date":"${date}","git_commit":"${commit}","git_dirty":"0","build_run":"local"}}],"last_run_uuid":"test"}
EOF
}

# Repozytorium wydania z podstawionymi: tożsamością OS (bramka E2E jest po niej) i SBOM,
# żeby test #277 sprawdzał wyłącznie bramkę E2E, a nie zależał od wersji hosta.
setup_e2e_release_repo() {
  setup_release_repo
  cat >"$RELEASE_REPO/ci/image_identity.py" <<'EOF'
#!/usr/bin/env python3
import sys
sys.exit(0)
EOF
  cat >"$RELEASE_REPO/ci/sbom.sh" <<'EOF'
#!/usr/bin/env bash
printf '{"spdxVersion":"SPDX-2.3"}\n' >"$2"
EOF
  chmod +x "$RELEASE_REPO/ci/sbom.sh"
  git -C "$RELEASE_REPO" add ci
  git -C "$RELEASE_REPO" -c commit.gpgsign=false commit -q --amend -m fixture
  git -C "$RELEASE_REPO" tag -f v9.9.9 >/dev/null

  E2E_FULL="wlb-general-9.9.9-20260101"
  E2E_ART="$BATS_TEST_TMPDIR/build/artifacts/$E2E_FULL"
  E2E_OUT="$RELEASE_REPO/output/$E2E_FULL"
  write_e2e_provenance "$E2E_ART" "$E2E_OUT"

  E2E_BIN="$BATS_TEST_TMPDIR/bin"
  E2E_LISTING="$BATS_TEST_TMPDIR/virt-ls-listing"
  mkdir -p "$E2E_BIN"
  # Atrapa pilnuje argv bramki: `-i` jest opcją guestfish, nie virt-ls (#360).
  cat >"$E2E_BIN/virt-ls" <<'EOF'
#!/usr/bin/env bash
if [[ ${1:-} != --format=qcow2 || ${2:-} != -a || ${4:-} != -R || ${5:-} != / ]]; then
  echo "virt-ls: nieoczekiwane argv: $*" >&2
  exit 1
fi
cat "$E2E_LISTING"
EOF
  chmod +x "$E2E_BIN/virt-ls"
}

@test "image_provenance: commit, flaga dirty, build_run (#12)" {
  source "$REPO_ROOT/ci/image-meta.sh"
  local r="$BATS_TEST_TMPDIR/repo"
  mkdir -p "$r"
  cd "$r"
  git init -q
  git config user.email t@example.com
  git config user.name tester
  echo a >f
  git add f
  git commit -qm init
  unset GITHUB_RUN_ID
  image_provenance
  [[ $GIT_COMMIT =~ ^[0-9a-f]{40}$ ]]
  [ "$GIT_DIRTY" -eq 0 ]
  [ "$BUILD_RUN" = local ]
  echo b >>f # zmiana śledzonego pliku
  image_provenance
  [ "$GIT_DIRTY" -eq 1 ]
}

@test "image_provenance: GITHUB_RUN_ID trafia do BUILD_RUN (#12)" {
  source "$REPO_ROOT/ci/image-meta.sh"
  cd "$BATS_TEST_TMPDIR"
  GITHUB_RUN_ID=12345 image_provenance
  [ "$BUILD_RUN" = 12345 ]
}

@test "release.sh: zły format tagu przerywa (#12)" {
  run bash "$REPO_ROOT/ci/release.sh" nie-jest-tagiem
  [ "$status" -ne 0 ]
  [[ $output == *"format vX.Y.Z"* ]]
}

@test "release.sh: brak tagu przerywa (#12)" {
  GITHUB_REF_NAME='' run bash "$REPO_ROOT/ci/release.sh"
  [ "$status" -ne 0 ]
  [[ $output == *"podaj tag"* ]]
}

@test "release.sh: brak dpkg-status zatrzymuje wydanie przed kopiowaniem (#129)" {
  setup_release_repo
  local art="$BATS_TEST_TMPDIR/art"
  mkdir -p "$art"
  printf 'WLB_IMAGE_VERSION=9.9.9\nWLB_GIT_COMMIT=%s\nWLB_GIT_DIRTY=0\n' \
    "$(git -C "$RELEASE_REPO" rev-parse HEAD)" >"$art/image-release"
  run bash "$RELEASE_REPO/ci/release.sh" v9.9.9 "$art"
  [ "$status" -ne 0 ]
  [[ $output == *"bez inwentarza systemowego (#129)"* ]]
  [ ! -e "$RELEASE_REPO/build/release" ]
}

@test "release.sh: niezgodna para tozsamosci OS zatrzymuje wydanie (#129)" {
  setup_release_repo
  local art="$BATS_TEST_TMPDIR/art2"
  mkdir -p "$art"
  printf 'WLB_IMAGE_VERSION=9.9.9\nWLB_GIT_COMMIT=%s\nWLB_GIT_DIRTY=0\n' \
    "$(git -C "$RELEASE_REPO" rev-parse HEAD)" >"$art/image-release"
  printf 'Package: acl\nVersion: 2.3.1\n\n' >"$art/dpkg-status"
  printf 'ID=debian\nVERSION_ID=12\n' >"$art/os-release"
  run bash "$RELEASE_REPO/ci/release.sh" v9.9.9 "$art"
  [ "$status" -ne 0 ]
  [[ $output == *"niezweryfikowana lub niezgodna (#129)"* ]]
  [ ! -e "$RELEASE_REPO/build/release" ]
}

@test "release.sh: obraz z fixture E2E jest odrzucany kodem 3 (#277)" {
  setup_e2e_release_repo
  printf 'etc/os-release\nopt/wlb/e2e/target.json\n' >"$E2E_LISTING"
  run env PATH="$E2E_BIN:$PATH" E2E_LISTING="$E2E_LISTING" \
    bash "$RELEASE_REPO/ci/release.sh" v9.9.9 "$E2E_ART"
  [ "$status" -eq 3 ]
  [[ $output == *"fixture E2E"* ]]
  [[ $output == *"/opt/wlb/e2e"* ]]
  [ ! -e "$RELEASE_REPO/build/release" ]
}

@test "release.sh: obraz bez fixture E2E przechodzi bramkę (#277)" {
  setup_e2e_release_repo
  printf 'etc/os-release\nopt/wlb/bin/wlb-health\n' >"$E2E_LISTING"
  run env PATH="$E2E_BIN:$PATH" E2E_LISTING="$E2E_LISTING" \
    bash "$RELEASE_REPO/ci/release.sh" v9.9.9 "$E2E_ART"
  [ "$status" -eq 0 ]
  [ -s "$RELEASE_REPO/build/release/image-release" ]
  [ -s "$RELEASE_REPO/build/release/packer-manifest.json" ]
  [ -s "$RELEASE_REPO/build/release/wlb-general-9.9.9-20260101.qcow2.sha256" ]
  [ -s "$RELEASE_REPO/build/release/sbom.spdx.json" ]
}

@test "release.sh: manifest z innego builda zatrzymuje wydanie (#277)" {
  setup_e2e_release_repo
  python3 - "$E2E_OUT/packer-manifest.json" <<'PY'
import json, sys
path = sys.argv[1]
data = json.load(open(path))
data["builds"][0]["custom_data"]["git_commit"] = "0" * 40
json.dump(data, open(path, "w"))
PY
  printf 'etc/os-release\n' >"$E2E_LISTING"
  run env PATH="$E2E_BIN:$PATH" E2E_LISTING="$E2E_LISTING" \
    bash "$RELEASE_REPO/ci/release.sh" v9.9.9 "$E2E_ART"
  [ "$status" -ne 0 ]
  [[ $output == *"custom_data.git_commit"* ]]
  [ ! -e "$RELEASE_REPO/build/release" ]
}

@test "release.sh: suma niezgodna z obrazem zatrzymuje wydanie (#277)" {
  setup_e2e_release_repo
  printf '%064d  %s\n' 0 "$E2E_FULL.qcow2" >"$E2E_OUT/$E2E_FULL.qcow2.sha256"
  printf 'etc/os-release\n' >"$E2E_LISTING"
  run env PATH="$E2E_BIN:$PATH" E2E_LISTING="$E2E_LISTING" \
    bash "$RELEASE_REPO/ci/release.sh" v9.9.9 "$E2E_ART"
  [ "$status" -ne 0 ]
  [[ $output == *"nie zgadza się z obrazem"* ]]
  [ ! -e "$RELEASE_REPO/build/release" ]
}

@test "release.sh: obcy manifest w repo nie jest brany zamiast manifestu obrazu (#277)" {
  setup_e2e_release_repo
  printf '{"builds":[]}\n' >"$RELEASE_REPO/packer-manifest.json"
  printf 'etc/os-release\n' >"$E2E_LISTING"
  run env PATH="$E2E_BIN:$PATH" E2E_LISTING="$E2E_LISTING" \
    bash "$RELEASE_REPO/ci/release.sh" v9.9.9 "$E2E_ART"
  [ "$status" -eq 0 ]
}

@test "release.sh: katalog artefaktów niezgodny z metadanymi zatrzymuje wydanie (#277)" {
  setup_e2e_release_repo
  local obcy="$BATS_TEST_TMPDIR/art-e2e"
  cp -a "$E2E_ART" "$obcy"
  printf 'etc/os-release\n' >"$E2E_LISTING"
  run env PATH="$E2E_BIN:$PATH" E2E_LISTING="$E2E_LISTING" \
    bash "$RELEASE_REPO/ci/release.sh" v9.9.9 "$obcy"
  [ "$status" -ne 0 ]
  [[ $output == *"nie odpowiada metadanym"* ]]
  [ ! -e "$RELEASE_REPO/build/release" ]
}

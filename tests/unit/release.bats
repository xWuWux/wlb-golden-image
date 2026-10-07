#!/usr/bin/env bats
# Testy proweniencji i walidacji wydania (#12).

load helpers

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

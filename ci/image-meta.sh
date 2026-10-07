# shellcheck shell=bash
# Proweniencja obrazu (#12a): wiąże artefakt z kodem, z którego powstał. Wspólne dla etapu 5
# (ci/integration.sh) i wydania (ci/release.sh), żeby liczyć to w jednym miejscu.
#
# image_provenance — eksportuje:
#   GIT_COMMIT    pełny SHA HEAD (puste poza repozytorium git)
#   GIT_DESCRIBE  git describe --tags --always --dirty (albo krótki SHA)
#   GIT_DIRTY     1, gdy drzewo robocze ma niezacommitowane zmiany; 0 gdy czyste
#   BUILD_RUN     identyfikator przebiegu CI (GITHUB_RUN_ID) albo "local"
image_provenance() {
  if git rev-parse --git-dir >/dev/null 2>&1; then
    GIT_COMMIT=$(git rev-parse HEAD)
    if git diff --quiet HEAD 2>/dev/null; then GIT_DIRTY=0; else GIT_DIRTY=1; fi
    GIT_DESCRIBE=$(git describe --tags --always --dirty 2>/dev/null || git rev-parse --short HEAD)
  else
    GIT_COMMIT="" GIT_DESCRIBE="" GIT_DIRTY=""
  fi
  BUILD_RUN=${GITHUB_RUN_ID:-local}
  export GIT_COMMIT GIT_DESCRIBE GIT_DIRTY BUILD_RUN
}

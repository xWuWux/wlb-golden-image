#!/usr/bin/env bash
# Składa pakiet wydania obrazu z tagu vX.Y.Z (#12a): metadane z proweniencją, SBOM (SPDX),
# changelog, SHA256SUMS. Sam obraz qcow2 i miejsce jego przechowywania to #12b (zależne od #15).
#   ci/release.sh [TAG] [KATALOG_ARTEFAKTÓW]
# TAG domyślnie z GITHUB_REF_NAME; katalog artefaktów — autodetekcja w build/artifacts/.
# Wynik: build/release/ (pliki wydania) + build/release/CHANGELOG.md (treść notatek).
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
require git python3

TAG=${1:-${GITHUB_REF_NAME:-}}
[[ -n $TAG ]] || die "podaj tag (albo uruchom z GITHUB_REF_NAME)"
[[ $TAG =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "tag musi mieć format vX.Y.Z, jest '${TAG}'"
VERSION=${TAG#v}

# Wydanie musi być powtarzalne i jednoznaczne: czyste drzewo i tag wskazujący dokładnie HEAD.
if ! git diff --quiet || ! git diff --cached --quiet; then
  die "drzewo robocze nie jest czyste — wydanie przerwane"
fi
[[ $(git rev-parse "${TAG}^{commit}") == $(git rev-parse HEAD) ]] ||
  die "tag ${TAG} nie wskazuje bieżącego HEAD — buduj wydanie na otagowanym commicie"
COMMIT=$(git rev-parse HEAD)

ARTIFACTS=${2:-$(find . -type d -path '*/build/artifacts/wlb-general-*' 2>/dev/null | sort | tail -1)}
[[ -n $ARTIFACTS && -d $ARTIFACTS ]] || die "nie znaleziono katalogu artefaktów obrazu (build/artifacts/wlb-general-*)"
[[ -s $ARTIFACTS/image-release ]] || die "brak image-release w ${ARTIFACTS}"
# manifest i suma qcow2 leżą obok (output/<full>/) — szukamy po nazwie, niezależnie od układu
MANIFEST=$(find . -name 'packer-manifest.json' 2>/dev/null | head -1)

# Proweniencja artefaktu musi zgadzać się z tym wydaniem (wersja z tagu, commit = HEAD, czyste drzewo).
rel_commit=$(sed -n 's/^WLB_GIT_COMMIT=//p' "$ARTIFACTS/image-release")
rel_version=$(sed -n 's/^WLB_IMAGE_VERSION=//p' "$ARTIFACTS/image-release")
rel_dirty=$(sed -n 's/^WLB_GIT_DIRTY=//p' "$ARTIFACTS/image-release")
[[ $rel_version == "$VERSION" ]] || die "obraz ma wersję '${rel_version}', a tag mówi '${VERSION}' — zbuduj obraz z IMAGE_VERSION=${VERSION}"
[[ $rel_commit == "$COMMIT" ]] || die "obraz zbudowano z commita '${rel_commit}', a HEAD to '${COMMIT}'"
[[ $rel_dirty == 0 ]] || die "obraz zbudowano z brudnego drzewa (WLB_GIT_DIRTY=${rel_dirty})"

OUT=build/release
rm -rf "$OUT"
mkdir -p "$OUT"

# Metadane wydania (bez qcow2 — jego przechowywanie to #12b)
cp "$ARTIFACTS/image-release" "$OUT/"
[[ -n $MANIFEST && -s $MANIFEST ]] && cp "$MANIFEST" "$OUT/packer-manifest.json"
for f in environment.lock.yml renv.lock dpkg-status; do
  [[ -s $ARTIFACTS/$f ]] && cp "$ARTIFACTS/$f" "$OUT/"
done
# suma qcow2 policzona przy budowaniu (sam obraz jest poza wydaniem w 12a)
find . -name '*.qcow2.sha256' -exec cp {} "$OUT/" \; 2>/dev/null || true

# SBOM (SPDX)
step "SBOM"
ci/sbom.sh "$ARTIFACTS" "$OUT/sbom.spdx.json"
endstep

# Changelog od poprzedniego tagu (albo od początku historii dla pierwszego wydania)
step "Changelog"
prev=$(git describe --tags --abbrev=0 "${TAG}^" 2>/dev/null || true)
if [[ -n $prev ]]; then range="${prev}..${TAG}"; else range="$TAG"; fi
{
  echo "# ${TAG} — $(sed -n 's/^WLB_IMAGE_DATE=//p' "$ARTIFACTS/image-release")"
  echo
  echo "Commit: \`${COMMIT}\` · obraz: \`$(sed -n 's/^WLB_IMAGE_NAME=//p' "$ARTIFACTS/image-release")-${VERSION}\`"
  [[ -n $prev ]] && echo "Poprzednie wydanie: ${prev}"
  echo
  echo "## Zmiany"
  git log "$range" --no-merges --pretty='- %s (%h)'
} >"$OUT/CHANGELOG.md"
endstep

# SHA256SUMS dla wszystkich plików wydania (poza samym plikiem sum)
step "SHA256SUMS"
(cd "$OUT" && find . -maxdepth 1 -type f ! -name 'SHA256SUMS*' -printf '%P\n' | sort |
  xargs sha256sum >SHA256SUMS.tmp && mv SHA256SUMS.tmp SHA256SUMS)
endstep

echo "Pakiet wydania ${TAG} w ${OUT}/:"
ls -1 "$OUT"

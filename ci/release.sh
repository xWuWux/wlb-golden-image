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
# #129: tożsamość OS broni release przed kopiowaniem — pozna awaria w sbom.sh
# zastalaby katalog wydania częściowo wypełniony.
[[ -s $ARTIFACTS/dpkg-status ]] ||
  die "release: brak dpkg-status — pakiet wydania bez inwentarza systemowego (#129)"
python3 ci/image_identity.py "$ARTIFACTS" ||
  die "release: tożsamość OS artefaktów niezweryfikowana lub niezgodna (#129)"
# Proweniencja artefaktu musi zgadzać się z tym wydaniem (wersja z tagu, commit = HEAD, czyste drzewo).
rel_commit=$(sed -n 's/^WLB_GIT_COMMIT=//p' "$ARTIFACTS/image-release")
rel_version=$(sed -n 's/^WLB_IMAGE_VERSION=//p' "$ARTIFACTS/image-release")
rel_dirty=$(sed -n 's/^WLB_GIT_DIRTY=//p' "$ARTIFACTS/image-release")
[[ $rel_version == "$VERSION" ]] || die "obraz ma wersję '${rel_version}', a tag mówi '${VERSION}' — zbuduj obraz z IMAGE_VERSION=${VERSION}"
[[ $rel_commit == "$COMMIT" ]] || die "obraz zbudowano z commita '${rel_commit}', a HEAD to '${COMMIT}'"
[[ $rel_dirty == 0 ]] || die "obraz zbudowano z brudnego drzewa (WLB_GIT_DIRTY=${rel_dirty})"

# #277-S3: wydanie nie może zawierać fixture E2E pulpitu. Sprawdzamy qcow2 wskazany przez
# metadane wydania (nie flavor testowy z output/); brak obrazu to błąd (fail-closed), nie
# „czysto”. ARTIFACTS to metadane (image-release, dpkg-status, locki) — nie rootfs, więc
# bramka drzewa nie ma tu czego sprawdzać; ścieżki E2E są wyłącznie w obrazie.
# Ścieżka obrazu jak w ci/integration.sh: output/<full>/<full>.qcow2.
rel_name=$(sed -n 's/^WLB_IMAGE_NAME=//p' "$ARTIFACTS/image-release")
rel_date=$(sed -n 's/^WLB_IMAGE_DATE=//p' "$ARTIFACTS/image-release")
[[ $rel_name =~ ^wlb-[a-z0-9]+(-[a-z0-9]+)*$ ]] ||
  die "image-release: nieprawidłowa nazwa obrazu '${rel_name}'"
[[ $rel_date =~ ^[0-9]{8}$ ]] ||
  die "image-release: data musi mieć format YYYYMMDD, jest '${rel_date}'"
FULL_NAME="${rel_name}-${VERSION}-${rel_date}"
[[ $(basename "$ARTIFACTS") == "$FULL_NAME" ]] ||
  die "katalog artefaktów '$(basename "$ARTIFACTS")' nie odpowiada metadanym wydania '${FULL_NAME}'"
RELEASE_DIR="output/${FULL_NAME}"
RELEASE_IMAGE="${RELEASE_DIR}/${FULL_NAME}.qcow2"
MANIFEST="${RELEASE_DIR}/packer-manifest.json"
CHECKSUM="${RELEASE_IMAGE}.sha256"
[[ -f $RELEASE_IMAGE ]] ||
  die "brak obrazu ${RELEASE_IMAGE} — nie można zweryfikować braku fixture E2E (#277)"
[[ -s $MANIFEST ]] ||
  die "brak manifestu ${MANIFEST} — nie można powiązać obrazu z buildem (#277)"
[[ -s $CHECKSUM ]] ||
  die "brak sumy ${CHECKSUM} — nie można powiązać obrazu z buildem (#277)"
step "Proweniencja obrazu (#277)"
python3 ci/release_provenance.py \
  --artifacts "$ARTIFACTS" --image "$RELEASE_IMAGE" \
  --manifest "$MANIFEST" --checksum "$CHECKSUM" \
  --repo-root "$REPO_ROOT" \
  --version "$VERSION" --commit "$COMMIT" ||
  die "obraz nie jest powiązany z manifestem i sumą wydania (#277)"
endstep
E2E_ARGS=(--image "$RELEASE_IMAGE")
step "Bramka E2E (#277)"
e2e_rc=0
python3 ci/e2e_release_gate.py "${E2E_ARGS[@]}" || e2e_rc=$?
endstep
# Kod 3 = znaleziono artefakt E2E; kod 2 = nie można zweryfikować. Oba przerywają wydanie
# i są przekazywane dalej bez zmiany, żeby CI mogło je rozróżnić.
((e2e_rc == 0)) || exit "$e2e_rc"

OUT=build/release
rm -rf "$OUT"
mkdir -p "$OUT"

# Metadane wydania (bez qcow2 — jego przechowywanie to #12b)
cp "$ARTIFACTS/image-release" "$OUT/"
cp "$MANIFEST" "$OUT/packer-manifest.json"
cp "$CHECKSUM" "$OUT/"
for f in environment.lock.yml renv.lock dpkg-status os-release; do
  [[ -s $ARTIFACTS/$f ]] && cp "$ARTIFACTS/$f" "$OUT/"
done

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

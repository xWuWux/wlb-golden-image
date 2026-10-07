# Wersjonowanie i wydania obrazu (#12a)

Wydanie powstaje z **tagu `vX.Y.Z`**. Workflow `release.yml` buduje obraz i etap 5 na otagowanym
commicie, a po sukcesie publikuje **GitHub Release** z pakietem metadanych. Sam qcow2 (4,3 GB,
powyżej limitu 2 GiB GitHuba) i miejsce jego przechowywania to osobne zgłoszenie **#12b** (zależne
od decyzji o hypervisorze #15).

## Numeracja (SemVer dla Laboratorium)

- **MAJOR** — zmiana **niekompatybilna dla Laboratorium**: format `lab.env`/user-data, układ dysku
  roboczego, migracja bazy huba bez powrotu (`c.JupyterHub.upgrade_db = True`).
- **MINOR** — nowe funkcje i pakiety, zgodne wstecz.
- **PATCH** — przebudowa z poprawkami (w tym bezpieczeństwa) bez nowych funkcji.

Para **(wersja, data)** jest unikalna i niezmienna. Przebudowa bezpieczeństwa podbija **PATCH**, a
nie samą datę — inaczej dwa różne obrazy miałyby ten sam numer. Zasady do utrwalenia w ADR (#14).

## Proweniencja (powiązanie obrazu z kodem)

Każdy obraz niesie commit, z którego powstał — w `packer-manifest.json` (`custom_data`) i w
`/etc/wlb/image-release`:

```
WLB_GIT_COMMIT=<pełny SHA>
WLB_GIT_DESCRIBE=<git describe --tags --always --dirty>
WLB_GIT_DIRTY=<0|1>
WLB_BUILD_RUN=<GITHUB_RUN_ID albo local>
```

Liczy to wspólny helper `ci/image-meta.sh` (`image_provenance`), używany przez etap 5
(`ci/integration.sh`) i wydanie (`ci/release.sh`). Dzięki temu dla każdego obrazu w Laboratorium
wiadomo, z jakiego kodu powstał (zamyka DoD #32/#105 i scenariusz „dwa obrazy 0.1.0, różne pakiety").

## Zawartość wydania (pakiet metadanych)

`ci/release.sh` składa w `build/release/`:

- `image-release` — metadane z proweniencją,
- `packer-manifest.json` — manifest Packera,
- `sbom.spdx.json` — SBOM w **SPDX** (osv-scanner; CycloneDX gubi pakiety deb Ubuntu, #12),
- `environment.lock.yml`, `renv.lock`, `dpkg-status` — zamrożone zależności i pakiety systemowe,
- `*.qcow2.sha256` — suma kontrolna obrazu (sam obraz jest poza wydaniem w 12a),
- `CHANGELOG.md` — `git log <poprzedni tag>..<tag> --no-merges` (treść notatek wydania),
- `SHA256SUMS` — sumy wszystkich plików wydania.

`ci/release.sh` **odmawia**, gdy: tag nie ma formatu `vX.Y.Z`, drzewo nie jest czyste, tag nie
wskazuje HEAD, albo proweniencja obrazu nie zgadza się z tagiem/commitem.

## Jak wydać

```bash
# na zielonym main, z czystym drzewem
git tag v0.1.0
git push origin v0.1.0
# release.yml zbuduje, zweryfikuje (etap 5) i opublikuje GitHub Release v0.1.0
```

## Poza zakresem 12a (świadomie)

- Przechowywanie niezmiennego qcow2 i promocja DEV→UAT→PROD — **#12b** (po #15).
- Zamrożenie apt ze `snapshot.ubuntu.com` (powtarzalność pakietów systemowych) i podpis
  (cosign/GPG) — osobne, niższe priorytety.

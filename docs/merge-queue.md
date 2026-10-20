# Konfiguracja GitHub Merge Queue

## Kontekst

Problem „zielony PR, czerwony `main` po scaleniu" — PR przeszło wszystkie checki w momencie
tworzenia, ale `main` poszedł dalej. Po merge'u PR może widzieć starszą wersję zależności lub
stan konfliktu semantycznego. Merge Queue testuje PR na potencjalnym stanie `main` po merge:
dla każdego PR w kolejce GitHub tworzy tymczasową gałąź `gh-readonly-queue/main/<sha>` =
`main` + kolejka PR-ów przed nim + commit PR.

Case study: PR #103 (2026-10-20). Dependabot `actions/upload-artifact 7.0.1 → 7.0.2` utworzony
przed PR #119 (`fix/aiohttp-cve-3144`). Po re-runie CI Stage 3 SCA rzucał 3 CVE, których łata była
już na `main`. Z Merge Queue: PR #103 dodany do kolejki → gałąź tymczasowa = `main` (z
`aiohttp==3.14.4`) + commit PR #103 → SCA zielono → automatyczny merge. Zero ręcznej pracy.

## Krok 1: dodaj trigger `merge_group` do `ci.yml`

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened, labeled, ready_for_review]
  merge_group:
    types: [checks_requested]
  push:
    branches: [main]
```

Dla `ci-retry.yml` i `ci-observability.yml` — nie dodawaj. Działają na `workflow_run` z gałęzi
domyślnej, więc zachowują się identycznie w kolejce. `release.yml` — nie dodawaj, trigger na
`push: tags: ['v*']`.

## Krok 2: branch protection — włącz Merge Queue

UI: Settings → Branches → Edit rule on `main` → ✅ Require merge queue.

| Parametr | Wartość | Uwagi |
|---|---|---|
| Merge method | Merge | Squash jeśli wolisz linear history |
| Maximum entries to build | 5 | ile PR-ów w kolejce jednocześnie |
| Minimum entries to merge | 1 | merge gdy 1 PR przejdzie |
| Maximum wait | 5 minutes | jak długo czekać na zapełnienie kolejki |

## Krok 3: weryfikacja

1. Otwórz testowy PR z drobną zmianą (np. typo w `README.md`).
2. Poczekaj na zielone CI.
3. Kliknij „Merge" → powinno pokazać „Add to merge queue".
4. GitHub utworzy `gh-readonly-queue/main/<sha>`:
   ```bash
   gh run list --branch 'gh-readonly-queue/main/*' --limit 5
   ```
5. Po zielonym CI na gałęzi tymczasowej → automatyczny merge do `main`.

## Krok 4 (opcjonalny): podział checków na szybkie i ciężkie

Aby uniknąć odpalania etapu 5 (integracja KVM, timeout 180 min) na zwykłym PR, ogranicz go do
merge queue i nocnego harmonogramu:

```yaml
integration:
  name: "5. Integracja i migracja"
  needs: [lint, unit]
  if: needs.lint.outputs.image == 'true' && github.event_name == 'merge_group'
```

Branch protection: `integration` jako required status check — wtedy wymuszamy przejście etapu 5
przed każdym scaleniem.

## Korzyści i koszty

| Aspekt | Bez MQ | Z MQ |
|---|---|---|
| Zielony PR, czerwony `main` po merge | częsty (jak PR #103) | niemożliwy |
| Konflikty semantyczne | wykrywane po merge (rollback) | wykrywane przed merge |
| Równoległy merge wielu PR | blokują się lub race | kolejkowane |
| Dodatkowe runy CI | — | każdy PR w kolejce = +1 run |
| Czas do merge | natychmiastowy | max 5 min + czas CI |

## Migracja — plan rollout

**Tydzień 1 (przygotowanie):**
- [ ] Dodaj `merge_group` trigger do `ci.yml`
- [ ] Przetestuj na 1 PR — czy checki odpalają się poprawnie
- [ ] Weryfikacja: `gh run list --branch 'gh-readonly-queue/main/*'`

**Tydzień 2 (włączenie):**
- [ ] Włącz Merge Queue w branch protection
- [ ] Komunikat do zespołu: „od teraz merge idzie przez kolejkę"
- [ ] Monitorować: czy są awarie, czy czas merge'owania akceptowalny

**Tydzień 3+ (pełny rollout):**
- [ ] Jeśli tydzień 2 zielony — zostawiamy
- [ ] Jeśli problemy — wyłączyć, diagnozować

## Alternatywy

1. **`bors` / `bors-ng`** — zewnętrzny bot robiący to samo. Darmowy, ale wymaga utrzymania.
2. **Manual rebase przed merge** — każdy PR przed kliknięciem „Merge" musi być zrebase'owany
   na `main`. Procedura w `docs/ci-runbook.md` sekcja `## dependabot-sca`.
3. **`merge-bot` GitHub Action** — automatyczny rebase + CI retry przed merge.

Dla projektu `wlb-golden-image` (~17 aktywnych gałęzi, kilka PR/tydzień) Merge Queue jest optymalne.

## Historia zmian

- **2026-10-20**: utworzono na podstawie incydentu PR #103. (wojtek)

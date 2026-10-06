# Wkład w projekt (CONTRIBUTING)

Obraz WLB to usługa **regulowana (Tier 4)** — dane medyczne/osobowe, RODO, Regulamin.
Wszystkie zmiany idą przez PR z zielonym CI; `main` jest chroniony.

## Reguła regresji (obowiązkowa)

**Każda poprawka błędu i każda nowa funkcjonalność dodaje test, który _pada przed_ zmianą
i _przechodzi po_ niej.** Celem jest, by po każdym kolejnym PR było widać, że działają zarówno
nowe, jak i wszystkie wcześniejsze funkcjonalności — bez ręcznego sprawdzania.

Dlaczego: błąd, który raz się wydarzył, to najlepszy kandydat na trwały test. Dla Tier 4 wymaga
tego Definition of Done (DoD #46 „testy pokrywają zmienione zachowanie, przypadki brzegowe i
regresję”, #52 „testy negatywne/bezpieczeństwa”). Przyjęcie DoD śledzi #58, zasady przeglądu #59.

### Jak to robić w praktyce

1. **Dobierz warstwę testu** (im niżej, tym szybciej i taniej):
   - logika skryptów (`wlb-firstboot`, śluza, `wlb-hub-user`, narzędzia CI) → **bats/pytest**
     w `tests/unit/` (etap 4, odpala się na **każdym** PR);
   - zachowanie na żywej VM (hub, spawner, sieć, rsyslog→SIEM, chrony→NTP, Traefik) →
     **akceptacja** w `tests/acceptance-remote.sh` lub migracja w `tests/migration-remote.sh`
     (etap 5, odpala się przy zmianach obrazu).
2. **Oznacz test numerem zgłoszenia** — wpisz `#NN` w tytule testu albo w nagłówku sekcji
   (`@test "... (#NN)"`, `expect_ok "... (#NN)"`, `# --- ... (#NN) ---`). Dzięki temu test trafia
   do mapy [`docs/mapa-testy-zgloszenia.md`](docs/mapa-testy-zgloszenia.md)
   (generowana skryptem `ci/mapa-testy.py`).
3. **Trzymaj test hermetycznie** — bez zależności od zasobów zewnętrznych. Używaj lokalnych
   zaślepek (`tests/syslog_sink.py`, `tests/ntp_sink.py`, `tests/lib/test-pki.sh`) i atrap, tak jak
   istniejące testy; migoczący test to zły test (DoD #56 „determinizm”).
4. **Zaktualizuj dokumentację w tym samym PR** (README/runbook/kontrakt obserwowalności), jeśli
   zmieniasz zachowanie (DoD #115).

### Po dodaniu testu odśwież mapę

```sh
python3 ci/mapa-testy.py   # nadpisuje docs/mapa-testy-zgloszenia.md
```

## Etapy CI (skrót)

| Etap | Kiedy | Zakres |
|---|---|---|
| 1–4 (lint, build, security, kontrakt, jednostkowe) | **każdy PR** + nocny/cotygodniowy harmonogram | szybka pętla |
| 5 (integracja + migracja na KVM) | PR dotykające obrazu + **nocny pełny build** | e2e na żywej VM |
| 6a/6b (benchmarki, wdrożenie tymczasowe) | etykieta/`workflow_dispatch` + **nocny build** | wydajność, OpenStack |

Nocny pełny przebieg (harmonogram `CI`) uruchamia etapy 1–6 niezależnie od zakresu zmian — łapie
regresje spoza repozytorium (dryf zamrożonych wersji, nowe CVE), zanim uderzą w PR.

## Publiczne wątki

Repozytorium jest prywatne. Treści publikowane publicznie (komentarze, zgłoszenia upstream)
zatwierdza wcześniej właściciel projektu.

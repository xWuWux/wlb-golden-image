# Fragmenty kryteriów akceptacji (`tests/acceptance.d/`)

Każdy plik to jeden obszar testów akceptacyjnych MVP. `tests/acceptance.sh` **skleja na hoście**
w kolejności nazw: `tests/lib/remote-common.sh` + `tests/acceptance-remote.sh` (prep + rdzeń 1–10)
+ `tests/acceptance.d/*.sh` + `summary`, i wysyła jeden skrypt na VM testową.

## Po co
Dawniej każdy feature dopisywał numerowaną sekcję na końcu jednego `acceptance-remote.sh` — każdy
równoległy PR konfliktował w tym samym miejscu. Teraz **feature = nowy plik fragmentu** → brak
konfliktów na wspólnym pliku.

## Konwencja
- Nazwa: `NN-krotki-opis.sh` (NN ustala kolejność; zostaw odstępy, np. 10/20/30, na wstawki).
- Pierwsza linia: `# shellcheck shell=bash`.
- **Etykieta opisowa, bez numeru sekcji** (`echo "== AppArmor (#65) =="`) — numeracja sekwencyjna
  była źródłem kolizji.
- Korzystaj z funkcji (`expect_ok`, `expect_fail`, `as`) i zmiennych (`R1`, `R2`, `PW`, `QUEUE`)
  z prefiksu — NIE definiuj ich ponownie i NIE wołaj `summary` (robi to orchestrator).
- Lint sprawdza **złożony** skrypt (`ci/lint.sh`), bo fragment sam w sobie odwołuje się do prefiksu.

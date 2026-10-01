# IMG-001: Model przydziału VM i domyślne limity zasobów badacza

| | |
|---|---|
| Status | **Proponowana** (szkic, 2026-10-01) |
| Decyduje | Właściciel Platformy (z Liderem Projektu Klienta w zakresie liczby użytkowników) |
| Dotyczy | #30 (PR #49), #19 (storage), #20 (eksport), #18 (dostęp), `WLB_Specs.txt` |
| Identyfikator | `IMG-` = decyzja obrazu VM. W IP_CMC skrót „ADR” oznacza *Artefacts Deliverable Record* (zob. #14), stąd osobny prefiks. |

## Kontekst

Limity zasobów z #30 dzielą pamięć VM na **rezerwę dla usług** (audyt, logi, hub) i **pulę badaczy**, a pulę na **limit na badacza**. Domyślny limit na badacza zależy od tego, ilu badaczy pracuje równolegle na jednej VM. Dokumenty projektu nie są w tej sprawie spójne:

- **Specyfikacja VM (`WLB_Specs.txt`)** zakłada VM współdzieloną przez zespół:
  > „Jedna VM per Laboratorium, oparta o The Littlest JupyterHub, do testów z jednym badaczem-testerem…”
  > „The Littlest JupyterHub (TLJH) — instalator oficjalny, jedna VM obsługuje wszystkich badaczy przypisanych do danego Laboratorium jako osobni użytkownicy Hub.”
- **Regulamin** mówi o pulpitach roboczych tworzonych dla użytkowników i o systemie plików wspólnym dla zespołu, nie o VM współdzielonej:
  > §8: Projekt badawczy obejmuje m.in. „współdzielony system plików dla danych projektowych” oraz „przypisane do użycia OS Image”.
  > §9: „Administrator IP_CMC, lub Administrator Klienta Środowiska WLB tworzy wirtualne pulpity robocze przez portal webowy WLB.”
  > §10: „Każdy Projekt badawczy posiada współdzielony system plików dostępny dla wszystkich członków zespołu. Systemy plików są automatycznie montowane w wirtualnych pulpitach roboczych.”
- **Analiza wymagań (BP-VL-1, BP-VL-4.1)** wymienia „pulpity robocze użytkowników” jako produkt uruchomienia Laboratorium i jako zasób usuwany przy jego zamknięciu.
- **Ustalenie z 2026-10-01 (właściciel repozytorium):** każdy badacz ma własną, niezależną VM. Nie przewiduje się podziału jednej VM między kilku badaczy.

Obraz i domyślne wartości w PR #49 przyjęły dotąd założenie ze specyfikacji, czyli VM współdzieloną: na badacza 50% puli pamięci i 50% vCPU. Wartość 50% pochodzi z planu implementacji #30.

## Decyzja 1: model przydziału VM

| Wariant | Opis | Za | Przeciw |
|---|---|---|---|
| **A. VM na badacza** (ustalenie z 2026-10-01) | Każdy badacz ma własną VM z obrazu. Dane zespołu wymienia współdzielony system plików projektu (§10). | Pełna izolacja badaczy (pamięć, CPU, procesy, `/tmp`, sieć). Zgodne z modelem „pulpitów roboczych użytkowników” w Regulaminie i Analizie. Prostsze limity. | Więcej VM, więc większy koszt i więcej zarządzania (§11, budżet projektu). Wymaga współdzielonego systemu plików między VM (#19). |
| **B. VM na Laboratorium** (specyfikacja) | Jedna VM dla całego zespołu, każdy badacz to osobny użytkownik huba. | Mniej VM. Wspólny `/workspace` bez dodatkowego storage. | Badacze dzielą zasoby, a izolacja zależy wyłącznie od obrazu (limity z #30, prawa plików). Niezgodne z modelem pulpitów per użytkownik. |
| **C. Mieszany** | Domyślnie A. B jako wyjątek dla małych zespołów z jednym badaczem aktywnym naraz. | Elastyczność | Dwa modele do testowania i opisania w runbookach |

**Rekomendacja: A**, zgodnie z ustaleniem i z Regulaminem. Specyfikację VM trzeba zaktualizować (dwa cytowane zdania).

## Decyzja 2: domyślne limity

Rezerwa na usługi pozostaje bez zmian w obu modelach: **max(3 GB, 10% RAM)**. Chroni audyt i logi (§21) także przed jedynym badaczem na VM.

| RAM VM | Rezerwa | Pula badacza | **A**: limit badacza (100% puli) | **B**: przy 2 badaczach (50%) | **B**: przy 4 badaczach (25%) |
|---|---|---|---|---|---|
| 8 GB | 3,0 GB | 5,0 GB | **5,0 GB** | 2,5 GB | 1,25 GB |
| 16 GB | 3,0 GB | 13,0 GB | **13,0 GB** | 6,5 GB | 3,25 GB |
| 32 GB | 3,2 GB | 28,8 GB | **28,8 GB** | 14,4 GB | 7,2 GB |
| 64 GB | 6,4 GB | 57,6 GB | **57,6 GB** | 28,8 GB | 14,4 GB |

CPU: w A badacz dostaje **wszystkie vCPU**, a usługi zachowują pierwszeństwo dzięki wagom CPU cgroup. W B dostaje 1/N vCPU.

Pozostałe ustawienia z #30 są wspólne dla obu modeli i nadal potrzebne także przy jednym badaczu:
- `OOMPolicy=continue`: przekroczenie pamięci zabija proces, zwykle kernel, a nie cały serwer notebooków,
- `TasksMax=2048`: ochrona przed fork bomb,
- ujemne `OOMScoreAdjust` usług.

**Rekomendacja (przy A):**
- domyślnie `RESEARCHER_MEM_LIMIT` = 100% puli i `RESEARCHER_CPU_LIMIT` = liczba vCPU,
- nadpisania w `lab.env` bez zmian,
- przy B jako wyjątku: `RESEARCHER_MEM_LIMIT` ustawiany jawnie, np. pula / maksymalna liczba aktywnych badaczy.

## Konsekwencje wariantu A

| Obszar | Konsekwencja | Zgłoszenie |
|---|---|---|
| Limity (#30) | Domyślne przeliczniki 100% zamiast 50%. Zmiana w `wlb-firstboot` i w testach bats. | #30 / PR #49 |
| Storage | `/workspace` należy do jednego badacza (dysk VM). **Współdzielony system plików projektu (§10)** musi być osobnym montowaniem wspólnym dla wszystkich VM zespołu (CephFS/NFS), z decyzją o prawach (kto czyta i zapisuje). | #19 |
| Śluzy | `/sluza-in` i `/sluza-out` montowane w każdej VM projektu. Kolejka eksportu jest dziś per VM (dysk roboczy), więc trzeba zdecydować, czy Kontroler widzi kolejki wszystkich VM projektu w jednym miejscu. | #20, #33 |
| Hub | Zostaje wieloużytkownikowy (badacz i Administrator Klienta), ale izolacja między badaczami w jednej VM staje się obroną w głębi, a nie główną granicą. | — |
| Koszty | Liczba VM = liczba aktywnych badaczy. Ma to wpływ na budżet projektu (§11) i wyłączanie nieużywanych pulpitów (§9). | — |
| Specyfikacja | Aktualizacja `WLB_Specs.txt`: „jedna VM per badacz” zamiast „jedna VM per Laboratorium … wszyscy badacze jako osobni użytkownicy Hub”. | — |
| Testy | Testy izolacji dwóch badaczy (tester1/tester2) zostają jako obrona w głębi. Dochodzi test współdzielonego systemu plików między dwiema VM (po #19). | #19 |

## Pytania do Właściciela Platformy

1. Czy potwierdzamy wariant **A** (VM na badacza) jako docelowy, a B najwyżej jako wyjątek?
2. Czy domyślny limit badacza = **100% puli** (po rezerwie max(3 GB, 10% RAM)) jest akceptowalny?
3. Jak wygląda współdzielony system plików projektu w modelu A (#19): jeden udział na projekt, montowany w każdej VM zespołu, z jakimi prawami?
4. Czy kolejka eksportu ma być wspólna dla projektu (wszystkie VM), czy per VM (#20)?

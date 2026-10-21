# IMG-001: Model przydziału VM i domyślne limity zasobów badacza

* **Status:** Proponowana (szkic 2026-10-01; wariant C potwierdzony przez zespół projektu, czeka na zatwierdzenie Właściciela Platformy)
* **Data:** 2026-10-01
* **Autorzy / decyduje:** Właściciel Platformy (liczbę użytkowników ustala z Liderem Projektu Klienta)
* **Powiązania:** Regulamin: §8, §9, §10 · IP_CMC: ADR 5.1 (VirtualLab) · Zgłoszenia/PR: #30 (PR #49), #19, #20, #18 · Pliki: `WLB_Specs.txt`, `ansible/roles/lab_config/files/wlb-firstboot`

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
- **Ustalenia z 2026-10-01 (zespół projektu):** każdy badacz ma zwykle własną, niezależną VM, ale zdarzą się sytuacje, w których zespół prowadzi badania równolegle na tej samej VM na różnych kontach.

Obraz i domyślne wartości w PR #49 przyjęły dotąd założenie ze specyfikacji, czyli VM współdzieloną: na badacza 50% puli pamięci i 50% vCPU. Wartość 50% pochodzi z planu implementacji #30.

## Decyzja 1: model przydziału VM

| Wariant | Opis | Za | Przeciw |
|---|---|---|---|
| **A. VM na badacza** (ustalenie z 2026-10-01) | Każdy badacz ma własną VM z obrazu. Dane zespołu wymienia współdzielony system plików projektu (§10). | Pełna izolacja badaczy (pamięć, CPU, procesy, `/tmp`, sieć). Zgodne z modelem „pulpitów roboczych użytkowników” w Regulaminie i Analizie. Prostsze limity. | Więcej VM, więc większy koszt i więcej zarządzania (§11, budżet projektu). Wymaga współdzielonego systemu plików między VM (#19). |
| **B. VM na Laboratorium** (specyfikacja) | Jedna VM dla całego zespołu, każdy badacz to osobny użytkownik huba. | Mniej VM. Wspólny `/workspace` bez dodatkowego storage. | Badacze dzielą zasoby, a izolacja zależy wyłącznie od obrazu (limity z #30, prawa plików). Niezgodne z modelem pulpitów per użytkownik. |
| **C. Mieszany** | Domyślnie A. B jako wyjątek dla małych zespołów z jednym badaczem aktywnym naraz. | Elastyczność | Dwa modele do testowania i opisania w runbookach |

**Rekomendacja: C**, zgodnie z ustaleniem zespołu: domyślnie VM na badacza, a kilka kont na jednej VM jako dopuszczalny przypadek. Obraz od początku obsługuje wiele kont (TLJH, osobne konta systemowe, hasła, katalogi domowe, limity i audyt per konto), więc C nie wymaga zmiany architektury administracji VM. Specyfikację VM trzeba zaktualizować (dwa cytowane zdania).

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

**Rekomendacja (przy C), wdrożona w PR #49:** parametr **`RESEARCHERS_PER_VM`** w `lab.env` (domyślnie 1). Limit badacza = pula / N, a CPU = vCPU / N (co najmniej 1). Przy N = 1 badacz dostaje całą pulę i wszystkie vCPU (kolumna A w tabeli), przy N > 1 odpowiednią część (kolumny B). Wspólny limit slice zawsze chroni usługi, niezależnie od N. `RESEARCHER_MEM_LIMIT` i `RESEARCHER_CPU_LIMIT` pozwalają ustawić wartości wprost.

## Odstępstwo od specyfikacji

* **Czy stanowi odstępstwo:** Tak.
* **Uzasadnienie / cytat:** `WLB_Specs.txt` zakłada VM współdzieloną: „jedna VM obsługuje wszystkich badaczy przypisanych do danego Laboratorium jako osobni użytkownicy Hub". Wariant A/C (domyślnie jedna VM per badacz, kilka kont na jednej VM jako dopuszczalny wyjątek) odchodzi od tego dla pełnej izolacji badaczy (pamięć, CPU, procesy, sieć) i zgodności z modelem „pulpitów roboczych użytkowników" (Regulamin §9). Specyfikację trzeba zaktualizować (dwa cytowane zdania).

## Konsekwencje wariantu A (VM na badacza; dotyczą też C)

| Obszar | Konsekwencja | Zgłoszenie |
|---|---|---|
| Limity (#30) | Domyślne przeliczniki 100% zamiast 50%. Zmiana w `wlb-firstboot` i w testach bats. | #30 / PR #49 |
| Storage | `/workspace` należy do jednego badacza (dysk VM). **Współdzielony system plików projektu (§10)** musi być osobnym montowaniem wspólnym dla wszystkich VM zespołu (CephFS/NFS), z decyzją o prawach (kto czyta i zapisuje). | #19 |
| Śluzy | `/sluza-in` i `/sluza-out` montowane w każdej VM projektu. Kolejka eksportu jest dziś per VM (dysk roboczy), więc trzeba zdecydować, czy Kontroler widzi kolejki wszystkich VM projektu w jednym miejscu. | #20, #33 |
| Hub | Zostaje wieloużytkownikowy (badacz i Administrator Klienta). Przy C izolacja między badaczami na jednej VM pozostaje granicą bezpieczeństwa (testy tester1/tester2). | — |
| Wspólny katalog zespołu | §10 wymaga katalogu wspólnego dla członków zespołu. Przy C potrzebny także **w jednej VM** (dziś go nie ma). | #50 |
| Rola Administratora Klienta | Przy kilku badaczach na VM rośnie znaczenie tego, że rola admina huba daje dostęp do serwerów i plików badaczy. | #51 |
| Koszty | Liczba VM = liczba aktywnych badaczy. Ma to wpływ na budżet projektu (§11) i wyłączanie nieużywanych pulpitów (§9). | — |
| Specyfikacja | Aktualizacja `WLB_Specs.txt`: „jedna VM per badacz” zamiast „jedna VM per Laboratorium … wszyscy badacze jako osobni użytkownicy Hub”. | — |
| Testy | Testy izolacji dwóch badaczy (tester1/tester2) zostają jako obrona w głębi. Dochodzi test współdzielonego systemu plików między dwiema VM (po #19). | #19 |

## Pytania do Właściciela Platformy

1. ~~Model VM~~: wariant **C** potwierdzony przez zespół projektu (2026-10-01). Do zatwierdzenia przez Właściciela Platformy.
2. Czy domyślne przeliczniki (pula / `RESEARCHERS_PER_VM`, rezerwa max(3 GB, 10% RAM)) są akceptowalne?
3. Jak wygląda współdzielony system plików projektu w modelu A (#19): jeden udział na projekt, montowany w każdej VM zespołu, z jakimi prawami?
4. Czy kolejka eksportu ma być wspólna dla projektu (wszystkie VM), czy per VM (#20)?

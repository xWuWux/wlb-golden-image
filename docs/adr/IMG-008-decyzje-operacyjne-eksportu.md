# IMG-008: Decyzje operacyjne eksportu/śluzy wyjściowej przed produkcją

* **Status:** Przyjęta
* **Data:** 2026-10-29
* **Autorzy / decyduje:** Właściciel Platformy
* **Powiązania:** Regulamin: §14.7, §24 · OPZ: śluza/eksport · IP_CMC: ADR 5.1 VirtualLab · Zgłoszenia/PR: #162 (to zgłoszenie), #147 (akceptacja warunkowa), #20, #19, #32, #17, #102, #33, #143 · Pliki: `ansible/roles/storage/files/wlb-sluza-out-mover`, `ansible/roles/storage/files/wlb-export-snapshot`, `ansible/roles/lab_config/files/wlb-firstboot`

## Kontekst i problem

Ograniczenia snapshotu/manifestu eksportu (#147) zostały **zaakceptowane warunkowo** na czas przyspieszenia dostawy. #162 zebrało decyzje operacyjne do rozstrzygnięcia **przed produkcją**, żeby akceptacja „na teraz" nie przeniosła ich na pierwszy realny incydent. Ten ADR je rozstrzyga.

Fakt tła kształtujący decyzje: **`RESEARCHERS_PER_VM` domyślnie = 1** (IMG-001: VM na badacza), konfigurowalne 1–64. Mechanika movera (`wlb-sluza-out-mover`): pojedynczy `flock`, sekwencyjny sweep; każdy pozostawiony `.incoming.*` (przerwany transfer/kopia) zatrzymuje sweep dla wszystkich (**fail-stop**). Limit wniosku: `MAX_BYTES = 100 GiB`, `MAX_ENTRIES = 100 000` (`wlb-export-snapshot`). EXDEV (rename między systemami plików) jest już obsłużony defensywnie (nie usuwa częściowej kopii, nie ponawia automatycznie).

## Rozważane opcje

Per punkt — pełne warianty w #162. Poniżej skrót rozważań; decyzje w następnej sekcji.

1. **Kolejka/limit:** /workspace jak dziś vs osobny wolumen od zaraz vs /workspace bez wymogu zmiany.
2. **Fail-stop:** zaakceptować (z alarmem) vs zaakceptować z twardym capem 1/VM vs zbudować kwarantannę per-wniosek od razu.
3. **Informacja zwrotna:** katalog „odrzucone/" z powodem vs pełna maszyna stanów od razu vs tylko syslog.
4. **Rejestr konto→osoba (#102):** przed vs po uruchomieniu self-service eksportu (#20).
5. **E2E na docelowym storage** oraz **śledztwo supply-chain** (pad sumy pakietu w CI).

## Decyzja

### 1. Kolejka na `/workspace` + limit 100 GiB — **MVP na /workspace, osobny wolumen przed produkcją**
Na MVP (pilot) kolejka zostaje na `/workspace` z limitem 100 GiB na wniosek **oraz kontrolą zapasu miejsca przed przyjęciem** (mover nie stageuje wniosku, który mógłby wywołać ENOSPC katalogów domowych). **Przed produkcją wymagany osobny wolumen kolejki** (montowany, poza `/workspace`) — śledzone w #19. Transfery **> 100 GiB** obsługuje **osobny proces operatorski**, nie self-service śluzy.

### 2. Fail-stop vs kwarantanna — **akceptacja fail-stop dla MVP + alarm; kwarantanna wymagana przed >1 badacza/VM**
Przy domyślnym `RESEARCHERS_PER_VM=1` fail-stop dotyka wyłącznie samego badacza (brak wektora DoS na kolegów i head-of-line między użytkownikami). Akceptujemy go dla MVP. **Warunki akceptacji:**
* zablokowany `.incoming.*` **musi** generować zdarzenie w kontrakcie obserwowalności → **alarm SIEM** + procedura **dyżuru** operatora;
* **kwarantanna per-wniosek** (izolacja błędnego wniosku bez mrożenia reszty) jest **twardym warunkiem wstępnym** przed włączeniem `RESEARCHERS_PER_VM > 1` w jakimkolwiek Laboratorium. Do czasu jej dostarczenia multi-user VM wymaga świadomej, odnotowanej akceptacji ryzyka właściciela Laboratorium.

### 3. Informacja dla badacza — **katalog „odrzucone/" z powodem (MVP); pełna maszyna stanów = schema v2**
Minimalny widoczny status: odrzucony/kwarantannowany wniosek trafia do **zwrotnego katalogu widocznego dla badacza** z **plikiem powodu** (`reason=`), zamiast znikać tylko do syslog. Łapie realne legity-pady: hardlink z katalogu domowego, plik z `/data-mart` z właścicielem root → mieszany właściciel → odrzucenie całości. Pełna maszyna stanów wniosku (`approved`/`rejected`/`published`) to **`schema_version: 2`**, poza MVP.

### 4. Rejestr konto→osoba (#102) — **przed uruchomieniem self-service eksportu (#20)**
Manifest atrybuuje `requester=jupyter-<login>` (UID konta, nie osoba — IMG-002/006/007). **Rejestr konto→osoba→daty (#102) musi istnieć zanim #20 (self-service eksport) wejdzie na produkcję** — inaczej audyt nie udowodni „dr X wyeksportowała Y". Twarda kolejność: rejestr → #20, nie odwrotnie.

### 5a. E2E na docelowym storage — **wymagane przed produkcją, osobno od CI**
PR jest bezpieczny na lokalnym ext4, ale NFS/Ceph zmieniają semantykę `inotifywait`/`flock`/`rename`/`mv` (**EXDEV**). **Wymagany osobny E2E na realnym backendzie storage** (ta sama klasa co produkcja) przed startem produkcyjnym — decyzja architektoniczna, nie checkbox CI. Śledzone w #19.

### 5b. Supply-chain (pad sumy pakietu) — **hash-pinning `--require-hashes` w CI**
`ci/requirements-unit.txt` pinuje wersje, ale **nie hashe**. „Niezgodna suma pobranego pakietu" to kontrola pip (pobrane bajty ≠ suma z indeksu PyPI): uszkodzone pobranie / popsute lustro / manipulacja. Przeszłego transientu nie przypiszemy po fakcie; **rozwiązaniem klasy problemu jest hash-pinning** — każda przyszła niezgodność staje się deterministycznym, audytowalnym sygnałem. Wdrożyć `--require-hashes` z `--hash=sha256:...` per pakiet (generowane pip-tools/hashin) dla wymagań CI.

### Granice (zaakceptowane jako znane; poza zakresem #147)
Kopia eksportu: nie transakcja aplikacyjna (#33), nie WORM, nie weryfikuje anonimizacji; `fsync`/rename nie dowodzą odporności na utratę zasilania. **Format kolejki v1 (`sang256-inventory-v1`, pakiet payload+manifest) zamrażamy i tagujemy teraz**; maszyna stanów = `schema_version: 2`.

## Odstępstwo od specyfikacji

* **Czy stanowi odstępstwo:** Nie — doprecyzowuje operacyjnie kontrolę eksportu (§14.7/§24) i warunki jej bezpiecznego uruchomienia; nie osłabia żadnego wymogu Regulaminu.

## Konsekwencje

* **Pozytywne:** jawne, odnotowane warunki startu MVP; ryzyka (fail-stop, ENOSPC, atrybucja) są zaakceptowane świadomie z twardymi warunkami wstępnymi na produkcję, nie przemilczane; supply-chain CI zyskuje audytowalną kontrolę.
* **Negatywne / dług techniczny — obowiązki wygenerowane przez te decyzje:**
  * [ ] Alarm SIEM na zablokowany `.incoming.*` + procedura dyżuru (pkt 2) — kontrakt obserwowalności (#17).
  * [ ] Kwarantanna per-wniosek — warunek przed `RESEARCHERS_PER_VM>1` (pkt 2, #32).
  * [ ] Kontrola zapasu miejsca przed przyjęciem wniosku + osobny wolumen kolejki przed prod + proces > 100 GiB (pkt 1, #19).
  * [ ] Zwrotny katalog „odrzucone/" z plikiem powodu (pkt 3).
  * [ ] Zależność: rejestr #102 przed uruchomieniem #20 (pkt 4).
  * [ ] E2E na NFS/Ceph przed produkcją (pkt 5a, #19).
  * [ ] Hash-pinning `--require-hashes` w CI (pkt 5b).
  * [ ] Zamrożenie i tag formatu kolejki v1 (granice).
* **Świadomie pominięte na MVP:** osobny wolumen od zaraz, pełna maszyna stanów wniosku, kwarantanna per-wniosek dla domyślnego 1/VM — odłożone z jawnymi warunkami wyzwalającymi (produkcja / `RESEARCHERS_PER_VM>1`).

# RB-08: Zamknięcie Laboratorium — trwałe usunięcie

**Rola:** Administrator Platformy / Operator Storage
**Odniesienia:** Regulamin §17.1, §22; BP-VL-3.4; IMG-006; #13, #19
**Zależności:** decyzja Lidera Projektu, potwierdzenie IOD, storage (#19), kopie zapasowe (§22), kolejka eksportu (RB-eksport-kolejka)

> Procedura techniczna na VM; proces/decyzje należą do platformy i Lidera.

> **WARUNEK WSTĘPNY — STATUS IMG-006: „DO POTWIERDZENIA PRZEZ IOD”.**
> Decyzja IMG-006 nie jest wiążąca bez pisemnego potwierdzenia IOD (interpretacja RODO).
> Nie wykonuj nieodwracalnych operacji z sekcji 5–6 przed tym potwierdzeniem.

## 1. Fakty (zweryfikowane w kodzie)

| Element | Wartość | Źródło |
|---|---|---|
| Dysk roboczy `/workspace` | **`/dev/vdb`**, ext4, `LABEL=workspace`; montowany jako `/workspace` | `cloud-init/lab-user-data.example.yaml` (`disk_setup`, `fs_setup`, `mounts`) |
| Kolejka eksportu | `WLB_EXPORT_QUEUE` z `/etc/wlb/image.conf` = **`/workspace/.wlb-export-queue`** | `ansible/roles/lab_config/tasks/main.yml`; `ansible/group_vars/all.yml` (`wlb_export_queue_dir`) |
| Baza huba (konta, hasła) | **`/workspace/.wlb-hub/jupyterhub.sqlite`** | `ansible/group_vars/all.yml` (`tljh_hub_db_path`); `ansible/roles/tljh/templates/10-wlb.py.j2` |
| Kopie bazy huba | `/workspace/.wlb-hub/backup/` | `hub_db_backup_dir` |
| Udziały Laboratorium | `/sluza-in` (ro), `/sluza-out` (rw), `/data-mart` (ro), `/projekt` (rw), `/docs` (ro) — CephFS/NFS | `cloud-init/lab-user-data.example.yaml` |
| Mechanizm crypto-erase | **BRAK w obrazie** — żaden skrypt/rola nie niszczy klucza wolumenu; to operacja storage (#19) | przegląd `ansible/`, `cloud-init/`, `tests/`, `ci/` — temat występuje wyłącznie w ADR IMG-006 |

**Kluczowe:** obraz używa `/workspace` jako osobnego wolumenu (`/dev/vdb`). Dysk systemowy jest jednorazowy, ale dane projektu, baza huba i kolejka eksportu żyją na `/workspace` i udziałach storage. „Trwałe usunięcie” nie polega więc na `rm -rf` ani `wipefs` na VM — wymaga zniszczenia klucza wolumenu po stronie storage i purge kopii.

## 2. Warunki wstępne

1. **Decyzja Lidera Projektu o zamknięciu** — pisemna, z zakresem: ID Laboratorium, właściciel danych, data zamknięcia, czy dopuszczono archiwizację (sekcja 4).
2. **Potwierdzenie IOD** — bez niego status IMG-006 pozostaje „do potwierdzenia”; nie wykonuj kroków nieodwracalnych.
3. **Zapis decyzji** w rejestrze zamknięć/ADR oraz w systemie zgłoszeń; wskaż osoby odpowiedzialne za VM, storage, kopie i IOD.
4. **Inwentaryzacja przed usunięciem** — zapisz identyfikatory: wolumen `/workspace`, udziały Ceph/NFS, zestawy kopii i snapshoty, klucz szyfrowania wolumenu.
   ```sh
   findmnt /workspace
   lsblk -o NAME,LABEL,SIZE,FSTYPE,MOUNTPOINT
   ```
5. **Brak aktywnych sesji** — poinformuj badaczy i wstrzymaj dostęp do Laboratorium; sesje i tak wygasają maksymalnie po 12 h (§9.5).

## 3. Eksport końcowy

1. Dokończ i zweryfikuj kolejkę eksportu zgodnie z [RB-eksport-kolejka](RB-eksport-kolejka.md). Nie usuwaj pakietów `pending_review` ani pozostałości `.incoming.*` — najpierw wyjaśnij je z Kontrolerem Przesyłu Danych.
2. Sprawdź, że nie ma oczekujących wniosków:
   ```sh
   q=$(sed -n 's/^WLB_EXPORT_QUEUE=//p' /etc/wlb/image.conf)
   printf '%s\n' "$q"
   ls -A "$q"
   systemctl status wlb-sluza-out.service --no-pager
   ```
   Puste `ls -A` oznacza brak wniosków. Każdy pakiet lub `.incoming.*` to zatrzymanie procedury do czasu wyjaśnienia.
3. Zapisz dowód zakończenia eksportu: listę UUID/hashy przekazanych pakietów, odbiorcę i datę. Dopiero potem przejdź do kroków nieodwracalnych.

## 4. Decyzja o archiwizacji

1. **Domyślnie: BRAK archiwizacji** — §17.1 wymaga trwałego usunięcia „bez dalszej archiwizacji”.
2. Archiwizacja jest **wyjątkiem tylko na jawną decyzję Lidera Projektu** (BP-VL-3.4) i trafia wyłącznie do repozytorium instytucjonalnego. Udokumentuj: zakres, podstawę decyzji, miejsce, retencję i osobę odbierającą.
3. Jeśli archiwizacja jest wykonywana: eksport musi być kompletny i zweryfikowany (hash), a kopia nie może omijać purge danych pierwotnych i kopii §22. Archiwizacja nie przedłuża życia danych na wolumenie Laboratorium.
4. Brak decyzji o archiwizacji odnotuj wprost w rejestrze zamknięcia.

## 5. Tombstone i crypto-erase danych pierwotnych

1. **Oznacz projekt jako zamknięty (tombstone)** w rejestrze: ID Laboratorium, data, decyzje Lidera/IOD, wolumeny, klucze, zestawy kopii, termin purge (sekcja 6). Tombstone muszą honorować systemy kopii — mechanizm po stronie platformy/storage (#19), nie obrazu.
2. **Strona VM (operator):** zatrzymaj usługi i odmontuj wolumen przed odłączeniem; nie wykonuj na nim operacji rzekomo „czyszczących”.
   ```sh
   sudo systemctl stop jupyterhub traefik wlb-sluza-out.service
   sudo fuser -vm /workspace    # upewnij się, że nikt nie używa
   sudo umount /workspace
   ```
   Następnie zatrzymaj VM z hypervisora i odłącz wolumen `/workspace` (oraz udziały projektu) zgodnie z procedurą platformy.
3. **Strona storage (#19):** zniszcz **klucz szyfrowania wolumenu** `/workspace` (Ceph key / klucz LUKS) — po zniszczeniu klucza dane pierwotne są nieczytelne. Lokalnie, bez Ceph: zniszcz klucz/dysk lokalny zgodnie z procedurą storage; bez szyfrowania pozostaje fizyczne zniszczenie nośnika.
4. **Nie traktuj `shred`, `wipefs`, `blkdiscard` ani `rm -rf` jako crypto-erase.** Na storage thin-provisioned/SSD nie dają gwarancji nieodtwarzalności. Operator VM nie ma w obrazie mechanizmu crypto-erase — przekazuje storage identyfikator wolumenu i klucza.
5. Zapisz dowód: ID wolumenu, ID klucza, operator, data i potwierdzenie z storage.

## 6. Wymuszony purge kopii §22 w ≤30 dni

1. Ustal **termin purge = data zamknięcia + maksymalnie 30 dni** i wpisz go do rejestru oraz do systemu kopii.
2. Oznacz tombstone wszystkie kopie i snapshoty: snapshoty Ceph/NFS, zestawy backupu, kopie bazy huba, ewentualne kopie pakietów eksportu. Wyłącz harmonogram backupów dla zamkniętego Laboratorium, żeby nie tworzyły nowych kopii po zniszczeniu klucza.
3. System kopii ma **wymusić usunięcie** w oknie retencji. Dłuższa retencja dla zamkniętych projektów jest **świadomie pominięta** (IMG-006); §22 jest operacyjnym DR z ograniczonym oknem, nie trwałą archiwizacją.
4. Po ≤30 dniach kopie nie mogą istnieć, a dane pierwotne pozostają nieodtwarzalne. Potwierdzenie purge zapisz jako dowód zamknięcia.

## 7. Weryfikacja i ślad audytowy

1. Po ≤30 dniach sprawdź: klucz nie istnieje, wolumen jest odłączony i oznaczony jako zniszczony, snapshoty i zestawy kopii zostały usunięte, kolejka eksportu jest pusta, a próba odtworzenia nie znajduje źródła. Nie wykonuj restore do środowiska produkcyjnego.
2. Wyślij zdarzenia do SIEM przez kanał logów/audytu platformy: start zamknięcia, zniszczenie klucza, purge kopii, zakończenie. Zachowaj tickety i raporty storage/backup.
3. Zamknij wpisy w rejestrze: Laboratorium, storage, kopie, IOD. Jeżeli purge nie może być potwierdzony w terminie — zgłoś incydent wg RB-09 i eskaluj; nie zamykaj sprawy jako zakończonej.

## Powiązania

- [IMG-006](../adr/IMG-006-zamkniecie-laboratorium-usuwanie.md) — decyzja „trwałe usunięcie” (crypto-erase + ograniczony purge); status **do potwierdzenia przez IOD**.
- Regulamin §17.1 (trwałe usunięcie bez dalszej archiwizacji) i §22 (kopie zapasowe, retencja).
- BP-VL-3.4 — archiwizacja tylko na jawną decyzję Lidera Projektu (wyjątek).
- #19 — storage: szyfrowanie wolumenów, zniszczenie klucza, snapshoty i tombstone.
- #13 — runbooki operacyjne cyklu życia Laboratorium.
- [RB-eksport-kolejka](RB-eksport-kolejka.md) — zamknięcie i weryfikacja kolejki eksportu.
- RB-07 (DR) — odtwarzanie po awarii; nie zastępuje purge zamkniętego projektu.
- RB-09 (incydenty) — eskalacja, gdy purge lub zniszczenie klucza nie przebiega zgodnie z procedurą.

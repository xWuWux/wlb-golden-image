# IMG-006: Zamknięcie Laboratorium — „trwałe usunięcie" (crypto-erase + ograniczony purge kopii)

* **Status:** Przyjęta (do potwierdzenia przez IOD)
* **Data:** 2026-10-23
* **Autorzy / decyduje:** Właściciel Platformy (potwierdzenie zgodności: IOD / właściciel Regulaminu)
* **Powiązania:** Regulamin: §17.1, §22 · Analiza: BP-VL-4 → BP-VL-3.4 · Zgłoszenia/PR: #117, #19 (storage), #13 (RB-08) · Pliki: runbook RB-08 (do napisania)

## Kontekst i problem

Przy zamknięciu projektu trzy źródła są sprzeczne i blokują RB-08: §17.1 („trwałe usunięcie **bez dalszej archiwizacji**"), §22 (kopie zapasowe, retencja **≥30 dni**), BP-VL-3.4 (zamknięcie obejmuje **archiwizację** środowisk/obrazów). Nie da się napisać deterministycznej procedury bez rozstrzygnięcia, co „trwałe usunięcie" znaczy wobec obowiązkowej retencji i archiwizacji.

## Rozważane opcje

1. **Crypto-erase + ograniczony purge** — trwałe usunięcie = zniszczenie danych pierwotnych (klucz wolumenu) + wymuszony purge kopii §22 w ≤30 dni (tombstone); archiwizacja tylko na decyzję Lidera.
2. **Archiwizacja domyślna (BP-VL-3.4 wygrywa)** — domyślnie archiwizujemy; sprzeczne z §17, cięższe dla RODO.
3. **Eskalacja do IOD** bez decyzji teraz.

## Decyzja

**Opcja 1.** „Trwałe usunięcie" (§17) = **crypto-erase danych pierwotnych** (zniszczenie klucza wolumenu — sprawa storage, #19) **+ wymuszony purge kopii zapasowych** §22 w oknie retencji, tak że po **≤30 dniach** dane są nieodtwarzalne; zamknięty projekt dostaje **tombstone**, honorowany przez kopie. **Archiwizacja (BP-VL-3.4) tylko** na jawną decyzję Lidera Projektu (wyjątek §17), do repozytorium instytucjonalnego. §22 dokumentujemy jako **operacyjne DR z ograniczonym oknem**, nie trwałą archiwizację; 30 dni = maksymalny czas „życia po usunięciu". Status **do potwierdzenia przez IOD** (interpretacja RODO).

## Odstępstwo od specyfikacji

* **Czy stanowi odstępstwo:** Częściowe wobec BP-VL-3.4 — archiwizacja środowiska nie jest domyślna, tylko na decyzję Lidera. Uzasadnienie: nadrzędność §17.1 („bez dalszej archiwizacji") i minimalizacja danych (RODO).

## Konsekwencje

* **Pozytywne:** odblokowuje RB-08 (#13) i DoD EOL/retirement; deterministyczna procedura; zgodność z minimalizacją danych.
* **Negatywne / dług techniczny:** wymaga wsparcia storage — crypto-erase/zniszczenie klucza wolumenu i mechanizm tombstone w kopiach (#19); lokalnie (bez Ceph) = zniszczenie klucza/dysku lokalnego i purge lokalnych kopii. Potwierdzenie IOD przed uznaniem za wiążące.
* **Świadomie pominięte:** domyślna archiwizacja środowiska; retencja kopii dłuższa niż okno §22 dla zamkniętych projektów.

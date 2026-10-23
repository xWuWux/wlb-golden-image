# IMG-003: Zakres uprawnień Administratora Klienta w hubie — rola ograniczona + wykrywanie

* **Status:** Przyjęta
* **Data:** 2026-10-23
* **Autorzy / decyduje:** Właściciel Platformy
* **Powiązania:** Regulamin: §19, §21, §25, §26 · IP_CMC: OPZ B.20 (rozdzielenie ról) · Zgłoszenia/PR: #51, #18, #13 · Pliki: `ansible/roles/lab_config/files/wlb-firstboot`, `ansible/roles/tljh/templates/10-wlb.py.j2`, `observability/contract.yml`

## Kontekst i problem

Administrator Klienta jest dziś administratorem huba (pełna rola `admin` TLJH). W JupyterHub 5.5.2 `admin` obejmuje `access:servers` (wejście do serwera dowolnego badacza — jego pliki, terminal, kernele), `tokens` (token w imieniu badacza), `admin:users` (zmiana hasła, nadanie admina) i `admin:servers`. Regulamin definiuje rolę Administratora Klienta jako zarządzanie środowiskiem i nadawanie uprawnień — **bez dostępu do danych badaczy** (§26 poufność, §19 najmniejsze uprawnienia, §21/§25 rozliczalność).

## Rozważane opcje

(pełna macierz zagrożeń Z1–Z7 i wariantów A–E w #51)
1. **A** — bez zmian (pełny `admin`). Z1–Z5 pozostają.
2. **B+E** — własna rola bez `access:servers` i `tokens`, z `admin:users`/`admin:servers`; + zdarzenia wykrywające w kontrakcie obserwowalności.
3. **C** — Administrator Klienta bez roli huba; zatwierdzanie/reset robi administrator platformy na wniosek.
4. **D** — konta/grupy w IdP (zależne od #18).

## Decyzja

**Opcja B+E.** Administrator Klienta dostaje **rolę ograniczoną**: zatwierdzanie kont (`admin:users`), zarządzanie serwerami (`admin:servers`), panel/lista — **bez `access:servers` i `tokens`**, więc nie wchodzi do serwera badacza ani nie działa jego tokenem (eliminuje Z1–Z3). Pozostające ryzyka (Z4 zmiana hasła, Z5 eskalacja) są **wykrywane**: zdarzenia „wejście admina do serwera innego użytkownika", „utworzenie tokenu", „zmiana hasła przez admina", „nadanie roli" trafiają do kontraktu obserwowalności i alertu SIEM. Docelowo (po #18) migracja do D.

## Odstępstwo od specyfikacji

* **Czy stanowi odstępstwo:** Nie — realizuje §19/§26 i rozdzielenie ról OPZ B.20, których pełny `admin` nie spełniał.

## Konsekwencje

* **Pozytywne:** poufność danych badacza (brak wglądu i działania w jego imieniu); rozliczalność przez wykrywanie; Administrator Klienta nadal sam zatwierdza konta (niski koszt operacyjny vs wariant C).
* **Negatywne / dług techniczny:** trzeba zweryfikować, że panel admina i `/hub/authorize` działają bez pełnej roli; Z4/Z5 możliwe (choć wykrywane); nowe zdarzenia w kontrakcie + test etapu 5 „Administrator Klienta nie otwiera serwera badacza".
* **Świadomie pominięte:** wariant C (pełna eliminacja Z4/Z5) — odrzucony dla kosztu operacyjnego; D czeka na IdP (#18).

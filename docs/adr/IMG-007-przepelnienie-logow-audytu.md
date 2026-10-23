# IMG-007: Polityka przy przepełnieniu kolejki logów / dysku audytu — ciągłość + głośny alert

* **Status:** Przyjęta
* **Data:** 2026-10-23
* **Autorzy / decyduje:** Właściciel Platformy
* **Powiązania:** Regulamin: §21 · Zgłoszenia/PR: #32, #17 (reguły SIEM), #22 (monitoring), #4 · Pliki: `ansible/roles/logging/tasks/main.yml`, `ansible/roles/audit/tasks/main.yml`, `wlb-firstboot` (omfwd), `observability/contract.yml`

## Kontekst i problem

Dwa niezależne tryby awarii dają dziury w logu centralnym (§21) bez sygnału: (1) **SIEM niedostępny** → kolejka rsyslog się zapełnia, a przy domyślnym `queue.timeoutEnqueue=2s` **blokuje całe lokalne logowanie** (potwierdzone w VM: lokalny syslog staje na 60 s), po czym zdarzenia są cicho odrzucane; (2) **brak miejsca na dysku** → auditd zawiesza zapis (`admin_space_left_action=SUSPEND`) i **nie wznawia sam** po zwolnieniu miejsca. O odrzuceniach rsyslog nie ma żadnego komunikatu.

## Rozważane opcje

1. **Ciągłość + alert** — nie blokować lokalnego logowania ani pracy; gubić tylko forwarding do SIEM, ale głośno alarmować; auto-resume auditd.
2. **Kompletność audytu** — blokować nowe sesje / `disk_full_action=halt`, gdy audyt nie zapisuje. Zero luk, ryzyko DoS badaczy.
3. **Hybryda** — ciągłość dla forwardingu SIEM, kompletność (blokada) dla lokalnego zapisu audytu.

## Decyzja

**Opcja 1 — ciągłość + głośny alert.** `queue.timeoutEnqueue=0`, żeby niedostępny SIEM **nie blokował lokalnego logowania** (naprawa obecnego błędu); zdarzenie „kolejka SIEM > X% / odrzucono zdarzenia" w kontrakcie obserwowalności i w monitoringu (#22); **auto-resume auditd** po zwolnieniu miejsca. Przy awarii SIEM gubimy forwarding (lokalny `audit.log` i praca badaczy trwają), a luka w SIEM jest zaalarmowana.

## Odstępstwo od specyfikacji

* **Czy stanowi odstępstwo:** Nie — realizuje rozliczalność §21 przez alertowanie luki zamiast cichej utraty; świadomie wybieramy ciągłość pracy nad twardą blokadą.

## Konsekwencje

* **Pozytywne:** koniec patologicznego blokowania lokalnego logowania; brak DoS badaczy przy awarii infry; luki w SIEM są widoczne (alert), a nie ciche.
* **Negatywne / dług techniczny:** przy długiej awarii SIEM zdarzenia odrzucone **nie są dosyłane** (rsyslog nie czyta journala wstecz) — akceptujemy, bo są zaalarmowane; kolejka leży na dysku systemowym, więc wymiana VM w trakcie awarii kasuje niedostarczone (jak #4). Do zrobienia: reguła SIEM (#17) na komunikat auditd, test etapu 5 „SIEM niedostępny → brak luk albo alert".
* **Świadomie pominięte:** halt/blokada sesji (opcja 2) — odrzucone dla ryzyka DoS; dosyłanie odrzuconych zdarzeń z journala.

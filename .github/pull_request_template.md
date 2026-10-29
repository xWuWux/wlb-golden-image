<!-- WLB golden image — szablon PR. Usługa regulowana (Tier 4): zob. CONTRIBUTING.md. -->

## Co i po co
<!-- Zwięźle: jaki problem rozwiązuje ten PR. Podlinkuj zgłoszenie. -->
Zamyka #

## Jak przetestowano
<!-- Które testy to pilnują i jak je uruchomić. -->

## Lista kontrolna
- [ ] **Regresja:** dodano test, który **pada przed** i **przechodzi po** tej zmianie
      (poprawka błędu/nowa funkcja). Jeśli nie dotyczy — uzasadnij poniżej.
- [ ] Test oznaczony numerem zgłoszenia `#NN` (tytuł testu lub nagłówek sekcji) i mapa
      odświeżona: `python3 ci/mapa-testy.py`.
- [ ] Test jest hermetyczny (lokalne zaślepki/atrapy, bez zasobów zewnętrznych).
- [ ] Dokumentacja zaktualizowana w tym PR (README / runbook / `lab.env.example`), jeśli
      zmienia się zachowanie lub konfiguracja.
- [ ] Kontrakt obserwowalności (`observability/contract.yml`) zaktualizowany, jeśli zmieniają
      się zdarzenia/pola telemetrii (etap 3.5 i tak zablokuje rozjazd).
- [ ] Nowa zmienna wdrożeniowa dodana w trzech miejscach: `wlb-firstboot`, `cloud-init/lab.env.example`
      i przykład `cloud-init/lab-user-data.example.yaml` (etap 3.5 i tak zablokuje rozjazd).
- [ ] Zmiana wrażliwa (audyt, uwierzytelnianie, sieć, proces wydania, dane) — oznacz, bo wymaga
      przeglądu właściciela obszaru (CODEOWNERS, #59).

<!-- „Nie dotyczy” dla regresji — uzasadnienie (np. sama dokumentacja, zmiana pinu zależności): -->

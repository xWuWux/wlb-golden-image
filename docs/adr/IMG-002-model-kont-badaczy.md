# IMG-002: Model kont badaczy — bezosobowe konta stanowiskowe (uNN)

* **Status:** Przyjęta
* **Data:** 2026-10-23
* **Autorzy / decyduje:** Właściciel Platformy
* **Powiązania:** Regulamin: §21 · RODO · IP_CMC: Standard nazewnictwa WLB (v0.3) · Zgłoszenia/PR: #102, #57 (OIDC), #18, #30 · Pliki: `ansible/roles/tljh/files/wlb-hub-user`, `ansible/roles/lab_config/files/wlb-firstboot`

## Kontekst i problem

Standard nazewnictwa WLB (v0.3) nakazuje konta **bezosobowe**: stanowiskowe `wlb-<kod>-<nn>-uNN`, Administrator Klienta `-a01`, a mapowanie osoba↔konto trzyma w **rejestrze (z datami), nigdy w nazwie**. Liczba kont = zatwierdzona liczba użytkowników; nowa osoba przejmuje konto stanowiskowe (reset poświadczeń). Obraz ma dziś konta **nazwane** (`jupyter-<login>`, NativeAuthenticator/`wlb-hub-user`). To rozjazd modelu wymagający rozstrzygnięcia przed wpuszczeniem badaczy.

## Rozważane opcje

1. **Nazwane; standard na warstwie IdP/rejestru** — konta systemowe zostają `jupyter-<login>`, mapowanie w rejestrze/IdP. Najlepsza rozliczalność, czyste mapowanie OIDC, bez przepisywania.
2. **Bezosobowe `uNN`/`a01` (pełny standard)** — konta stanowiskowe, mapowanie wyłącznie w rejestrze. Dosłowna zgodność ze standardem.
3. **Hybryda** — `uNN` systemowo + utrzymywany rejestr + procedura przejęcia.

## Decyzja

**Opcja 2 — konta bezosobowe `uNN` / Administrator `a01`, zgodnie ze Standardem nazewnictwa WLB.** Mapowanie osoba↔konto↔daty utrzymuje **rejestr** (poza nazwą konta); przejęcie konta przez nową osobę = reset poświadczeń z wpisem do rejestru i śladem audytu. Rozliczalność RODO/§21 realizuje korelacja przez rejestr, nie przez nazwę w logach.

## Odstępstwo od specyfikacji

* **Czy stanowi odstępstwo:** Nie — przeciwnie, dostosowuje obraz do Standardu nazewnictwa WLB, od którego obecny model nazwany odbiegał.

## Konsekwencje

* **Pozytywne:** zgodność ze standardem IP_CMC; stała, przewidywalna liczba kont = zatwierdzeni użytkownicy; brak danych osobowych w nazwach kont/logach.
* **Negatywne / dług techniczny:** realne przepisanie modelu kont — `wlb-hub-user` (tworzenie `uNN`), katalogi domowe `/workspace/<konto>`, odtwarzanie kont w `wlb-firstboot`, backup w bazie huba, **rejestr osoba↔konto↔daty** i procedura przejęcia. Mapowanie na OIDC (#57/#18): claim tożsamości → stałe konto stanowiskowe `uNN`. Do rozpisania jako zadania wdrożeniowe (zgłoszenie potomne #102).
* **Świadomie pominięte:** nie utrzymujemy jednocześnie modelu nazwanego; migracja istniejących kont testowych `jupyter-*` → `uNN` jest częścią wdrożenia.

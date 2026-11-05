# Pomoc i zgłoszenia — Wirtualne Laboratorium Badawcze IP_CMC

## Wsparcie techniczne

Administrator IP_CMC zapewnia wsparcie techniczne **w dni robocze w godzinach 8:00–16:00**.

Zgłoszenia problemów technicznych kieruj do **HelpDesku IT GUMed**:

- e-mail: **helpdesk@gumed.edu.pl**

## Co dołączyć do zgłoszenia

Żeby przyspieszyć obsługę, w treści zgłoszenia podaj:

- **Laboratorium** i **login**, którym się logujesz,
- **co robiłeś** i **co się stało** (treść komunikatu błędu, jeśli jest),
- **datę i godzinę** wystąpienia problemu,
- **wersję obrazu** — jest w pliku `/etc/wlb/image-release` (otwórz go w JupyterLab albo w terminalu: `cat /etc/wlb/image-release`).

## Trwałość pracy, sesja i „reset" maszyny

Najważniejsze: **Twoja praca nie znika.** Katalog domowy (`~`, czyli `/workspace/jupyter-<login>`)
leży na osobnym **dysku roboczym** i przeżywa wszystko poza celowym usunięciem Laboratorium:

- **zamknięcie sesji po 12 h**, restart maszyny, a nawet **aktualizację obrazu do nowszej wersji**
  (nowa wersja = podmiana dysku **systemowego**; Twój dysk roboczy i pliki w `~` zostają nienaruszone).
  Dlatego dane sprzed wielu godzin czy wczoraj wciąż tam są — maszyna **nie resetuje się** sama w tle.
- **Zapis pracy = zapis do `~`.** Cokolwiek zapiszesz w katalogu domowym (notatniki, wyniki, skrypty)
  jest trwałe. **Nie musisz** kopiować niczego do `/sluza-out`, żeby zachować pracę.
- **`/sluza-out` służy wyłącznie do EKSPORTU** gotowych wyników poza Laboratorium (z zatwierdzeniem
  Kontrolera Przesyłu Danych) — to nie jest „miejsce zapisu", tylko brama na zewnątrz. Do codziennej
  pracy zapisuj do `~`, a przez śluzę przepuszczaj dopiero to, co ma opuścić maszynę.
- **Co ginie po 12 h / restarcie:** tylko to, co było **w pamięci** (uruchomiony serwer notebooków,
  zmienne w kernelu, niezapisane komórki). Pliki na dysku **zostają** — patrz checkpointy niżej.

## Długie obliczenia (limit sesji 12 h)

Sesja w Laboratorium trwa maksymalnie **12 godzin** (§9.5 Regulaminu) — po tym czasie serwer notebooków
jest zatrzymywany, a trzeba zalogować się od nowa. Krótka bezczynność (30 min) **nie** przerywa trwającego
obliczenia, ale **limit 12 h obowiązuje niezależnie od tego, że coś się liczy**. Obliczenie trwające dłużej
niż 12 h zostanie więc przerwane w połowie, a stan w pamięci przepadnie (pliki na dysku zostają).

Dopóki nie ma trybu obliczeń wsadowych, dla zadań dłuższych niż ~12 h stosuj **punkty kontrolne (checkpoint)
i wznawianie**:

- **Dziel pracę na etapy** i zapisuj wyniki pośrednie do swojego katalogu w `/workspace` (przeżywa wymianę
  obrazu i restart). Przykłady: `df.to_parquet(...)`, `np.save(...)`, `torch.save(...)`, `saveRDS(...)`.
- **Zapisuj co jakiś czas**, nie tylko na końcu — np. po każdej iteracji/epoce/partii danych, pod nazwą z
  numerem kroku (`model_krok_0007.pt`).
- **Przy wznowieniu** wczytaj najnowszy checkpoint i kontynuuj od niego, zamiast liczyć od zera.
- **Nie licz w jednej komórce przez wiele godzin bez zapisu** — po 12 h stracisz całość.

Jeśli Twoje obliczenia regularnie przekraczają 12 h i trudno je checkpointować, **zgłoś to HelpDeskowi** —
Twoje Laboratorium może dostać wydłużony limit sesji (patrz niżej).

## Wydłużona sesja (48 h na wniosek)

Domyślnie sesja trwa 12 godzin. Jeśli prowadzisz długie obliczenie, które się w tym nie mieści, możesz
**wnioskować o wydłużenie limitu do maksymalnie 48 godzin**. Wydłużenie ustawiane jest dla całego
Laboratorium (całej VM) i usuwa 12-godzinny limit jako przyczynę przerwania liczenia. Twoje zasoby
(RAM, CPU) się przy tym nie zmieniają.

> **WAŻNE: 48 godzin to NIE jest gwarancja, że nic nie przepadnie.** Wydłużony limit chroni tylko przed
> automatycznym zamknięciem sesji — **nie** czyni obliczenia odpornym na awarię. Stan w pamięci (jądro,
> zmienne, wynik w trakcie) **ginie bezpowrotnie** przy restarcie/reboocie VM, aktualizacji (wymianie)
> obrazu oraz awarii hosta. Reboot w 30. godzinie 48-godzinnego liczenia zabierze cały niezapisany
> postęp; pliki w `/workspace` zostają. Dlatego **regularny checkpoint do `/workspace` jest nadal
> konieczny**, niezależnie od długości sesji. Obliczenie trwające ponad 48 h i tak zostanie ucięte.

**Uwaga:** po wygaśnięciu sesji **zaloguj się ponownie**, a nie klikaj „Wyloguj" — wylogowanie
zatrzymuje serwer notebooków (`shutdown_on_logout=True`) i może przerwać niezapisane obliczenie.

**Jak wnioskować:** zgłoś się do **HelpDesku** lub do **Administratora Klienta** swojego Laboratorium.

## Eksport wyników — limity i odrzucenia

Wyniki eksportujesz przez `/sluza-out`. Po skopiowaniu plik znika z widoku i trafia do kolejki
zatwierdzenia — to **jeszcze nie jest eksport**: wniosek czeka na zgodę Kontrolera Przesyłu Danych.
Obowiązują ograniczenia operacyjne (decyzje IMG-008, §14.7/§24 Regulaminu):

- **Limit jednego wniosku: 100 GiB i 100 000 plików.** Większe transfery zgłoś operatorowi — idą
  osobnym trybem, nie przez śluzę.
- **Każdy plik/katalog to osobny wniosek.** Pliki należące do siebie spakuj w jedno archiwum przed
  kopiowaniem (`tar -czf ~/wynik.tar.gz ~/wyniki/ && cp ~/wynik.tar.gz /sluza-out/`).
- **Wniosek zostanie odrzucony**, jeśli zawiera dowiązania (symboliczne lub twarde), pliki specjalne
  albo pliki o **różnych właścicielach** — np. plik skopiowany z `/data-mart` należy do `root`, a nie
  do Ciebie. Skopiuj dane do siebie (`cp` tworzy kopię Twojej własności). Jeden niepasujący element
  odrzuca **cały** wniosek.
- **Powód odrzucenia** znajdziesz w katalogu **`/sluza-odrzucone`** (plik z wyjaśnieniem). Jeśli plik
  zniknął ze śluzy, a nie dotarł do operatora — zajrzyj tam najpierw.
- **Jeśli eksport w ogóle przestał działać** (nowe pliki nie znikają ze śluzy), wniosek mógł utknąć
  i wstrzymać kolejkę — **zgłoś HelpDeskowi**; operator odblokuje.

Zachowaj oryginał w katalogu domowym do czasu potwierdzenia eksportu. Automatyczny status wniosku,
zgoda Lidera i publikacja pozostają do wdrożenia (#20).

## Narzędzia w terminalu — osobne środowisko każdej karty (FSL, flavor radiologia)

Każdy **terminal** (zakładka terminala w JupyterLab lub na pulpicie) to **osobna powłoka z własnym
środowiskiem**. Zmienne (`PATH`, `FSLDIR`) ustawione w jednej karcie **nie przenoszą się** do innych
kart ani do już otwartych okien — w nowej karcie trzeba je ustawić ponownie.

Na flavorze **radiologia** narzędzia FSL (`fsleyes`, `fslmaths`, **`eddy`**, **`topup`** itd.) nie są
domyślnie na `PATH` w terminalu. Na początku pracy w danej karcie wczytaj środowisko FSL **jedną
komendą**:

```sh
source /etc/profile.d/fsl.sh
```

Po tym cały zestaw FSL działa w tej karcie (`fsleyes`, `eddy`, `topup`, `flirt`, …). Równoważnie,
gdybyś wolał ustawić to ręcznie:

```sh
export FSLDIR=/usr/local/fsl
. ${FSLDIR}/etc/fslconf/fsl.sh
export PATH=${FSLDIR}/share/fsl/bin:${PATH}
```

Żeby robić to automatycznie przy każdym nowym terminalu, dopisz `source /etc/profile.d/fsl.sh` do
pliku `~/.bashrc` (jest w Twoim katalogu domowym, więc **przeżywa** restart i wymianę obrazu).

> Aplikacje z **kafelków menu pulpitu** mają środowisko ustawione samodzielnie — powyższe dotyczy
> wyłącznie pracy z **terminala**. Jeśli kafelek nie startuje, zgłoś to HelpDeskowi (znany temat #199).

## Zanim zgłosisz

- Pełny Regulamin WLB: [`/docs/Regulamin_korzystania_z_WLB.pdf`](/docs/Regulamin_korzystania_z_WLB.pdf).
- Eksport wyników odbywa się wyłącznie przez katalog `/sluza-out` i wymaga zatwierdzenia przez Kontrolera Przesyłu Danych.
- Danych nie wolno pobierać na urządzenia osobiste ani wykonywać zrzutów ekranu z danymi medycznymi (§14, §24 Regulaminu).

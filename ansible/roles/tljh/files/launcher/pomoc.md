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
planowany jest tryb uruchamiania długich zadań odpięty od limitu sesji.

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

## Zanim zgłosisz

- Pełny Regulamin WLB: [`/docs/Regulamin_korzystania_z_WLB.pdf`](/docs/Regulamin_korzystania_z_WLB.pdf).
- Eksport wyników odbywa się wyłącznie przez katalog `/sluza-out` i wymaga zatwierdzenia przez Kontrolera Przesyłu Danych.
- Danych nie wolno pobierać na urządzenia osobiste ani wykonywać zrzutów ekranu z danymi medycznymi (§14, §24 Regulaminu).

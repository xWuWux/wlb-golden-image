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

## Zanim zgłosisz

- Pełny Regulamin WLB: [`/docs/Regulamin_korzystania_z_WLB.pdf`](/docs/Regulamin_korzystania_z_WLB.pdf).
- Eksport wyników odbywa się wyłącznie przez katalog `/sluza-out` i wymaga zatwierdzenia przez Kontrolera Przesyłu Danych.
- Danych nie wolno pobierać na urządzenia osobiste ani wykonywać zrzutów ekranu z danymi medycznymi (§14, §24 Regulaminu).

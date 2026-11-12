# Śluza eksportu: TYMCZASOWA procedura ręcznego wydania (do czasu #20)

> **Status: DRAFT — wymaga zatwierdzenia przez IOD i Lidera/Kontrolera Przesyłu Danych przed
> użyciem operacyjnym.** Procedura **zastępcza**, obowiązuje **tylko do wdrożenia #20** (automatyczna
> zgoda Lidera + publikacja). Wygasa z chwilą scalenia #20. Nie jest to bezpieczne API ani kanał dla
> sudo — korzysta z niej **operator z istniejącymi uprawnieniami root** po **udokumentowanej decyzji
> Kontrolera**. Dotyczy danych wrażliwych (m.in. radiologia) — obowiązuje polityka IOD i §14.7 Regulaminu.

Kontekst techniczny i format kolejki: [RB-eksport-kolejka.md](RB-eksport-kolejka.md).
Sprawdzanie statusu i zwrot dla badacza: [RB-sluza-zwrot-badaczowi.md](RB-sluza-zwrot-badaczowi.md).

## Zasady nadrzędne (nie pomijać)

1. **Rozdział obowiązków.** Wnioskodawca (badacz `uNN`) ≠ zatwierdzający (Kontroler/Lider) ≠ wykonawca
   (operator root). **Zakaz samozatwierdzania** — nikt nie zatwierdza i nie wydaje własnego wniosku.
2. **Przyjęcie do kolejki ≠ zgoda.** Wpis `pending_review` i potwierdzenie #208 **nie** są zgodą. Wydanie
   wymaga osobnej, pisemnej decyzji Kontrolera powiązanej z `request_id`.
3. **Integralność przed wydaniem.** Wydać można **wyłącznie** paczkę, która przeszła `verify` i której
   spis/rozmiar/sumy zgadzają się z tym, co zatwierdził Kontroler.
4. **Kanał wyjściowy zatwierdza IOD.** Konkretny nośnik/kanał „wyniesienia" ustala polityka instytucji
   (nie wymyślać ad hoc, nie kopiować na prywatny sprzęt).
5. **Wszystko jest audytowane.** Każdy krok ma ślad: kto, kiedy, `request_id`, `sha256`, odbiorca.

## Wymagania wstępne

- Operator z dostępem root/SSH do VM (admin-klienta `a01` **nie** wykonuje tej procedury — brak SSH,
  kolejka `root 0700`).
- Pisemna decyzja Kontrolera/Lidera (ticket / rejestr decyzji) z: `request_id`, celem, **odbiorcą**,
  podstawą zgody, oraz powiązaniem **konto `uNN` ↔ osoba** na datę wniosku (rejestr #102 nie jest
  wdrożony → wpis ręczny, zweryfikowany).
- Zatwierdzony przez IOD kanał wyjściowy i lokalizacja docelowa.

## Krok 1 — Decyzja Kontrolera/Lidera (przed dotknięciem danych)

1. Kontroler weryfikuje wniosek: ten sam **wynik/wersja**, **cel** i **odbiorca**, zgoda na zakres danych
   (w razie potrzeby: kontrola anonimizacji/źródła). Nie zatwierdza własnego wniosku.
2. Decyzja zapisana pisemnie i powiązana z **`request_id`** (nie z nazwą paczki — nazwa nie jest tożsamością).
3. Ustalony **odbiorca** i **kanał** (zatwierdzone przez IOD). Brak któregokolwiek → **stop**.

## Krok 2 — Weryfikacja techniczna (operator, root)

```sh
# 1. Zidentyfikuj paczkę po request_id z decyzji (NIE po nazwie):
sudo grep -rl '"request_id": *"<REQUEST_ID>"' /workspace/.wlb-export-queue/*/manifest.json

# 2. Zweryfikuj integralność (0 = spójny spis, rozmiary i sumy):
sudo /usr/local/sbin/wlb-export-snapshot verify /workspace/.wlb-export-queue/<PAKIET>

# 3. Porównaj z decyzją Kontrolera: liczba plików, łączny rozmiar, sha256, spis:
sudo cat /workspace/.wlb-export-queue/<PAKIET>/manifest.json   # entries, sha256, requester.uid, original_name

# 4. Skoreluj ze śladem przyjęcia w SIEM:
sudo journalctl -t wlb-sluza-out | grep '<REQUEST_ID przez queued_as/entry>'   # export_request ...
```

- `original_name` i zawartość to **dane niezaufane** — **nie wykonywać** (żadnych makr/skryptów), tylko podgląd.
- `verify` sprawdza spis/rozmiary/sumy, **nie** autentyczność metadanych zmienionych przez roota ani zgodę.
- Rozbieżność z decyzją (inny rozmiar/liczba plików/sha256) → **nie wydawać**, wrócić do Kontrolera.

## Krok 3 — Kontrolowane wyniesienie

1. Skopiuj **zweryfikowaną** paczkę (payload) do **zatwierdzonej lokalizacji** jednym krokiem (bez
   automatycznego ponawiania). Nie przez `/sluza-*`, nie na prywatny sprzęt.
2. Policz i **zapisz `sha256`** u odbiorcy; porównaj z `manifest.json`. Uzyskaj **potwierdzenie odbioru**.
3. Zatwierdzenie ≠ przekazanie: dopiero potwierdzony odbiór kończy wydanie. Kanał/nośnik wg polityki IOD/§14.7.

> Konkretny kanał (np. dedykowany transfer wewnętrzny / nośnik nadzorowany) **uzupełnia IOD** przy
> zatwierdzaniu tej procedury. Dopóki nie jest wpisany — wydania nie wykonywać.

## Krok 4 — Zamknięcie i audyt

1. Wpis do **rejestru wydań** (ticket/rejestr): `request_id`, sha256, kto zatwierdził, kto wydał, czas,
   odbiorca, kanał, potwierdzenie odbioru, powiązanie `uNN ↔ osoba`.
2. **Zwrot dla badacza**: potwierdzenie #208 już jest w `/sluza-potwierdzenia`; dodatkowo przekaż (przez
   admin-klienta/HelpDesk) informację „wydano do <odbiorca>, <data>, sha256 <...>" — patrz formułki w
   [RB-sluza-zwrot-badaczowi.md](RB-sluza-zwrot-badaczowi.md).
3. **Retencja paczki** w kolejce: wg decyzji IOD (IMG-006 — usuwanie warunkowe, wymaga potwierdzenia IOD).
   Do czasu decyzji **nie usuwać** payloadu ani manifestu.

## Czego NIE wolno

- Wydać bez pisemnej decyzji Kontrolera, bez `verify`, albo przy rozbieżności z decyzją.
- Zatwierdzić/wydać własnego wniosku (łamanie rozdziału obowiązków).
- Kopiować payloadu/kwarantanny na prywatny sprzęt ani ponownie do śluzy.
- Wydać część wniosku, „naprawiać" manifest, podnosić limity (100 GiB / 100 000 plików) ani wykonywać zawartości.
- Traktować obecności pliku w kolejce lub potwierdzenia #208 jako zgody.

## Ślad audytowy (minimum do zalogowania)

`request_id`, `sha256`, decyzja Kontrolera (id), operator, czas verify, czas wydania, odbiorca, kanał,
potwierdzenie odbioru, powiązanie `uNN ↔ osoba`. Zdarzenia movera (`export_request`, `snapshot_failed`)
pozostają w SIEM niezależnie.

## Wygaśnięcie

Procedura wygasa z wdrożeniem **#20** (automatyczna zgoda Lidera/Kontrolera + idempotentna publikacja z
potwierdzeniem, rejestr #102). Po #20 wydania tą ścieżką są zabronione. Przegląd procedury: przy każdej
zmianie polityki IOD/§14.7 lub movera/snapshotu.

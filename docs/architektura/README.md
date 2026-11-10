# Architektura WLB — indeks

Dokumentacja architektury i cyklu życia Wirtualnego Laboratorium Badawczego (koordynowane z **#226**).
Każdy element diagramowany jest osobno, w typie dobranym do tego, co pokazuje (zachowanie →
`sequenceDiagram`/`flowchart`/`stateDiagram`; struktura → `classDiagram`/komponenty). Spójność daje
ten indeks + planowany diagram kontekstu/komponentów. Wszystkie diagramy renderują się na GitHub.

## Elementy

| Element | Dokument | Stan |
|---|---|---|
| **Śluza wyjściowa (eksport danych)** | [`sluza-eksportu.md`](sluza-eksportu.md) | ✅ gotowe (Etap 1) |
| Śluza wejściowa (import `/sluza-in`) | _planowane_ | ⬜ |
| Cykl wydania obrazu (źródła → baza → warianty → testy → stable/rollback) | _planowane_ | ⬜ |
| Utworzenie Laboratorium (wydanie → VM → montowania → konto uNN → sesja) | _planowane_ | ⬜ |
| Model domenowy (`classDiagram`: projekt, osoba, konto, VM, sesja, wniosek, decyzja, wydanie) | _planowane_ | ⬜ |
| Diagram komponentów platformy + słownik ról + mapa źródeł | _planowane_ | ⬜ |

## Zasady

- Każdy krok oznaczony: **DZIAŁA w CI/DEV** / **zaproponowano** / **wymaga decyzji**; dla każdej ścieżki krytycznej — dowód (plik+symbol, test, ADR/decyzja) lub jawna luka.
- Dane syntetyczne. Każdy dokument ma datę, wersję bazową (commit) i właściciela aktualizacji; zmiana kontraktu/etapu/odpowiedzialności uruchamia przegląd odpowiedniego diagramu.

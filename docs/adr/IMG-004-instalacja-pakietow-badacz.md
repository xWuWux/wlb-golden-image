# IMG-004: Instalacja pakietów przez badacza — allowlista (kuratorowany mirror)

* **Status:** Przyjęta
* **Data:** 2026-10-23
* **Autorzy / decyduje:** Właściciel Platformy (z Administratorem IP_CMC jako właścicielem Regulaminu)
* **Powiązania:** Regulamin: §24.c, §29.5, §30.1 · Analiza: F-WKS-010, F-WKS-004 · IP_CMC: OPZ OP.3 (CRAN/Bioconductor) · Zgłoszenia/PR: #23, #16 · Pliki: `ansible/roles/lab_config/files/wlb-firstboot`, `/docs/README.md`, `lab.env.example`

## Kontekst i problem

§24.c zabrania instalacji nieautoryzowanego oprogramowania; F-WKS-010 wymaga wsparcia instalacji bibliotek z zewnętrznych źródeł. Dziś obraz sam sobie przeczy: `/docs/README.md` mówi „zakaz", a `wlb-firstboot` przy obecności `PYPI_INDEX_URL`/`CRAN_MIRROR_URL` tworzy `pip.conf`/`r-repos.R` umożliwiające instalację do `~/.local`. O faktycznej możliwości decyduje osiągalność mirrora z UID badacza (nftables/proxy), nie konfiguracja klienta.

## Rozważane opcje

1. **A — zakaz** — mirror niedostępny z UID badacza; pakiety tylko przez nową wersję obrazu / wniosek §29.5. Pełna powtarzalność, zero infrastruktury; sprzeczne z F-WKS-010, obchodzone przez Upload.
2. **B — allowlista pakietów** — kuratorowany mirror (devpi/Nexus + miniCRAN/kuratorowany PPM); badacz instaluje tylko z zatwierdzonej listy, wniosek o nowy pakiet do Administratora IP_CMC.
3. **C — pełny mirror z audytem** — pull-through, instalacje logowane; trudne do pogodzenia z §24.c.

## Decyzja

**Opcja B — zatwierdzona allowlista pakietów przez kuratorowany mirror.** Allowlista = forma „zgody Administratora IP_CMC udzielonej z góry", więc §24.c i F-WKS-010 się nie wykluczają. Mirror może stać **lokalnie** (devpi/miniCRAN na hoście Laboratorium), więc decyzja jest zgodna z lokalnym wdrożeniem bez chmury. Niezależnie od tego obraz dostaje **jawny przełącznik** `RESEARCHER_PACKAGE_INSTALL=deny|mirror` w `lab.env` zamiast wnioskowania z samej obecności `PYPI_INDEX_URL`.

## Odstępstwo od specyfikacji

* **Czy stanowi odstępstwo:** Nie — godzi §24.c z F-WKS-010/OP.3. Do poprawienia błędne założenie specyfikacji „brak sudo = brak instalacji" oraz dopisanie Bioconductora (OP.3) do allowlisty/obrazu.

## Konsekwencje

* **Pozytywne:** zgodność regulaminowa + elastyczność dla badaczy; ochrona przed literówkami/złośliwymi pakietami; pełna kontrola wersji.
* **Negatywne / dług techniczny:** potrzebny **kuratorowany mirror (#16)** i **proces kuratorski** (kto zatwierdza, w jakim czasie); zależności przechodnie wydłużają listę; to więcej pracy niż offline (A). Test akceptacyjny: instalacja z allowlisty działa, spoza — nie.
* **Świadomie pominięte:** pełny mirror (C) — ryzyko złośliwych pakietów; `PYTHONNOUSERSITE` (środek z wariantu A) przeszkadzałby w trybie `mirror`.

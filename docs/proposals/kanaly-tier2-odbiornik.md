# Odbiornik bajtów dla sond kanałów (#333)

Pierwszy inkrement Tier 2 dostarcza `tests/channel_receiver.py`. Odbiornik działa w procesie kontrolera CI, na dedykowanym interfejsie izolowanej sieci. Domyślnie binduje 127.0.0.1 i losowy port. Dla VM kontroler musi wskazać osiągalny adres testowego hosta i właściwą granicę zaufania. Testy jednostkowe używają localhost. Nie stanowią odbioru zapory VM.

## Kontrakty

| Element | Wejście / wynik | Użycie i błędy |
|---|---|---|
| `receive_canary(host: str = "127.0.0.1", *, read_timeout: float = 1.0)` | Context manager zwracający `Receiver`; timeout w (0,30] s | Kontroler uruchamia i zatrzymuje odbiornik. Port przydziela kernel. Problem bind/start/stop przerywa próbę |
| `Receiver.url: str` | Adres HTTP faktycznie związanego interfejsu i portu | Nadawca w izolowanym teście wysyła POST. GET /health służy do osobnej kontroli żywotności |
| `snapshot() -> tuple[Receipt, ...]` | Spójna kopia obserwacji | Kontroler pobiera ją po oknie obserwacji i ukończeniu odbioru. Pusty wynik wymaga dodatkowych dowodów przed klasyfikacją |
| `Receipt` | frozen dataclass: `bytes_received: int`, `sha256: str`, `complete: bool` | Liczy bajty body przeczytane przez odbiornik, w tym fragment przed timeoutem lub EOF. Hash dotyczy odebranego body |
| `transfer_matches(receipts, payload: bytes) -> bool` | Dokładnie jedno kompletne odebranie zgodne z długością i SHA-256 | Kontrola dodatnia. Duplikat, różne bajty lub częściowy transfer dają false |
| `MAX_PAYLOAD_BYTES` | int, 65536 | Rozmiar pojedynczego syntetycznego POST. Zbyt duży lub niejednoznaczny framing tworzy niekompletną obserwację, którą runner musi potraktować jako błąd |

Odbiornik zachowuje długość i hash, a payload jest zużywany strumieniowo. Historia dostępna jest kontrolerowi w pamięci procesu. Osobny odbiornik na scenariusz ogranicza mieszanie prób. Protokół fixture obsługuje HTTP z Content-Length. TLS, CONNECT, UDP/DNS, IPv6 i protokoły plikowe wymagają własnych adapterów. Współdzielony, wystawiony publicznie serwer wymagałby innych zabezpieczeń i limitów. Ten fixture uruchamiamy tylko na kontrolowanej sieci i przez ograniczony czas.

## Włączenie do runnera Tier 2

1. Kontroler tworzy świeży canary_id oraz payload syntetyczny. Zapisuje hash, granicę, konto/UID, flavor, schemat sondy i identyfikator reguły.
2. Uruchamia osobny odbiornik i potwierdza GET /health przed próbą.
3. Na izolowanym wariancie z usuniętą konkretną blokadą wykonuje identyczne żądanie tym samym klientem. Dopiero odebranie poprawnego payloadu potwierdza zdolność sondy do transferu.
4. Weryfikuje aktywność blokady w wariancie chronionym, wykonuje sondę z sesji badacza, zamyka nadawcę i czeka przez jawne, ograniczone okno obserwacji.
5. Sprawdza żywotność po próbie i snapshot odbiornika. Jakiekolwiek odebrane body obala wymóg zera bajtów, również częściowe lub o innym hashu. Niekompletny framing, brak kontroli dodatniej albo awaria odbiornika dają error.
6. Publikuje wynik wraz z dowodami oraz ustala kod wyjścia na podstawie required i polityki wydania. Brak raportu wymaganej sondy blokuje odbiór.

Zero bajtów jest wynikiem obserwacji w zadanym oknie. Może wspierać odmowę dopiero po kontroli trasy, żywotności i wykonania sondy. Hash kompletnego canary sam nie wykrywa fragmentów ani zmienionych bajtów, dlatego wynik liczy również odebrane bajty częściowe.

Dla śluzy zastosować identyczny pomiar do rzeczywistego procesu decyzji i publikacji z #20. Nie zastępować zatwierdzenia bezpośrednim skopiowaniem pliku przez test. Po ponowieniu sprawdzić liczbę publikacji i właściwy request_id. Potwierdzenie przyjęcia #208 jest odrębnym zdarzeniem od zgody na eksport.

## Odbiór tego inkrementu

Siedem testów unittest uruchamia lokalny HTTP receiver i sprawdza dodatni transfer, hash, duplikaty, żywotność, EOF, timeout po fragmencie, przekroczenie limitu, pusty wynik i izolację kolejnych instancji. Ten zakres nie realizuje wszystkich scenariuszy #333. Adaptacja matrycy #331, sesja VM, kontrola mutacyjna blokady, raport ProbeResult i gating pozostają do wdrożenia.

```sh
python3 -m unittest discover -s tests/unit -p test_channel_receiver.py -v
```

Powiązania [#333](https://github.com/xWuWux/wlb-golden-image/issues/333), [#331](https://github.com/xWuWux/wlb-golden-image/pull/331), [#292](https://github.com/xWuWux/wlb-golden-image/issues/292), [#20](https://github.com/xWuWux/wlb-golden-image/issues/20).

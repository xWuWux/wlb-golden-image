# Ochrona domyślnej gałęzi (#259)

Stan odczytany z [rulesetu 26372851](https://github.com/xWuWux/wlb-golden-image/rules/26372851). Ruleset jest aktywny, ma selektor `~DEFAULT_BRANCH` i pustą listę bypass. Blokuje usunięcie i aktualizacje non-fast-forward. Wymaga PR i checku `Gotowe do code review`, lecz licznik aprobat wynosi 0, strict jest wyłączony, a źródło checku nie jest przypięte. Zmiana gałęzi domyślnej zmienia cel selektora. Jeżeli polityka ma chronić wyłącznie nazwę `main`, zmiana selektora wymaga osobnej decyzji.

Reguła `merge_queue` nie występuje w odczytanym rulesecie. Trigger `merge_group` w CI umożliwia obsługę kolejki, gdy zostanie skonfigurowana. Przed wdrożeniem sprawdź także ustawienia klasycznej ochrony gałęzi oraz reguły organizacji. Nazwa rulesetu sama nie potwierdza aktywnej kolejki. [#125](https://github.com/xWuWux/wlb-golden-image/issues/125) · [Przewodnik kolejki](merge-queue.md)

## Zmiana do zatwierdzenia

Zaktualizować istniejący ruleset z zachowaniem warunków, metod scalania, ochrony przed usunięciem i force-pushem oraz pustej listy bypass. Przed zmianą odczytać aktualną konfigurację w Settings i zachować jej kopię wraz z identyfikatorem rulesetu. Jeśli różni się od opisu, uzgodnić różnice przed zmianą.

| Pole GitHub | Wartość docelowa | Skutek |
|---|---|---|
| `required_approving_review_count` | 1, liczba całkowita | PR wymaga aprobaty uprawnionego recenzenta. Właściciel ustala zastępstwo i dostępność recenzji |
| `dismiss_stale_reviews_on_push` | true, bool | Gdy zmieni się diff objęty aprobatą, potrzebna jest ponowna recenzja |
| `require_last_push_approval` | true, bool | Ostatni zestaw zmian wymaga aprobaty osoby innej niż ta, która go wypchnęła |
| `required_review_thread_resolution` | true, bool | Otwarte wątki recenzji blokują scalenie |
| `strict_required_status_checks_policy` | true, bool | Aktualizacja względem bazy może wymagać kolejnego przebiegu i recenzji |
| `required_status_checks` | Jeden unikalny kontekst `Gotowe do code review` z oczekiwanym źródłem GitHub Actions | Przed przypięciem źródła sprawdź producenta na prawdziwym PR. W API źródło wskazuje `integration_id`, którego wartość trzeba odczytać z faktycznego checku |
| `require_code_owner_review` | false w tej zmianie | Włączyć w osobnym kroku po dodaniu i sprawdzeniu efektywnego CODEOWNERS na gałęzi bazowej oraz uprawnień zespołów z #59 |

Agregat sprawdza wymagane etapy 1–4 wraz z 3.5 i etap 5 dla zmian obrazu. Pominięcie etapu 5 jest dopuszczalne przy zmianach poza obrazem. Jeśli opcjonalny etap 6 uruchomiono i zakończył się błędem, agregat blokuje scalenie. Kontekst musi mieć jednego producenta, a zmiany workflow i klasyfikatora zakresu wymagają uważnej recenzji. Status sprawdzaj na commicie ocenianym przez GitHub dla PR, a przy przyszłej kolejce również dla `merge_group`. [Workflow](../.github/workflows/ci.yml) · [Agregat](../ci/ready.sh)

## Odbiór poza gałęzią produkcyjną

Użyć gałęzi próbnej objętej tymi samymi parametrami albo repozytorium testowego z tym samym workflow. Przygotować autora i uprawnionego recenzenta na dwóch odrębnych kontach GitHub. Agenci działający na wspólnym koncie reprezentują tę samą tożsamość. Do pozytywnej próby po pushu recenzenta przygotuj trzecie konto, które może zatwierdzić cudzy PR. Każda próba negatywna powinna mieć zielone CI i spełniać pozostałe wymagania, aby przypisać blokadę do właściwej reguły.

| Próba | Oczekiwany wynik |
|---|---|
| Zielony PR bez aprobaty | Blokada za brak wymaganej recenzji |
| Zmieniony diff po aprobacie | Stara aprobata przestaje spełniać wymaganie, nowa odblokowuje próbę |
| Recenzent wypycha ostatnią zmianę | Wymagana aprobata od innej uprawnionej osoby, która może recenzować ten PR |
| Nierozwiązany wątek recenzji | Blokada, następnie odblokowanie po rozwiązaniu |
| Baza przesuwa się po zielonym CI | Strict blokuje do aktualizacji i przejścia wymaganych sprawdzeń |
| Check o tej samej nazwie z innego źródła | Nie spełnia wymagania przypiętego źródła |
| Zmiana obrazu z pominiętym etapem 5 | Agregat kończy się błędem |
| Wszystkie wymagania spełnione | Próbny PR da się scalić |

Sprawdzić przyczyny blokad w interfejsie. Jeżeli używasz API merge do próby negatywnej, wykonaj ją wyłącznie na gałęzi testowej, na której nieoczekiwane scalenie nie ma skutków operacyjnych. Zapisz SHA próby, wynik oraz komunikat GitHuba.

## Wdrożenie i powrót

Po próbie administrator zmienia regułę w Settings, sprawdza odczyt konfiguracji i przeprowadza zwykły PR na domyślną gałąź. W razie blokady pracy najpierw odczytuje konkretną przyczynę. Jeśli konieczny jest powrót, przywraca zatwierdzoną kopię reguły i zapisuje przyczynę. Utrzymanie dwóch dostępnych tożsamości, które mogą się nawzajem recenzować, jest warunkiem uruchomienia. Własny PR wymaga drugiej tożsamości. Środowisko `release` może chronić publikację, a awaryjne scalenie wymaga osobnej decyzji w polityce gałęzi.

Alternatywą przy częstych aktualizacjach bazy jest Merge Queue. Wymaga osobnego odbioru `merge_group`, w tym klasyfikacji zmian obrazu i budżetu CI. Gdy koszt powtórnych recenzji przeważa, właściciel może rozważyć pozostawienie wymagania aprobaty po ostatnim pushu przy wyłączonym unieważnianiu starych recenzji. Dla zmian wrażliwych najpierw uruchomić CODEOWNERS i sprawdzić pokrycie ścieżek. Podniesienie globalnego licznika do 2 obejmie całą gałąź.

[Dokumentacja reguł GitHuba](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets) · [#259](https://github.com/xWuWux/wlb-golden-image/issues/259)

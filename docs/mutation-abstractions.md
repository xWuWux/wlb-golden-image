# Kontrakty mutacyjne WLB

Katalog wykonywalny `ci/mutations/abstractions.yml` przypisuje kontrakt do właściciela,
pliku źródłowego, testu, konsumentów oraz wariantów. Klucz kontraktu i ID mutacji
identyfikują jedną zmianę źródła. Każdy konsument ma własny zielony baseline i musi
wykazać naruszenie wskazanej asercji. Mutacje tabelaryczne są ręcznie dobranymi
przypadkami. Wynik 100% obejmuje wyłącznie te przypadki. Nie przyznajemy im wyjątków.

| Kontrakt | Implementacja i zakres dowodu | Ryzyko i pozostały dowód |
|---|---|---|
| Wartości wdrożenia | Jeden parser w dwóch ścieżkach odczytu: wzór env i cloud-init (główny i opcjonalny). | Komentarz, cudzysłów lub kolejność mogą zmienić wartość widzianą przez kontrolę CI. Uruchomienie firstboot sprawdzają odrębne testy. |
| Zapora i ukończenie firstboot | Jedna implementacja, konfiguracje HTTP i HTTPS. Każda przechodzi osobno drogę poprawną i błąd przy otwarciu huba. | Raport dotyczy pliku z regułami i znaczników w piaskownicy. Zastosowanie polityki w jądrze wymaga testu VM. |
| AppArmor | Jeden skrypt desktopowy, istniejące wiersze TSV sprawdzają sweep i wynik dla Ansible. | Tryb profili na obrazie wymaga pomiaru na VM. |
| Śluza | Jeden eksporter snapshotów. Testy jednostkowe w `test_wlb_export_snapshot.py`. | Integralność danych i zachowanie storage wymagają odrębnych dowodów. Poza tą macierzą. |
| SIEM | Zdarzenia z `observability/contract.yml`, dekodery i reguły Wazuh. | Kontrakt i próbki sprawdza etap 3.5. Ta macierz nie mutuje deklaracji zdarzeń. |

Właścicielem operacyjnym katalogu jest rola utrzymania platformy. Nazwy konsumentów
opisują faktyczne ścieżki kodu lub konfiguracje. Liczba wariantów nie jest liczbą
niezależnych implementacji. Survivor wymaga sprawdzenia selektora, testu i osiągalności.

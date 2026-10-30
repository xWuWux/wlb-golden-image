# Stan WLB: lokalne metryki i ograniczenia (#22)

`wlb-health.timer` uruchamia co 60 sekund lokalny kolektor. Usługa czyta ścieżkę kolejki z `/etc/wlb/image.conf` i atomowo publikuje `/var/lib/wlb-node-exporter/wlb-health.prom`; katalog jest zapisywalny wyłącznie przez root. Node exporter odczytuje go i udostępnia razem z metrykami systemu tylko na `127.0.0.1:9100`. Przeniesienie poza `/var/lib/wlb` jest konieczne: firstboot nadaje temu katalogowi 0700, co blokuje nieuprzywilejowanego node_exportera. Kolektor zapisuje ogólny wynik do journala, bez nazw pakietów i danych badaczy.

Kontrakt nazw i etykiet jest w `observability/contract.yml`; odpowiedź node_exportera jest sprawdzana w etapie 5. Kolektor podaje:

- `wlb_health_timestamp_seconds` — czas rozpoczęcia próbkowania; brak metryki lub stara próbka wymaga sprawdzenia timera/usługi i eksportera.
- `wlb_export_queue_bundles`, `wlb_export_queue_payload_bytes` — liczba kompletnych wniosków i suma **logicznych rozmiarów plików z manifestów**, bez ponownego odczytu treści ani weryfikacji sum. Nie są to bajty zajęte na dysku. `wlb_export_queue_incoming` liczy osobno kwarantannę `.incoming.*` bez wchodzenia do jej zawartości. Stan może się zmieniać w trakcie pomiaru.
- `wlb_siem_spool_file_bytes` — suma długości plików `wlb_siem.*` w `/var/spool/rsyslog`. Firstboot jawnie konfiguruje ten katalog kolejki. Pomiar nie obejmuje zdarzeń trzymanych w RAM i nie dowodzi dostarczenia do SIEM; zero nie oznacza, że SIEM jest skonfigurowany lub odbiera logi.
- `wlb_health_filesystem_available_bytes{scope="root"|"audit"}` — bajty dostępne dla nieuprzywilejowanego użytkownika na systemach plików `/` i `/var/log/audit` (mogą to być ten sam system plików).
- `wlb_health_auditd_active` — stan usługi auditd, **nie** dowód poprawnego zapisu audytu. `wlb_health_chrony_synchronised` — wynik `chronyc tracking`; 0 oznacza brak synchronizacji.

Każdy pomiar ma `wlb_health_*_collect_success`: 1 oznacza skuteczny odczyt, 0 błąd; przy błędzie metryka wartości jest pomijana, a nie ustawiana na zero. Niezamontowany `/workspace` przy kolejce w tym katalogu, nieznany wpis w kolejce, niepoprawny manifest, przekroczony limit (100 000 katalogów lub wpisów na manifest, 1 000 000 wpisów i 128 MiB manifestów łącznie), błędy I/O i wyścigi z moverem mogą spowodować nieudany odczyt. Usługa ma limit 45 s i 256 MiB pamięci; jeśli się nie zakończy, stara próbka pozostanie na miejscu — niezbędny jest alert na jej wiek.

Diagnostyka lokalna (administrator):

```bash
systemctl status wlb-health.timer wlb-health.service
journalctl -u wlb-health.service -b --no-pager
curl --noproxy '*' -fsS http://127.0.0.1:9100/metrics | grep '^wlb_'
```

Do zdalnego monitoringu i alertowania nadal potrzebne są uzgodnione scrape, transport i reguły zapory; sam lokalny exporter nie wysyła danych do Grafany ani nie alarmuje. Nie uruchamiać testów na danych rzeczywistych.

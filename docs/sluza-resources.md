# Budżet zasobów śluzy (#149)

## Zakres i kontrakt

Limity dotyczą całego `wlb-sluza-out.service` i jego potomków. Jeden drop-in
`60-resources.conf` wystarcza; nie ma dodatkowego slice ani delegowania cgroups.
Cgroups ograniczają zasoby, nie zastępują uprawnień plików ani izolacji badaczy.
Odczyt parametrów cgroup nie jest eskalacją uprawnień. Zapis, przenoszenie PID
oraz zmiana praw mają być zabronione nieuprzywilejowanemu użytkownikowi.

Parametry są **wyłącznie konfiguracją budowy obrazu** w `ansible/group_vars/all.yml`.
Nie dodajemy drugiej ścieżki w `lab.env` i parserze firstboot.

| Zmienna | Typ / jednostka | Domyślnie | Walidacja |
|---|---|---:|---|
| `wlb_sluza_memory_max_mb` | int, MiB | 256 | większe od high, do 4096 |
| `wlb_sluza_memory_high_mb` | int, MiB | 192 | 64 ≤ high < max |
| `wlb_sluza_tasks_max` | int, procesy i wątki | 32 | 16–512 |
| `wlb_sluza_io_weight` | int, względna waga | 50 | 1–10000 |

Przepływ: group_vars → assert w roli storage → szablon drop-in → systemd →
kontrolery memory/pids/io. Render szablonu jest w etapie 2, regresje w etapie 4,
wartości jądra i testy przeciążeń w etapie 5. Zmiana parametrów wymaga nowego
obrazu; rola przeładowuje definicje, ale celowo nie przerywa działającego eksportu
restartem przy ręcznym użyciu Ansible na istniejącej VM. Tam aktywacja wymaga
zaplanowanego restartu usługi i potwierdzenia wartości w cgroup.

256/192 MiB to budżet startowy, nie wynik pomiarów. `MemoryHigh` wymusza reclaim
oraz spowalnia alokacje, nie gwarantuje zwolnienia pamięci przez aplikację.
`MemoryMax` jest ostatnią barierą; nie gwarantuje braku globalnego OOM wywołanego
przez inne usługi lub zbyt małą VM. `MemorySwapMax=0` ogranicza ryzyko thrashingu.
32 tasks zostawia zapas dla bash + potoków find/sort/xargs/sha256sum; 10 jest
ryzykownie małe. Wartość 32 także wymaga pomiarów na docelowych danych.

`IOWeight=50` nie jest limitem MB/s/IOPS. Działanie zależy od backendu i obsługi
kontrolera I/O; na NFS/CephFS nie deklarujemy gwarancji przepustowości. Twardy limit
wymaga identyfikacji urządzenia/backendu i oddzielnego testu konkurencji z hubem.

`OOMPolicy=stop`, `KillMode=control-group` i istniejące `Restart=always`/`RestartSec=5`
kończą resztę procesów po wykrytym OOM i pozwalają wznowić usługę. To nie jest
transakcyjny rollback: mover może zostawić `.incoming` i nie odzyskuje go sam.
Nie usuwać takich wpisów automatycznie. Sprawdzić kolejkę i logi, wstrzymać ponowne
próby problematycznego eksportu, skorygować budżet lub skierować przypadek do
obsługi. Recovery/atomowość eksportu pozostają w zakresie prac #20/#147.

## Testy i ograniczenia dowodu

`tests/sluza_resources.py LOGIN` działa tylko jako root w jednorazowej VM testowej.
LOGIN to istniejący login badacza bez `jupyter-`. Program trafia do VM przez
`tests/acceptance.sh`, nie jest instalowany w produkcyjnym obrazie.

1. Sprawdza aktywną usługę, rzeczywiste memory.max/high/swap.max, pids.max,
   io.weight i polityki systemd. Brak kontrolera lub pliku to FAIL.
2. Próby zapisu jako badacz wymagają konkretnie EACCES/EPERM. ENOENT, brak sudo
   czy brak konta nie zaliczają testu. Nie wymaga zakazu odczytu parametrów.
3. Tworzy jednostki testowe z **kopią wdrożonego drop-in**. Alokuje max+64 MiB
   i wymaga `Result=oom-kill`, SIGKILL oraz liczników `oom` i `oom_kill`
   zachowanych w nadrzędnym slice testowym (768 MiB / 192 tasks). Timeout i dowolny błąd nie wystarczają.
4. Wykonuje skończoną liczbę fork (tasks+8), wymaga EAGAIN oraz przyrostu
   `pids.events:max`; sprząta i zbiera dzieci.
5. Kontrole wykonują te same obciążenia z nadal ograniczonym budżetem 512 MiB,
   128 tasks, bez swapu i z RuntimeMaxSec=45. Nigdy nie wyłączają limitów hosta.
6. Sprawdza rzeczywisty mover na prywatnym pliku 1 MiB i prywatnej kolejce pod
   tym samym drop-in; potwierdza zachowanie treści. Istniejące testy śluzy nadal
   sprawdzają eksport badaczy. PID-y huba, audytu, logów i realnego movera muszą
   pozostać niezmienione po próbach.

Funkcje testowe: `run(*args: str) -> str` (timeout 15 s),
`prop(unit: str, name: str) -> str`, `budget(memory: int, tasks: int) -> tuple[int,int]`
(bajty/liczba dzieci), `probe(root: Path, label: str, code: str, args: list[str],
control: bool=False) -> tuple[str,str]` (Result, ExecMainStatus), `main(login: str) -> None`.
Wszystkie błędy blokują akceptację. Logi testu są widoczne, nie tłumione przez expect_ok.

Bezpieczna obwiednia testu: max 64–384 MiB, tasks 16–64 i co najmniej 1 GiB
MemAvailable. Większy poprawny budżet obrazu wymaga świadomego przestrojenia
kontroli i zasobów runnera; test kończy się FAIL zamiast ryzykować OOM całej VM.
Testy syntetyczne nie zabijają realnego movera i nie dowodzą odzyskania eksportu
po OOM. Nie testują też izolacji I/O, dużych drzew ani wszystkich backendów storage.

Przed odbiorem: pomiar memory.peak/pids.peak (jeżeli dostępne), czasu eksportu
pliku/katalogu z reprezentatywną liczbą wpisów, opóźnień huba przy konkurencji I/O,
próba recovery kolejki i test po restarcie VM. Utrwalić SHA obrazu i logi wyników.

## Bramka CI

Zmiany storage, group_vars, programu testowego, acceptance.sh i selektora etapów
uruchamiają etap 5 na PR oraz merge_group bez etykiety. Błędna/brakująca baza diff
wymusza integrację. Pozostałe ścieżki zachowują politykę #86.
`storage_change() -> status` korzysta z istniejącego BASE; kod 0 oznacza wymagany
build. BASE w merge queue pochodzi z `merge_group.base_sha`.
PR #152 modyfikuje ten sam selektor dla sieci: przy scalaniu zachować oba zestawy
ścieżek. Ten PR jest niezależny od #152 i go nie zastępuje.

Źródła semantyki:
- https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html
- https://docs.kernel.org/admin-guide/cgroup-v2.html

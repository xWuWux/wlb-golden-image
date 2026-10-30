# Pierwsze uruchomienie obrazu: przewodnik dla testera

Ten przewodnik prowadzi od czystego komputera z Windows do zbudowanego obrazu VM Laboratorium i
działającej VM testowej z JupyterHubem. Powstał na podstawie pierwszego uruchomienia przez testera
(2026-10-01). Problemy, na które wtedy trafił, są opisane w sekcji
[Typowe problemy](#typowe-problemy), z przyczyną i rozwiązaniem.

| | |
|---|---|
| Czas | ok. 30 min przygotowania (jednorazowo) + 10–60 min budowania obrazu + 10 min testów |
| Wynik | `output/wlb-general-<wersja>-<data>/*.qcow2` oraz VM testowa z hubem pod `http://localhost:8080` |
| Wymagania | Windows 11 z WSL2 (Ubuntu 24.04 lub nowszy), ok. 40 GB wolnego miejsca, co najmniej 12 GB RAM w komputerze |

## Zanim zaczniesz: trzy zasady

1. **Wszystkie polecenia uruchamiasz w terminalu Ubuntu (WSL), nie w PowerShellu.**
   Wyjątkiem jest `wsl --shutdown`, które uruchamia się w PowerShellu. W przewodniku znak zachęty pokazuje, gdzie
   uruchomić polecenie:

   | Znak zachęty | Gdzie |
   |---|---|
   | `PS>` | PowerShell w Windows |
   | `wsl$` | terminal Ubuntu (WSL) na Twoim komputerze, np. `lk@lk:~/projekty/wlb-golden-image$` |
   | `vm$` | wewnątrz VM testowej po zalogowaniu przez SSH, np. `wlbadmin@lab-test01:~$` |

2. **Repozytorium musi leżeć w systemie plików WSL (`~/…`), a nie na dysku C: (`/mnt/c/…`).**
   Na dysku Windows wszystkie pliki mają prawa 0777 i nie da się tego zmienić. Skutki:
   - `ssh` odrzuca klucz budowania („UNPROTECTED PRIVATE KEY FILE”), więc budowanie się nie udaje,
   - Ansible ignoruje swoją konfigurację („world writable directory”),
   - Git na Windows zamienia zakończenia linii na CRLF i skrypty przestają działać (`env: 'bash\r'`).

   Pliki z WSL otworzysz w Windows przez `\\wsl.localhost\Ubuntu\home\<login>\projekty\wlb-golden-image`
   albo w VS Code z rozszerzeniem WSL (`code .` w terminalu WSL).

3. **Polecenia `make` uruchamiasz zawsze w katalogu głównym repozytorium**, czyli tam, gdzie leży `Makefile`.
   W podkatalogach (np. `ci/`) pojawi się błąd `No rule to make target`.

## 1. Przygotowanie WSL (jednorazowo)

**1.1. Pamięć i wirtualizacja.** Utwórz lub zmień plik `%UserProfile%\.wslconfig` w Windows:

```ini
[wsl2]
memory=12GB
processors=4
nestedVirtualization=true
```

**1.2. Pakiety systemowe:**

```bash
wsl$ sudo apt update
wsl$ sudo apt install -y make git curl xz-utils python3 python3-venv \
       qemu-system-x86 qemu-utils cloud-image-utils genisoimage openssh-client
```

**1.3. Dostęp do KVM.** VM buduje się i uruchamia z akceleracją sprzętową:

```bash
wsl$ sudo usermod -aG kvm $USER
```

```powershell
PS> wsl --shutdown
```

Otwórz terminal Ubuntu ponownie i sprawdź: `wsl$ id -nG` musi zawierać `kvm`.

## 2. Pobranie repozytorium

```bash
wsl$ mkdir -p ~/projekty && cd ~/projekty
wsl$ git clone https://github.com/xWuWux/wlb-golden-image
wsl$ cd wlb-golden-image
```

Od tej chwili wszystkie polecenia `wsl$` wykonujesz w `~/projekty/wlb-golden-image`.

## 3. Narzędzia projektu

```bash
wsl$ make tools
```

Instaluje do `.tools/` przypięte wersje Packera, Ansible, narzędzi testowych i skanerów, bez sudo.
`make` sam dodaje je do `PATH`, więc **nie trzeba niczego eksportować ręcznie**. Komunikat
`You are in 'detached HEAD' state` przy instalacji `bats` jest normalny.

## 4. Sprawdzenie środowiska

```bash
wsl$ make doctor
```

Sprawdza wszystko, na czym może się wyłożyć budowanie: położenie repozytorium, zakończenia linii, dostęp
do KVM, pakiety systemowe, narzędzia z `make tools`, wolne miejsce i pamięć. Przy każdym błędzie podaje
polecenie naprawcze. Przechodź dalej dopiero po komunikacie **„Środowisko gotowe.”**
`make build` i `make test-up` uruchamiają to sprawdzenie same.

## 5. Walidacja konfiguracji

```bash
wsl$ make init        # wtyczki Packera (raz)
wsl$ make validate    # walidacja bez budowania obrazu (ok. 1 min)
```

Wynik: **„Wszystkie sprawdzenia przeszły.”** Ostrzeżenia z listy
[Normalne komunikaty](#normalne-komunikaty) nie są błędami.

## 6. Budowanie obrazu

```bash
wsl$ make build IMAGE_VERSION=0.1.0
```

- Trwa 10–60 minut, najdłużej przy pierwszym budowaniu. Pobiera obraz Ubuntu, a potem instaluje JupyterHub,
  środowisko Pythona i pakiety R (HADES).
- Kończy się komunikatem `Builds finished. The artifacts of successful builds are:` i ścieżką do
  `output/wlb-general-0.1.0-<data>/wlb-general-0.1.0-<data>.qcow2`.
- Ostatni komunikat `Zamrożone wersje pakietów: … (make freeze …)` jest wskazówką dla opiekuna
  repozytorium. Tester nie musi nic z nim robić (zob. [krok 10](#10-zamrożenie-wersji-tylko-opiekun-repozytorium)).

## 7. VM testowa i testy automatyczne

```bash
wsl$ make test-up     # start VM z obrazu jako Laboratorium testowe (ok. 2–3 min)
wsl$ make test        # kryteria akceptacji MVP (ok. 5 min)
```

Oczekiwany wynik `make test`: **`Wynik: N PASS, 0 FAIL, 2 SKIP`**. Dwa testy z SKIP (proxy Laboratorium
i faktyczne wylogowanie po 12 h) wymagają infrastruktury albo czasu, którego test lokalny nie ma.

## 8. Ręczne sprawdzenie w przeglądarce

**8.1. Hasło Administratora Klienta (konto bezosobowe `a01`):**

```bash
wsl$ make test-password
```

Hasło jest zapisane w VM w pliku `/root/wlb-hub-admin-initial-password`, który może czytać tylko root.
`make test-password` odczytuje je przez SSH, więc nie trzeba logować się do VM.

**8.2. Hub:** otwórz w przeglądarce Windows `http://localhost:8080` i zaloguj się jako `a01`.

- Konta bezosobowe (IMG-002): badacze NIE rejestrują się sami — konta stanowiskowe `u01`, `u02`, …
  są pre-provisionowane przy pierwszym starcie (ile — `RESEARCHER_ACCOUNTS` w `lab.env`). Hasła początkowe
  w VM: `/root/wlb-hub-u01-initial-password` itd. (tylko root). Zaloguj się jako `u01` tym hasłem.
- Jako badacz sprawdź na przykład: nowy notebook Python i R; odczyt `/data-mart`; zapis do `/sluza-out`
  (plik powinien zniknąć); po wdrożeniu #7 także przycisk pobierania pliku (powinien być ukryty, a bezpośredni adres `/files/…` dawać odmowę 403).

**8.3. Opcjonalnie: logowanie do VM przez SSH** (administrator platformy):

```bash
wsl$ ssh -p 2222 -i build/test/id_ed25519 wlbadmin@127.0.0.1
vm$ sudo cat /root/wlb-hub-admin-initial-password    # pliki roota tylko przez sudo
vm$ exit
```

- Konto `wlbadmin` nie ma hasła, więc `su` nie zadziała. Polecenia administracyjne uruchamiasz przez `sudo …`.
- Ścieżki w VM zaczynają się od `/`, np. `/root/...`. Bez ukośnika, czyli `root/...`, oznaczają katalog
  wewnątrz katalogu domowego.
- Komunikat po zalogowaniu `New release '26.04 LTS' available. Run 'do-release-upgrade'` **ignoruj**.
  VM nigdy nie aktualizuje się sama, bo poprawki wchodzą przez nową wersję obrazu.

## 9. Zatrzymanie VM testowej

```bash
wsl$ make test-down
```

VM testowa zajmuje kilka GB RAM, więc zatrzymaj ją po testach. `make test-up` uruchomi ją ponownie z tego
samego obrazu. Konta i pliki z poprzedniego uruchomienia znikną, bo dysk roboczy tworzy się od nowa.

## 10. Zamrożenie wersji (tylko opiekun repozytorium)

`make freeze` przenosi do `envs/` dokładne wersje pakietów z ostatniego budowania.

- Komunikat **„Bez zmian: wersje w repozytorium są zgodne ze zbudowanym obrazem”** oznacza, że wszystko się
  zgadza i nie trzeba nic commitować. Tak było przy pierwszym uruchomieniu testera.
- Jeśli wersje się zmieniły, zmiana trafia na osobną gałąź i do PR. Nigdy nie commituje się jej
  bezpośrednio do `main`.

## Normalne komunikaty

Te komunikaty pojawiają się przy poprawnym działaniu i nie wymagają reakcji:

| Komunikat | Skąd | Dlaczego jest w porządku |
|---|---|---|
| `You are in 'detached HEAD' state` | `make tools` (bats) | narzędzie jest pobierane w przypiętej wersji (tagu), a nie z gałęzi |
| `Rscript niedostępny — pomijam (w CI instalowany)` | `make validate` | R jest potrzebny tylko w VM; skrypty R sprawdza CI |
| `nft -c wymaga sudo — pomijam (w CI wykonywane)` | `make validate` | reguły zapory sprawdza CI z uprawnieniami |
| `schema.py[WARNING]: datasource not detected` | `make validate` | walidacja cloud-init działa poza chmurą |
| `creating filesystem with Joliet extensions but without Rock Ridge` | `make build` | płyta z konfiguracją dla maszyny budującej |
| `[DEPRECATION WARNING]: INJECT_FACTS_AS_VARS…` | `make build` (Ansible) | zapowiedź zmian w przyszłej wersji Ansible |
| `userdel: user packer is currently used by process …` | koniec `make build` | konto budujące jest usuwane przy zamykaniu maszyny |
| `New release '26.04 LTS' available` | logowanie do VM | VM nie aktualizuje się sama (zob. krok 8.3) |

## Typowe problemy

Każdy z poniższych problemów wystąpił przy pierwszym uruchomieniu. Większość z nich wykrywa teraz
`make doctor`.

| # | Objaw | Przyczyna | Rozwiązanie |
|---|---|---|---|
| 1 | `env: 'bash\r': No such file or directory` | Repozytorium sklonowane na dysku Windows z `core.autocrlf=true`, więc skrypty mają zakończenia linii CRLF | Sklonuj repozytorium w WSL (krok 2). Od tej wersji `.gitattributes` wymusza LF także przy checkout na Windows. |
| 2 | `Brak narzędzia: ansible-playbook — uruchom: make tools …` | Narzędzia projektu nie są jeszcze zainstalowane | `make tools` (krok 3) |
| 3 | `make: *** No rule to make target 'validate'` | Polecenie uruchomione w podkatalogu (np. `ci/`) | Wróć do katalogu głównego: `cd ~/projekty/wlb-golden-image` |
| 4 | `make build`: `exec: "ansible-playbook": executable file not found in $PATH` | Starsza wersja `Makefile` nie dodawała `.tools/` do `PATH` | Od tej wersji robi to sama. Bez ręcznego `export PATH`, w którym łatwo o literówkę, np. `ansible=playbook`. |
| 5 | `Ansible is being run in a world writable directory … ignoring it as an ansible.cfg source` | Repozytorium na dysku Windows (prawa 0777) | Repozytorium w WSL (zasada 2). `make` ustawia też `ANSIBLE_CONFIG`. |
| 6 | `WARNING: UNPROTECTED PRIVATE KEY FILE! Permissions 0777 …` i `Permission denied (publickey)`, a budowanie kończy się po ok. 1 min | Klucz budowania na dysku Windows, gdzie nie da się ustawić praw 0600, więc ssh go odrzuca | Repozytorium w WSL (zasada 2). Wykrywa to `make doctor`. |
| 7 | `make freeze && git commit` daje `nothing to commit, working tree clean` | Wersje w repozytorium są zgodne z obrazem, więc nie ma czego commitować | To poprawny wynik. `make freeze` pisze teraz o tym wprost (krok 10). |
| 8 | Nie da się odczytać hasła admina: `nano /root/…` w WSL, `cd root/…`, `su` i `cat` w VM kończą się błędem | Plik leży **w VM**, nie w WSL. Może go czytać tylko root. `wlbadmin` nie ma hasła (`su`). `root/…` bez ukośnika to inna ścieżka. | `make test-password` (krok 8.1) albo w VM `sudo cat /root/wlb-hub-admin-initial-password` (krok 8.3) |
| 9 | `ssh -p 2222` wypisuje tylko pomoc (`usage: ssh …`) | Brak klucza i adresu w poleceniu | Pełne polecenie z kroku 8.3 albo `make test-password` |

## Gdy coś nie działa

1. `make doctor`: większość problemów środowiska ma tam gotowe polecenie naprawcze.
2. Logi budowania: przy błędzie Packer wypisuje zadanie Ansible, które się nie powiodło. Komunikat
   `[ERROR]` lub `fatal:` stoi kilka linii wyżej niż `Build … errored`.
3. Konsola VM testowej: `build/test/serial.log`. Przy problemie zgłoszenie z tym plikiem i wynikiem
   `make doctor` pozwala szybko znaleźć przyczynę.

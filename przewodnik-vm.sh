#!/usr/bin/env bash
# =============================================================================================
#  Przewodnik: golden image VM Laboratorium WLB (JupyterHub) — od pustego WSL do testów w CI
# =============================================================================================
#
#  Skrypt prowadzi krok po kroku przez cały proces:
#    przygotowanie środowiska -> budowanie obrazu -> testy lokalne -> CI na GitHubie -> wdrożenie
#  Przed każdym poleceniem pokazuje, co robi, i pyta o zgodę. Na końcu jest lista błędów, które
#  napotkaliśmy przy tworzeniu projektu, wraz z obejściami (tryb "bledy").
#
#  Użycie:
#    ./przewodnik-vm.sh              # interaktywnie, wszystkie kroki po kolei
#    ./przewodnik-vm.sh krok 5       # tylko wybrany krok (lista: ./przewodnik-vm.sh lista)
#    ./przewodnik-vm.sh pokaz        # tylko wypisz polecenia z opisem, niczego nie wykonuj
#    ./przewodnik-vm.sh bledy        # napotkane błędy i jak je ominąć
#
#  Środowisko, na którym to przygotowano: Windows 11 + WSL2, Ubuntu 26.04, 8 CPU, 16 GB RAM.
#  Repozytorium: https://github.com/xWuWux/wlb-golden-image (prywatne)
# =============================================================================================
set -uo pipefail

REPO_URL=https://github.com/xWuWux/wlb-golden-image
REPO_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd) # katalog, w którym leży ten skrypt (korzeń repo)
IMAGE_VERSION=${IMAGE_VERSION:-0.1.0}                  # wersja budowanego obrazu
TRYB=interaktywny                                      # interaktywny | pokaz

# --- funkcje pomocnicze -----------------------------------------------------------------------

# naglowek "tytuł" — wyraźny początek kroku
naglowek() {
  printf '\n\033[1;34m================================================================\033[0m\n'
  printf '\033[1;34m %s\033[0m\n' "$1"
  printf '\033[1;34m================================================================\033[0m\n'
}

# opis "tekst..." — wyjaśnienie, co i po co robimy
opis() { printf '\033[0;36m%s\033[0m\n' "$@"; }

# uwaga "tekst" — ostrzeżenie (np. rzeczy, które kiedyś się nie udały)
uwaga() { printf '\033[1;33m! %s\033[0m\n' "$@"; }

# polecenie "komentarz" "polecenie" — pokazuje polecenie z komentarzem i (po zgodzie) wykonuje je.
# Polecenie jest napisem, bo często zawiera potoki i przekierowania.
polecenie() {
  local komentarz=$1 cmd=$2 odp
  printf '\n\033[0;32m# %s\033[0m\n$ %s\n' "$komentarz" "$cmd"
  [[ $TRYB == pokaz ]] && return 0
  read -r -p "Wykonać? [T]ak / [p]omiń / [q] zakończ: " odp
  case ${odp,,} in
    p*)
      echo "(pominięto)"
      return 0
      ;;
    q*)
      echo "Koniec."
      exit 0
      ;;
  esac
  if bash -c "cd '$REPO_DIR' && $cmd"; then
    printf '\033[0;32m✔ OK\033[0m\n'
  else
    printf '\033[0;31m✘ Polecenie zakończyło się błędem (kod %s).\033[0m\n' "$?"
    uwaga "Sprawdź komunikat powyżej i sekcję błędów: ./przewodnik-vm.sh bledy"
    read -r -p "Kontynuować mimo to? [t/N]: " odp
    [[ ${odp,,} == t* ]] || exit 1
  fi
}

# tylko_pokaz "komentarz" "polecenie" — polecenia, których przewodnik celowo NIE wykonuje
# (np. w PowerShellu, na produkcyjnej chmurze) — wypisuje je do ręcznego uruchomienia
tylko_pokaz() { printf '\n\033[0;35m# %s  (uruchom ręcznie)\033[0m\n$ %s\n' "$1" "$2"; }

pauza() { [[ $TRYB == pokaz ]] || read -r -p $'\nEnter = dalej ' _; }

# =============================================================================================
#  KROKI
# =============================================================================================

krok_1() {
  naglowek "Krok 1. Sprawdzenie sprzętu i WSL"
  opis "Golden image budujemy na QEMU/KVM (a nie VMware), bo Proxmox i OpenStack używają formatu" \
    "qcow2 i sterowników virtio — obraz z KVM działa na obu bez konwersji." \
    "WSL2 obsługuje zagnieżdżoną wirtualizację, więc KVM działa wewnątrz Ubuntu w WSL."

  polecenie "Czy CPU wspiera wirtualizację sprzętową (vmx = Intel, svm = AMD)? Wynik > 0 = tak" \
    "grep -cE 'vmx|svm' /proc/cpuinfo"
  polecenie "Czy istnieje urządzenie KVM (powinno: crw-rw---- root kvm /dev/kvm)" \
    "ls -l /dev/kvm"
  polecenie "Zasoby: CPU, RAM i wolne miejsce (potrzeba ~6 GB RAM dla budowania i ~40 GB dysku)" \
    "nproc; free -g; df -h ~ | tail -1"
  polecenie "Wersja systemu w WSL" "grep PRETTY_NAME /etc/os-release"
}

krok_2() {
  naglowek "Krok 2. Instalacja narzędzi (wymaga sudo)"
  opis "QEMU uruchamia maszyny, qemu-utils daje qemu-img (dyski qcow2), cloud-image-utils daje" \
    "cloud-localds (dysk z konfiguracją cloud-init), genisoimage tworzy ISO z seedem dla Packera," \
    "Ansible instaluje zawartość obrazu, make uruchamia cele z Makefile, gh obsługuje GitHuba."

  polecenie "Pakiety z repozytoriów Ubuntu" \
    "sudo apt update && sudo apt install -y qemu-system-x86 qemu-utils cloud-image-utils genisoimage ansible make git gh"
  uwaga "Za pierwszym razem zabrakło 'make' — bez niego cele typu 'make build' nie działają."

  opis "Packera nie ma w repozytoriach Ubuntu — instalujemy go z oficjalnego repozytorium HashiCorp."
  polecenie "Klucz podpisujący repozytorium HashiCorp" \
    "wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor --yes -o /usr/share/keyrings/hashicorp.gpg"
  polecenie "Repozytorium HashiCorp dla tej wersji Ubuntu i instalacja Packera" \
    "echo \"deb [signed-by=/usr/share/keyrings/hashicorp.gpg] https://apt.releases.hashicorp.com \$(lsb_release -cs) main\" | sudo tee /etc/apt/sources.list.d/hashicorp.list && sudo apt update && sudo apt install -y packer"
  uwaga "Jeśli HashiCorp nie ma jeszcze repozytorium dla Twojej wersji Ubuntu, pobierz sam plik binarny" \
    "z https://developer.hashicorp.com/packer/install i umieść go w /usr/local/bin."

  polecenie "Opcjonalnie: kcov (pokrycie testów powłoki) — jest w Ubuntu od 26.04" \
    "sudo apt install -y kcov || echo 'kcov niedostępny — testy zadziałają, ale bez pomiaru pokrycia'"
  polecenie "Kontrola wersji" \
    "qemu-system-x86_64 --version | head -1; ansible --version | head -1; packer version; make --version | head -1; gh --version | head -1"
}

krok_3() {
  naglowek "Krok 3. Dostęp do KVM bez sudo"
  opis "Packer i skrypty testowe uruchamiają QEMU jako Twój użytkownik — musi on mieć prawo do /dev/kvm."

  polecenie "Dodanie użytkownika do grupy kvm" "sudo usermod -aG kvm \"\$USER\""
  opis "Nowa grupa zadziała dopiero w nowej sesji. W WSL trzeba zrestartować całą maszynę WSL:"
  tylko_pokaz "W PowerShellu w Windows (zamyka wszystkie terminale WSL)" "wsl --shutdown"
  uwaga "Samo otwarcie nowej karty terminala nie wystarczy. Polecenie 'sg kvm' nie istnieje w Ubuntu 26.04."
  polecenie "Po restarcie WSL: czy mamy prawo zapisu do /dev/kvm?" \
    "test -w /dev/kvm && echo 'KVM dostępne' || echo 'BRAK dostępu — zrestartuj WSL (wsl --shutdown)'"
}

krok_4() {
  naglowek "Krok 4. Repozytorium z GitHuba"
  opis "Repozytorium jest prywatne — potrzebne jest zalogowanie w gh (przeglądarka lub token)."

  polecenie "Stan logowania do GitHuba (jeśli brak: gh auth login)" "gh auth status"
  opis "Jeśli czytasz ten plik, repozytorium już masz (katalog: $REPO_DIR)."
  tylko_pokaz "Na nowym komputerze: sklonowanie repozytorium" \
    "gh repo clone xWuWux/wlb-golden-image && cd wlb-golden-image"
  polecenie "Aktualna gałąź i ostatnie commity" "git status -sb | head -1; git log --oneline -5"
  polecenie "Struktura projektu" \
    "ls; echo; ls ansible/roles ci tests"
  opis "Najważniejsze miejsca:" \
    "  packer/wlb-general.pkr.hcl  — jak budowany jest obraz (QEMU, Ubuntu 24.04, cloud-init)" \
    "  ansible/group_vars/all.yml  — wszystkie parametry (wersje, limity sesji, katalogi §10)" \
    "  ansible/roles/*             — zawartość obrazu (TLJH, Python, R/HADES, audyt, logi, zapora)" \
    "  cloud-init/                 — wzór konfiguracji konkretnego Laboratorium (lab.env)" \
    "  tests/ i ci/                — testy lokalne i etapy pipeline'u CI"
}

krok_5() {
  naglowek "Krok 5. Narzędzia CI i szybkie testy (etapy 1–4, ~5 minut)"
  opis "Te same skrypty co w GitHub Actions. Narzędzia (shellcheck, ruff, semgrep, bats…) instalują się" \
    "w przypiętych wersjach do katalogu .tools/ — bez sudo, z weryfikacją sum SHA-256."
  uwaga "Nie ustawiaj TMPDIR na bardzo długą ścieżkę — wtyczki Packera tworzą tam gniazda uniksowe" \
    "(limit 108 znaków) i kończą się błędem 'plugin exited before we could connect'."

  polecenie "Instalacja narzędzi CI do .tools/" "make tools"
  polecenie "Etap 1: lint, formatowanie, sekrety (FIX=1 make lint poprawia formatowanie)" "make lint"
  polecenie "Etap 2: walidacja Packera, Ansible, szablonów, cloud-init i konfiguracji z wlb-firstboot" "make check"
  polecenie "Etap 3: SAST (semgrep, bandit), IaC (checkov), podatności zależności, licencje" "make security"
  polecenie "Etap 3.5: kontrakt obserwowalności (czy logi obrazu zgadzają się z observability/contract.yml)" \
    "make observability"
  polecenie "Etap 4: testy jednostkowe (bats + pytest) z progami pokrycia 85% / 90%" "make unit"
  opis "Wszystkie cztery naraz: make ci  — warto uruchamiać przed każdym pushem."
}

krok_6() {
  naglowek "Krok 6. Budowanie golden image (~15–30 minut)"
  opis "Packer pobiera przypięte wydanie Ubuntu 24.04, uruchamia je w QEMU/KVM z tymczasowym" \
    "użytkownikiem 'packer', Ansible instaluje zawartość, a skrypt czyszczący usuwa tożsamość" \
    "maszyny budującej (klucze SSH, machine-id, sekrety huba). Wynik: plik .qcow2 + suma SHA-256."
  uwaga "Budowanie trwa ~15–30 min (w CI ~14 min). Nie usypiaj komputera w trakcie budowania lokalnego."

  polecenie "Pobranie wtyczek Packera (qemu, ansible) — raz" "make init"
  polecenie "Budowanie obrazu wersji $IMAGE_VERSION (log na ekranie; można przerwać Ctrl+C)" \
    "make build IMAGE_VERSION=$IMAGE_VERSION"
  polecenie "Wynik: obraz, suma kontrolna i manifest" "ls -lh output/*/"
  polecenie "Wersje składników zapisane w obrazie" "cat build/artifacts/*/image-release 2>/dev/null | tail -8"
}

krok_7() {
  naglowek "Krok 7. Zamrożenie wersji pakietów"
  opis "Po pierwszym budowaniu w build/artifacts/ są dokładne wersje pakietów Pythona i R." \
    "Przeniesienie ich do envs/ sprawia, że każde kolejne budowanie odtwarza te same wersje," \
    "a etap 3 CI zaczyna sprawdzać ich podatności (osv-scanner)."

  polecenie "Kopiowanie locków do envs/" "make freeze"
  polecenie "Podgląd zmian przed commitem" "git diff --stat envs/"
  polecenie "Commit zamrożonych wersji" \
    "git add envs/ && git commit -m \"Zamrożenie środowisk dla $IMAGE_VERSION\""
}

krok_8() {
  naglowek "Krok 8. Uruchomienie VM testowej i kryteria akceptacji MVP"
  opis "VM startuje z nakładki na obraz (obraz się nie zmienia) i z osobnym dyskiem roboczym," \
    "a cloud-init konfiguruje ją jak Laboratorium testowe (tests/cloud-init/user-data.yaml)." \
    "Proxy w teście celowo nie istnieje — każde wyjście badacza do internetu musi się nie udać."

  polecenie "Start VM testowej (czeka na cloud-init i wlb-firstboot)" "make test-up"
  polecenie "Hasło początkowe Administratora Klienta (login: a01)" \
    "ssh -q -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i build/test/id_ed25519 -p 2222 wlbadmin@127.0.0.1 sudo cat /root/wlb-hub-admin-initial-password"
  opis "JupyterHub: http://localhost:8080 (działa też z przeglądarki w Windows)."
  opis "Logi VM testowej idą do testowego SIEM na hoście (10.0.2.2:5514). Żeby je zobaczyć, uruchom" \
    "odbiornik przed make test-up — w osobnym terminalu:"
  tylko_pokaz "Testowy odbiornik SIEM (Ctrl+C kończy)" \
    "python3 tests/syslog_sink.py --port 5514 --out build/siem.log"
  polecenie "Kryteria akceptacji MVP (logowanie, izolacja, śluzy, egress, limity sesji, audyt)" "make test"
  polecenie "Czy zdarzenia z kontraktu obserwowalności dotarły do SIEM (jeśli odbiornik działał)" \
    "test -s build/siem.log && python3 ci/observability_contract.py verify-log build/siem.log || echo 'brak build/siem.log — odbiornik nie był uruchomiony'"
  opis "Kryteria oznaczone SKIP wymagają infrastruktury (proxy, SIEM) albo czasu (12 h) — patrz README."
  tylko_pokaz "Ręczny test limitu 12 h: skróć limit do 5 minut w VM i sprawdź, że serwer zostaje zatrzymany" \
    "sudo tljh-config set services.cull.max_age 300 && sudo tljh-config reload hub"
}

krok_9() {
  naglowek "Krok 9. Test migracji (nowa VM na istniejącym dysku roboczym)"
  opis "Dysk systemowy jest jednorazowy: nowa wersja obrazu = nowy dysk systemowy, ten sam /workspace." \
    "Test sprawdza, że konto badacza, jego UID, pliki, hasło i hasło Administratora Klienta przetrwają."

  polecenie "Zatrzymanie VM z kroku 8" "make test-down"
  polecenie "Migracja: ten sam obraz jako źródło i cel" \
    "tests/migration.sh \"\$(ls -t output/*/*.qcow2 | head -1)\""
  tylko_pokaz "Migracja między wersjami obrazu (np. 0.1.0 -> 0.2.0)" \
    "tests/migration.sh output/<stary>/<stary>.qcow2 output/<nowy>/<nowy>.qcow2"
}

krok_10() {
  naglowek "Krok 10. Benchmarki wydajności (opcjonalnie)"
  opis "Czas startu VM, logowania, spawnu serwera, operacji pandas, ładowania HADES i przepustowość" \
    "dysku roboczego — porównane z budżetami w ci/perf-budget.env."
  polecenie "Benchmarki ostatniego obrazu" "make perf"
  polecenie "Wyniki" "cat build/perf/summary.md"
}

krok_11() {
  naglowek "Krok 11. CI na GitHubie"
  opis "Każdy PR przechodzi etapy po kolei: 1 lint -> 2 build test -> 3 security -> 4 unit ->" \
    "5 integracja i migracja (buduje obraz, 1–2 h) -> 6 benchmarki/wdrożenie (na żądanie) ->" \
    "'Gotowe do code review'. Kolejny etap startuje dopiero po sukcesie poprzedniego."

  polecenie "Nowa gałąź na zmiany (nie pracujemy bezpośrednio na main)" "git switch -c moja-zmiana"
  tylko_pokaz "Po zmianach: szybkie testy, commit i wypchnięcie" \
    "make ci && git commit -am 'Opis zmiany' && git push -u origin moja-zmiana"
  tylko_pokaz "Otwarcie PR — pipeline startuje automatycznie" "gh pr create --fill"
  polecenie "Lista ostatnich przebiegów CI" "gh run list --limit 5"
  tylko_pokaz "Śledzenie przebiegu na żywo / logi nieudanych kroków" \
    "gh run watch   |   gh run view <ID> --log-failed"
  tylko_pokaz "Benchmarki w CI: etykieta 'perf' na PR" "gh pr edit <NR> --add-label perf"
  tylko_pokaz "Telemetria CI (ślady, metryki, logi OTLP) dowolnego przebiegu — lokalnie" \
    "GITHUB_TOKEN=\$(gh auth token) python3 ci/ci_telemetry.py --repo xWuWux/wlb-golden-image --run-id <ID>"
  opis "Po scaleniu do main workflow 'CI observability' robi to automatycznie po każdym przebiegu" \
    "(artefakt ci-telemetry; eksport do kolektora po ustawieniu vars.OTEL_EXPORTER_OTLP_ENDPOINT)."
  opis "Komputer można uśpić — CI działa na serwerach GitHuba (e-mail przy niepowodzeniu)." \
    "Wymagany status check dla main: Settings → Branches → 'Gotowe do code review'" \
    "(dla repozytoriów prywatnych wymaga planu GitHub Pro/Team). Etap 5 zużywa minuty Actions."
}

krok_12() {
  naglowek "Krok 12. Wdrożenie obrazu na klaster (ręcznie, poza przewodnikiem)"
  opis "Przewodnik tylko wypisuje polecenia — wdrożenie dotyczy wspólnej infrastruktury i wymaga" \
    "decyzji (Proxmox czy OpenStack) oraz danych konkretnego Laboratorium."
  tylko_pokaz "OpenStack: rejestracja obrazu" \
    "openstack image create wlb-general-$IMAGE_VERSION --disk-format qcow2 --container-format bare --private --property hw_disk_bus=virtio --property hw_qemu_guest_agent=yes --file output/wlb-general-$IMAGE_VERSION-*/wlb-general-$IMAGE_VERSION-*.qcow2"
  tylko_pokaz "OpenStack: VM Laboratorium z user-data według cloud-init/lab-user-data.example.yaml" \
    "openstack server create lab-XX --image wlb-general-$IMAGE_VERSION --flavor wlb.general --network lab-XX-net --user-data lab-XX.yaml --block-device source_type=blank,destination_type=volume,volume_size=200,delete_on_termination=false"
  tylko_pokaz "Proxmox: import dysku i własny user-data cloud-init" \
    "qm importdisk <vmid> <obraz>.qcow2 <storage> && qm set <vmid> --cicustom user=snippets:lab-XX.yaml"
  opis "Każde Laboratorium: własny plik user-data (hostname, klucz SSH, udziały §10, /etc/wlb/lab.env)." \
    "Do zakończenia wlb-firstboot VM przyjmuje z sieci tylko SSH."
}

# =============================================================================================
#  BŁĘDY NAPOTKANE PRZY TWORZENIU PROJEKTU I JAK JE OMINĄĆ
# =============================================================================================
bledy() {
  naglowek "Napotkane błędy i obejścia"
  cat <<'EOF'
ŚRODOWISKO (WSL / narzędzia)
 1. "make: command not found"
    -> sudo apt install -y make
 2. /dev/kvm niedostępne mimo dodania do grupy kvm ("kvm not accessible")
    -> nowa grupa działa dopiero po restarcie WSL: w PowerShellu `wsl --shutdown`.
       `sg kvm` nie istnieje w Ubuntu 26.04, nowa karta terminala nie wystarcza.
 3. Packera nie ma w repozytoriach Ubuntu
    -> repozytorium apt HashiCorp (krok 2) albo plik binarny do /usr/local/bin.
 4. Packer: "Failed to load source type / plugin exited before we could connect"
    -> wtyczki tworzą gniazda uniksowe w $TMPDIR (limit ścieżki 108 znaków). Nie ustawiaj
       TMPDIR na długą ścieżkę (albo: unset TMPDIR).
 5. Packer: "no file exists at packer/packer/cloud-init/..." (podwojona ścieżka)
    -> templatefile() rozwiązuje ścieżki względne względem path.root; używamy ścieżek
       absolutnych: local.repo_root = abspath("${path.root}/..").

OBRAZ / ANSIBLE / CLOUD-INIT
 6. ansible.builtin.deb822_repository wymaga na maszynie docelowej python3-debian
    -> instalowany jawnie w roli r_env przed dodaniem repozytorium CRAN.
 7. cloud-init: "users.0.uid: The use of string type is deprecated"
    -> `uid: 1001` jako liczba, nie "1001".
 8. TLJH domyślnie daje administratorom huba pełne sudo (/etc/sudoers.d/jupyterhub-admins)
    -> usuwane w roli tljh i w wlb-firstboot (Regulamin §21, §24.c).
 9. JupyterHub 5 (TLJH 2.0) wpuszcza tylko allowed_users albo przy allow_all
    -> c.NativeAuthenticator.allow_all = True; o dostępie decyduje zatwierdzenie konta.
10. RStudio Server na osobnym porcie loguje przez PAM, a konta TLJH nie mają haseł systemowych
    -> RStudio uruchamiane z JupyterLab (jupyter-rsession-proxy), domyślnie wyłączone.
11. Migracja: baza huba na jednorazowym dysku systemowym -> nowa wersja obrazu kasowała konta,
    TLJH zakładał konta badaczy z innym UID (utrata dostępu do plików), resetował hasło admina
    -> baza huba w /workspace/.wlb-hub/, wlb-firstboot odtwarza konta z UID właściciela
       katalogu domowego, `wlb-hub-user --if-missing` nie rusza istniejącego konta.
12. Zatrzymanie QEMU sygnałem SIGTERM = odcięcie zasilania (ryzyko niespójnego dysku roboczego)
    -> tests/stop-local.sh najpierw wykonuje `systemctl poweroff` przez SSH.

TESTY JEDNOSTKOWE (bats / pytest)
13. W bats `! polecenie` w środku testu NIE powoduje niepowodzenia (shellcheck SC2314) —
    część asercji negatywnych była martwa i ukrywała prawdziwy błąd testu
    -> funkcja `refute polecenie...` w tests/unit/helpers.bash.
14. Atrapy poleceń z wielowierszowym wyjściem traciły cudzysłowy (wyjście wykonywane jak kod)
    -> wyjście atrapy trzymane w osobnym pliku i wypisywane przez cat.
15. Przypisanie do zmiennej readonly w nieinteraktywnym bashu kończy całą powłokę
    -> sprawdzenie w podpowłoce: `(ZMIENNA=x) || echo readonly`.
16. argparse traktuje login "-root" jako opcję (inny komunikat błędu)
    -> w testach nieprawidłowych loginów użyty "_root".
17. Test license_check.main() dopisywał swoje wyniki do podsumowania CI ($GITHUB_STEP_SUMMARY)
    -> monkeypatch.delenv("GITHUB_STEP_SUMMARY") w teście.

POKRYCIE (kcov)
18. kcov nie ma w Ubuntu 24.04 (runnery GitHub)
    -> etap 4 w kontenerze ubuntu:26.04 (lokalnie: sudo apt install kcov).
19. kcov raportował 0% pokrycia w kontenerze, choć testy przechodziły
    -> przyczyną był brak locale UTF-8 (kontenery nie mają LANG): kcov nie dopasowuje śladu
       wykonania do wierszy z polskimi znakami. ci/unit.sh ustawia LANG=C.UTF-8.
       (Uruchamianie jako zwykły użytkownik tylko pozornie pomagało — `su` ustawia LANG.)

SECURITY / CI
20. semgrep: zestaw reguł p/bash nie istnieje (HTTP 404), a --quiet ukrył błąd
    -> używane p/default, p/python, p/github-actions, p/secrets.
21. semgrep i bandit zgłaszają urllib.urlopen z dynamicznym adresem
    -> license_check.py dopuszcza tylko https://, zgłoszenia wyciszone z uzasadnieniem.
22. checkov: --output-file-path musi wskazywać plik (checkov.sarif), nie katalog.
    CKV_GHA_7 (SLSA: brak parametrów workflow_dispatch) -> wyłączone w .checkov.yaml
    z uzasadnieniem: parametry włączają tylko opcjonalne etapy testowe.
23. semgrep: Dependabot bez okresu karencji -> `cooldown: default-days: 7`.
24. osv-scanner: requirements.txt rozwiązywał zależności przechodnie (fałszywe alarmy)
    -> --no-resolve (locki zawierają pełny zestaw); plik dpkg wymaga prefiksu
       `-L dpkg-status:ścieżka`.
25. gitleaks (drzewo robocze) wykrył klucz prywatny build/packer_ed25519
    -> to lokalny klucz maszyny budującej (w .gitignore); wykluczony w .gitleaks.toml.
26. Plik __pycache__ trafił do commita -> __pycache__/ w .gitignore.
27. GitHub Actions, etap 2: "rsyslogd: could not open config file ... Permission denied"
    -> AppArmor pozwala rsyslogd czytać konfigurację tylko z /etc/rsyslog*; sprawdzenie
       kopiuje plik na chwilę do /etc/rsyslog.d/.

LICENCJE (do decyzji)
28. inspectomop ma licencję AGPL-3.0 -> wyjątek w ci/license-policy.yml "do potwierdzenia
    przez dział prawny"; bez zgody pakiet należy usunąć z envs/python/environment.yml.
29. stringi: licencja "file LICENSE" -> sprawdzona ręcznie (BSD-3-Clause + ICU), wpisana jako wyjątek.

PIERWSZE BUDOWANIE OBRAZU W CI (etap 5)
30. Test akceptacyjny urywał się po cichu na pierwszym sprawdzeniu audytu i był uznawany za zaliczony
    -> ausearch, gdy stdin nie jest terminalem, czyta z niego dane — a skrypt testu szedł do VM
       przez stdin ("ssh ... bash -s"), więc ausearch zjadał resztę testów. Skrypt trafia teraz
       do pliku w VM i działa ze stdin z /dev/null; ausearch --input-logs; brak linii "Wynik:"
       w logu = błąd.
31. Migracja: wlb-firstboot padał na nowej VM ("firstboot.done: No such file")
    -> grupy TLJH (jupyterhub-users/-admins) powstawały po ustawieniu GID_MIN=10000 i zajmowały
       GID z zakresu badaczy, więc odtwarzanie grupy badacza z GID = UID trafiało na zajęty numer.
       Grupy huba są systemowe, konto odtwarzane z GID katalogu domowego (przy kolizji: nowy GID).
32. renv.lock z obrazu miał 0 pakietów (zamrożenie wersji R nie działało)
    -> renv::snapshot() poza projektem renv pomija bibliotekę site; lockfile zapisywany wprost
       z installed.packages() (sprawdzone: renv::lockfile_read, renv::restore, osv-scanner).
       Pusty lock z budowania = błąd etapu 5.
33. Etap 5 był przerywany ("The operation was canceled") podczas skanu podatności obrazu
    i nie zapisywał artefaktów. Przyczyna niepotwierdzona (podejrzenie: brak pamięci na runnerze)
    -> skan jako osobny krok po zapisaniu artefaktów, z limitem 15 min i continue-on-error.
34. Runner GitHub dla repozytorium prywatnego ma 2 vCPU i ~7 GB RAM, a VM prosiła o 4 vCPU / 8 GB
    -> ci/integration.sh dobiera VM_CPUS/VM_MEMORY i zasoby budowania do maszyny.

OBSERWOWALNOŚĆ
35. Wzorce obserwowalności dla aplikacji (endpointy HTTP, ślady rozproszone) nie pasują do obrazu VM
    -> kontrakt zdarzeń logów + weryfikacja dostarczenia do SIEM; ślady i metryki tylko dla potoku CI.
36. Test odbiornika SIEM: "address already in use" — odbiornik z poprzedniej próby działał w tle
    (`polecenie && ... &` wysyła do tła CAŁY łańcuch &&, razem z przypisaniem zmiennych)
    -> uruchamiaj odbiornik osobną linią: `python3 tests/syslog_sink.py ... &`; zamykaj `kill <PID>`,
       nie `pkill -f` (wzorzec trafia też we własną powłokę).
37. Klient OTLP przyjmował tylko https, a kolektor w sieci wewnętrznej zwykle działa po http
    -> dozwolone http i https (inne schematy, np. file://, odrzucane).

OBSŁUGA BŁĘDÓW CI (docs/ci-runbook.md)
38. Etap 5 kończył się "The operation was canceled" bez logów i artefaktów, nawet dla kroków always()
    -> przyczyna: osv-scanner na dpkg-status (~1000 pakietów Ubuntu) przekraczał 3 GB w <1 min
       i wyczerpywał pamięć runnera (7 GB), zabijając agenta GitHub Actions. Zmierzone lokalnie
       w cgroup (systemd: "Failed with result 'oom-kill', 3G memory peak"). Ten sam pomiar bez limitu
       przerwał sesję roboczą -> każdy ciężki pomiar uruchamiaj pod strażnikiem:
         ci/guard.sh --name pomiar --memory 3G --timeout 10m -- <polecenie>
       Rozwiązanie: skan bez dpkg-status, wszystkie etapy CI pod ci/guard.sh (--memory auto),
       diagnoza kategorii błędu i automatyczne ponowienie wyłącznie awarii infrastruktury.
39. semgrep: akcje GitHub przypięte do ruchomych tagów (@v4) — ryzyko podmiany (supply chain)
    -> wszystkie akcje przypięte do SHA commitów, wersja w komentarzu (Dependabot aktualizuje).
40. sudo (strażnik w CI) usuwa zmienne LD_* — Python z setup-python może ich potrzebować
    -> strażnik przekazuje PATH, HOME i LD_LIBRARY_PATH jawnie (ścieżka sudo sprawdzana dopiero w CI).
41. Przebieg #5 padł w etapie 1 na "Request failed with status code 504" (akcja setup-packer,
    serwer HashiCorp), a diagnoza uznała to za błąd testu
    -> Packer instalowany przez ci/install-tools.sh (SHA-256, curl --retry-all-errors) jak reszta
       narzędzi; przejściowe błędy sieci (5xx, timeout, DNS, limit API) = kategoria infra (ponowienie).
42. Kontrakt SIEM w CI: 7/9 zdarzeń OK, brak firstboot.done i sluza_out.export_request, choć dotarły
    -> rsyslog (RSYSLOG_SyslogProtocol23Format) wstawia DWIE spacje przed treścią, logger(1) jedną;
       parser zakładał jedną, więc wzorce zakotwiczone na początku nie pasowały. Test na prawdziwej
       linii z VM w tests/unit/test_observability_contract.py.
43. Strażnik sklasyfikował OOM jako FAIL (kod 143/15): po zabiciu procesu systemd dobija resztę SIGTERM
    -> OOM rozpoznawany po wyniku jednostki systemd (Result=oom-kill), nie po kodzie wyjścia.
44. Przyczyna OOM osv-scannera zawężona bisekcją do JEDNEGO pakietu: linux-libc-dev (źródło: linux).
    Sam ten pakiet: > 6 GB w 160 s; 294 pozostałe pakiety: 1,2 GB w 7 s; bazowy ubuntu:24.04: 86 MB.
    Zgłoszone do google/osv-scanner; u nas issue #2.
45. Przebieg #7: etap 5 padł na "test -w /dev/kvm" zaraz po udevadm trigger (wyścig z udev)
    -> ci/enable-kvm.sh: udevadm settle, czekanie, w razie potrzeby chmod; brak /dev/kvm na runnerze
       = adnotacja "INFRA:" (kategoria infra, automatyczne ponowienie).
46. make freeze ujawnił podatności w pakietach bazowych Pythona z instalatora TLJH (urllib3 CVSS 8.9,
    setuptools 8.8, requests, idna, h2, hpack, wheel) -> minimalne wersje w environment.yml.
47. Kontrola licencji wysypywała się na timeoutach api.anaconda.org przy 468 pakietach (16 wątków)
    -> ponawianie z przerwą, 6 wątków, brak pakietu w API = licencja nieznana (do oceny).
48. Budowanie padło na "CondaHTTPError: HTTP 000 CONNECTION FAILED" (pobieranie paczki conda-forge)
    -> ponawianie we wszystkich zadaniach Ansible z siecią (conda: CONDA_REMOTE_MAX_RETRIES +
       retries zadania; TLJH, R, get_url, RStudio) i Acquire::Retries dla apt.
49. osv-scanner: override pakietu musi używać nazwy ŹRÓDŁOWEJ (Source:), nie binarnej —
    name = "linux" działa (skan 1 s), name = "linux-libc-dev" nie (dalej OOM).
50. Budowanie z zamrożonego renv.lock: "libzmq.so.5: cannot open shared object file" (pbdZMQ)
    -> pierwsze budowanie (pak) samo doinstalowywało biblioteki systemowe, renv::restore tego nie robi.
       Pełna lista z pak::pkg_sysreqs(..., sysreqs_platform = "ubuntu-24.04") wpisana jawnie
       w roli r_env (libzmq3-dev, libicu-dev, libx11-dev, xz-utils). Uwaga: ponawianie zadania nie
       pomaga przy błędach deterministycznych — czytaj pierwszy komunikat, nie ostatni.
51. Skan pakietów systemowych przywrócony (issue #2): ci/osv-scanner-image.toml pomija pakiet
    źródłowy "linux" -> 1066 pakietów w 19 s, 1,3 GB. ci/integration.sh image-sca brał pusty katalog
    artefaktów (utworzony przez mkdir przed wyborem) -> wybór najnowszego katalogu z lockami.
    osv-scanner kończy się kodem 1, gdy ZNAJDZIE podatności -> strażnik: --ok-codes 0,1 dla raportu.
52. Kolejka eksportu leżała na jednorazowym dysku systemowym (wnioski ginęły przy nowej wersji obrazu)
    -> /workspace/.wlb-export-queue (dysk roboczy, 0700 root); test migracji sprawdza wniosek. #4
53. chrony miał publiczne serwery NTP, nieosiągalne z sieci Laboratorium -> NTP_SERVERS w lab.env. #5
    Walidację trzeba robić PRZED zapisem pliku: `die` wewnątrz `{ ...; } > plik` wypisywało komunikat
    do pliku konfiguracyjnego zamiast do logu (wyłapał to test jednostkowy).
54. Lokalny etap 5: "Odbiornik SIEM nie dostał żadnych zdarzeń" — port 5514 trzymał odbiornik
    z ręcznego testu -> integration.sh sprawdza, czy odbiornik wystartował (kill -0), przed startem VM.

PIERWSZE URUCHOMIENIE PRZEZ TESTERA (2026-10-01) — pełny opis: docs/pierwsze-uruchomienie.md
55. env: 'bash\r' — repozytorium sklonowane na dysku Windows (/mnt/c) z CRLF -> .gitattributes (eol=lf),
    make doctor wykrywa CRLF; klonować w WSL (~/projekty).
56. "Brak narzędzia: ansible-playbook" i make uruchamiane w ci/ ("No rule to make target") -> komunikat
    wskazuje make tools w katalogu głównym; przewodnik: wszystkie polecenia make z katalogu głównego.
57. make build: ansible-playbook nie w PATH (narzędzia w .tools/) -> Makefile eksportuje PATH z .tools/
    i ANSIBLE_CONFIG; bez ręcznego export PATH (u testera literówka "ansible=playbook").
58. Na /mnt/c: "world writable directory" (ansible.cfg ignorowany) i "UNPROTECTED PRIVATE KEY FILE
    0777" (ssh odrzuca klucz budowania, Permission denied) -> make doctor blokuje budowanie z /mnt/*.
59. make freeze -> "nothing to commit": wersje zgodne z obrazem -> freeze pisze "Bez zmian" wprost;
    zmiany wersji tylko przez gałąź i PR.
60. Hasło admina huba: nano /root/... w WSL, cd/su w VM -> plik jest w VM, tylko dla roota; wlbadmin
    bez hasła -> make test-password (albo sudo cat w VM).

WYNIKI I NIEZWERYFIKOWANE (stan na 2026-09-25)
 - Obraz buduje się w CI w ~14 min (R/HADES z binariów Posit Package Manager: ~75 s).
 - Na prawdziwej VM przechodzą wszystkie kryteria akceptacji (37 PASS, 0 FAIL, 3 SKIP) i test
   migracji (9/9); poprawki 30–34 potwierdzone w CI (przebieg #4). Zamrożony renv.lock: 86 pakietów.
 - Etap 6b (wdrożenie tymczasowe na OpenStack) nie był uruchamiany — wymaga konfiguracji chmury.
 - Obserwowalność: łańcuch odbiornik SIEM -> kontrakt sprawdzony lokalnie (logger RFC 5424 po TCP),
   eksport OTLP sprawdzony na prawdziwym OpenTelemetry Collector 0.161; dostarczenie z prawdziwej VM
   (rsyslog, audisp-syslog, logi jądra) potwierdzi pierwszy przebieg etapu 5 z tą zmianą.
EOF
}

# =============================================================================================
#  URUCHOMIENIE
# =============================================================================================
KROKI=(krok_1 krok_2 krok_3 krok_4 krok_5 krok_6 krok_7 krok_8 krok_9 krok_10 krok_11 krok_12)

lista() {
  local i
  for i in "${!KROKI[@]}"; do
    printf '%3d. %s\n' "$((i + 1))" "$(declare -f "${KROKI[$i]}" | grep -m1 -oP 'naglowek "Krok \d+\. \K[^"]+')"
  done
}

case ${1:-} in
  krok)
    n=${2:?podaj numer kroku (./przewodnik-vm.sh lista)}
    [[ $n =~ ^[0-9]+$ && $n -ge 1 && $n -le ${#KROKI[@]} ]] || {
      echo "Nie ma kroku $n"
      exit 1
    }
    "krok_$n"
    ;;
  pokaz)
    TRYB=pokaz
    for k in "${KROKI[@]}"; do "$k"; done
    bledy
    ;;
  bledy) bledy ;;
  lista) lista ;;
  "")
    naglowek "Przewodnik: golden image VM Laboratorium WLB"
    opis "Repozytorium: $REPO_DIR ($REPO_URL)" \
      "Przed każdym poleceniem zobaczysz komentarz i pytanie: T = wykonaj, p = pomiń, q = zakończ."
    lista
    for k in "${KROKI[@]}"; do
      "$k"
      pauza
    done
    bledy
    ;;
  *)
    sed -n '11,16p' "$0"
    exit 2
    ;;
esac

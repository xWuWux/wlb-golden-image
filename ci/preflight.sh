#!/usr/bin/env bash
# Sprawdzenie środowiska przed budowaniem obrazu i testem lokalnym (make doctor).
# Każdy problem: co jest nie tak, dlaczego to przeszkadza i jak to naprawić. Kod 1, gdy coś blokuje.
#   ci/preflight.sh          # pełne sprawdzenie (budowanie + test lokalny)
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
blocking=0
ok() { printf '  OK     %s\n' "$1"; }
warn() { printf '  UWAGA  %s\n         %s\n' "$1" "$2"; }
fail() {
  printf '  BŁĄD   %s\n         %s\n' "$1" "$2"
  blocking=1
}

echo "== Środowisko (make doctor)"

# 1. Repozytorium na dysku Windows (/mnt/c/...): pliki mają tam prawa 0777 i nie da się ich zmienić,
#    więc ssh ignoruje klucz budowania ("UNPROTECTED PRIVATE KEY FILE"), a Ansible pomija ansible.cfg
fs=$(stat -f -c %T . 2>/dev/null)
if [[ $PWD == /mnt/* || $fs == 9p || $fs == v9fs ]]; then
  fail "Repozytorium leży na dysku Windows ($PWD)" \
    "Sklonuj je w systemie plików WSL: mkdir -p ~/projekty && cd ~/projekty && git clone https://github.com/xWuWux/wlb-golden-image"
else
  ok "Repozytorium w systemie plików Linuksa ($PWD)"
fi

# 2. Zakończenia linii CRLF (checkout z core.autocrlf=true na Windows)
if grep -lq $'\r' ci/*.sh tests/*.sh Makefile 2>/dev/null; then
  fail "Skrypty mają zakończenia linii CRLF (Windows)" \
    "git config core.autocrlf input && git rm --cached -r -q . && git reset --hard"
else
  ok "Zakończenia linii LF"
fi

# 3. KVM (budowanie i VM testowa)
if [[ ! -e /dev/kvm ]]; then
  fail "Brak /dev/kvm" "WSL2: włącz zagnieżdżoną wirtualizację (nestedVirtualization=true w .wslconfig) i wsl --shutdown"
elif [[ ! -w /dev/kvm ]]; then
  fail "Brak dostępu do /dev/kvm" "sudo usermod -aG kvm $USER, potem w PowerShell: wsl --shutdown i ponowne otwarcie terminala"
else
  ok "Dostęp do /dev/kvm"
fi

# 4. Narzędzia z pakietów systemowych
for cmd in qemu-system-x86_64:qemu-system-x86 qemu-img:qemu-utils cloud-localds:cloud-image-utils \
  ssh:openssh-client make:make git:git; do
  if command -v "${cmd%%:*}" >/dev/null; then ok "${cmd%%:*}"; else fail "Brak ${cmd%%:*}" "sudo apt install ${cmd#*:}"; fi
done
# płyta z konfiguracją cloud-init dla maszyny budującej (Packer: cd_content) — dowolny z trzech
if command -v xorriso >/dev/null || command -v genisoimage >/dev/null || command -v mkisofs >/dev/null; then
  ok "narzędzie ISO (xorriso / genisoimage / mkisofs)"
else
  fail "Brak narzędzia do tworzenia ISO" "sudo apt install genisoimage"
fi

# 5. Narzędzia projektu w .tools/ (przypięte wersje) — Makefile dodaje je do PATH sam
for t in .tools/bin/packer .tools/venv-lint/bin/ansible-playbook; do
  if [[ -x $t ]]; then ok "$(basename "$t") (.tools)"; else fail "Brak $(basename "$t")" "make tools (w katalogu głównym repozytorium)"; fi
done

# 6. Zasoby
free_gb=$(($(df -Pk . | awk 'NR == 2 {print $4}') / 1024 / 1024))
if ((free_gb >= 40)); then
  ok "Wolne miejsce: ${free_gb} GB"
else
  warn "Wolne miejsce: ${free_gb} GB" "Obraz, cache i VM testowa potrzebują ok. 40 GB"
fi
mem_gb=$(($(awk '/^MemTotal:/ {print $2}' /proc/meminfo) / 1024 / 1024))
if ((mem_gb >= 10)); then
  ok "Pamięć: ${mem_gb} GB"
else
  warn "Pamięć: ${mem_gb} GB" "Budowanie potrzebuje 6 GB dla VM, test lokalny 8 GB; zwiększ memory= w .wslconfig"
fi

echo
if ((blocking)); then
  echo "Popraw błędy powyżej i uruchom ponownie: make doctor"
  exit 1
fi
echo "Środowisko gotowe."

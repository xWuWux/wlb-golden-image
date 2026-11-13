# shellcheck shell=bash
# Parser i walidacja kafelków .desktop → Exec (#314 część A). Wydzielony, żeby miał testy
# jednostkowe (tests/unit/kafelki-exec.bats) i był używany przez tests/acceptance.d/43-kafelki-exec.sh.
# Fragment akceptacji dostaje ten plik przez tests/acceptance.sh (sklejanie na hoście).

# Kanoniczny PATH sesji pulpitu: jrdp/xstartup (ansible/roles/desktop/files/wlb-desktop-xstartup)
# nie ustawia PATH — sesja dziedziczy PATH spawnera TLJH. Zweryfikowane w #199/#202 i opisane
# w ansible/roles/neuro_apps/tasks/main.yml: to /opt/tljh/user/bin:/bin:/usr/bin, BEZ /usr/local/bin.
# Dlatego bramka NIE może używać `command -v` roota (root ma /usr/local/bin) — fałszywy zielony.
w43_session_path() {
  printf '%s\n' "${W43_SESSION_PATH:-/opt/tljh/user/bin:/bin:/usr/bin}"
}

# w43_strip_codes STR — usuwa field-codes Desktop Entry: %f %F %u %U %i %c %k; %% → %.
w43_strip_codes() {
  printf '%s' "$1" | sed -e 's/%%/%/g' -e 's/%[fFuUick]//g'
}

# w43_first_token EXEC — pierwszy token polecenia; pomija `env` i przypisania VAR=... (np. env FOO=1 cmd).
w43_first_token() {
  local t
  # shellcheck disable=SC2086  # celowo dzielimy na tokeny; Exec w naszych kafelkach nie ma cudzysłowów
  for t in $(w43_strip_codes "$1"); do
    case $t in
      env) continue ;;
      [A-Za-z_]*=*) continue ;;
    esac
    t=${t%\"}
    t=${t#\"}
    t=${t%\'}
    t=${t#\'}
    printf '%s\n' "$t"
    return 0
  done
  return 1
}

# w43_on_session_path CMD — czy CMD rozwiązuje się na PATH SESJI (nie roota).
w43_on_session_path() {
  local cmd=$1 dir
  local IFS=:
  for dir in $(w43_session_path); do
    [[ -n $dir && -x "$dir/$cmd" ]] && return 0
  done
  return 1
}

# w43_exec_target_ok CMD — absolutny i wykonywalny ALBO rozwiązywalny na PATH sesji.
w43_exec_target_ok() {
  local cmd=$1
  case $cmd in
    /*) [[ -x $cmd ]] && return 0 ;;
    *) w43_on_session_path "$cmd" && return 0 ;;
  esac
  return 1
}

# w43_is_wrapper PATH — czy to wrapper WLB (domyślnie /usr/local/bin, /opt/wlb)? Katalogi można
# podmienić przez W43_WRAPPER_DIRS (tylko dla testów jednostkowych).
w43_is_wrapper() {
  local p=$1 d
  for d in ${W43_WRAPPER_DIRS:-/usr/local/bin /opt/wlb}; do
    case $p in "$d"/*) return 0 ;; esac
  done
  return 1
}

# w43_wrapper_target_ok WRAPPER — wrapper WLB musi wskazywać istniejący cel.
# Binarka/symlink do ELF jest celem sama w sobie (rc=0). Dla skryptu powłoki bierzemy polecenie
# z linii `exec …`: absolutne → test -x; gołe → PATH sesji, a gdy wrapper źródłuje profil FSL,
# także $FSLDIR/share/fsl/bin i $FSLDIR/bin (FSLDIR z profilu).
w43_wrapper_target_ok() {
  local w=$1 line target fsldir profile=${W43_FSL_PROFILE:-/etc/profile.d/fsl.sh}
  # tylko skrypty powłoki mają „cel" do sprawdzenia — nie zgadujemy dla binarek
  head -c 2 "$w" 2>/dev/null | grep -q '#!' || return 0
  line=$(grep -E '^[[:space:]]*exec[[:space:]]' "$w" 2>/dev/null | head -1) || return 1
  [[ -n $line ]] || return 1
  target=$(w43_first_token "${line#*exec}") || return 1
  case $target in
    /*)
      [[ -x $target ]] && return 0
      return 1
      ;;
  esac
  w43_on_session_path "$target" && return 0
  if grep -q 'profile\.d/fsl\.sh' "$w" && [[ -r $profile ]]; then
    fsldir=$(sed -n 's/^[[:space:]]*FSLDIR=//p' "$profile" | head -1 | tr -d '"')
    [[ -n $fsldir ]] || return 1
    [[ -x "$fsldir/share/fsl/bin/$target" || -x "$fsldir/bin/$target" ]] && return 0
  fi
  return 1
}

# w43_tile_ok PLIK — kafelek poprawny, gdy KAŻDA linia Exec= wskazuje istniejący, wykonywalny cel
# (na PATH sesji, nie roota) i każdy wrapper WLB ma istniejący cel. Brak Exec= to błąd.
w43_tile_ok() {
  local f=$1 execs cmd rc=0 n=0
  [[ -f $f ]] || {
    echo "brak pliku $f" >&2
    return 1
  }
  while IFS= read -r execs; do
    n=$((n + 1))
    if ! cmd=$(w43_first_token "${execs#Exec=}"); then
      echo "$f: Exec bez polecenia: $execs" >&2
      rc=1
      continue
    fi
    if ! w43_exec_target_ok "$cmd"; then
      echo "$f: Exec '$cmd' nie istnieje/nie jest wykonywalny na PATH sesji ($(w43_session_path))" >&2
      rc=1
      continue
    fi
    if w43_is_wrapper "$cmd" && ! w43_wrapper_target_ok "$cmd"; then
      echo "$f: wrapper $cmd wskazuje nieistniejący cel" >&2
      rc=1
    fi
  done < <(grep -E '^Exec=' "$f")
  if [[ $n -eq 0 ]]; then
    echo "$f: brak linii Exec=" >&2
    rc=1
  fi
  return $rc
}

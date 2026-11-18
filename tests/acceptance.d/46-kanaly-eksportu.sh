# shellcheck shell=bash
# #292 (inkrement 1): kanały eksportu/importu — matryca tests/channels.yaml.
#
# Harness realizuje wpisy matrycy jako sondy JAKO BADACZ (as "$R1"), po sesji huba/serwera
# notebooków. Zasada nadrzędna: każda asercja `denied` ma kontrolę pozytywną w tej samej grupie
# (surface) — błąd kontroli unieważnia denial (ERROR/SKIP, nigdy fałszywy PASS). `known_open` jest
# tylko raportowany (SKIP z właścicielem i uzasadnieniem why), nie asertowany.
#
# Gating: WLB_CHANNEL_GATING=1 (flaga --channel-gating z tests/acceptance.sh) promuje niezgodności
# (fail) oraz awarie wymaganych sond (error) do FAIL blokującego bramkę.
# Domyślnie (bez gatingu) niezgodność = SKIP/MISMATCH — do walidacji KVM, jak #138.
# Raport: /tmp/wlb-channels/channels.json + channels.md; ci/integration.sh kopiuje je do
# build/ci-logs/channels-<flavor>/ (per flavor, żeby raporty się nie nadpisywały).

# Inicjalizacja wszystkich zmiennych PRZED ich użyciem (odporność na set -u)
WLB_CH_DIR=${WLB_CH_DIR:-/tmp/wlb-channels}
WLB_CH_ROWS=$WLB_CH_DIR/rows.tsv
WLB_CH_JAMOVI_RUNTIME=${WLB_CH_JAMOVI_RUNTIME:-/tmp/wlb-channels-runtime}
[[ -n ${R1:-} ]] || R1=u01
[[ -n ${R2:-} ]] || R2=u02
[[ -n ${HUB:-} ]] || HUB="http://127.0.0.1"
WLB_CH_JAR=/tmp/wlb-test-$R1.jar
WLB_CH_ARGS=" $* "
WLB_CH_GATING=0
[[ $WLB_CH_ARGS == *" --channel-gating "* ]] && WLB_CH_GATING=1
WLB_CH_FLAG_PROXY=0
[[ $WLB_CH_ARGS == *" --proxy-allowlist "* ]] && WLB_CH_FLAG_PROXY=1

declare -A WLB_CH_CTRL=()
WLB_CH_CONTROL=0
WLB_CH_ALWAYS_FAIL=0
WLB_CH_OBS=""
WLB_CH_JUPYTER_OK=0
WLB_CH_XSRF=""
WLB_CH_PROXY=""
WLB_CH_MIRROR=""
WLB_CH_SETUP_ERR=""

WLB_R1_HOME=$(getent passwd "jupyter-$R1" 2>/dev/null | cut -d: -f6)
[[ -n ${WLB_R1_HOME:-} ]] || WLB_R1_HOME="/workspace/jupyter-$R1"

# Normalizacja błędów infrastruktury i protokołu:
# Kody 2 (błąd harnessu), 6 (brak DNS), 7 (brak połączenia), 28 (timeout curl), 35 (błąd TLS),
# 52 (pusta odpowiedź), 56 (błąd odbioru), 124 (timeout polecenia), 126 (brak uprawnień wykonania),
# 127 (brak binarki) oraz sygnały (>=128) oznaczają awarię sondy i zwracają rc=2 (error), NIGDY pass/denied!
wlb_is_infra_error() {
  local rc=$1
  case $rc in
    2 | 6 | 7 | 28 | 35 | 52 | 56 | 124 | 126 | 127) return 0 ;;
    *)
      if ((rc >= 128)); then return 0; fi
      return 1
      ;;
  esac
}

wlb_ch_surface() {
  case $1 in
    JL-*) echo jupyter ;;
    JM-*) echo jamovi ;;
    DT-*) echo desktop ;;
    NET-*) echo network ;;
    RS-*) echo rstudio ;;
    CL-*) echo client ;;
    *) echo unknown ;;
  esac
}

wlb_ch_owner() {
  case $(wlb_ch_surface "$1") in
    jamovi) echo histologia ;;
    rstudio) echo rstudio ;;
    *) echo platform ;;
  esac
}

wlb_ch_required() {
  case $1 in
    JM-*) echo 0 ;;               # jamovi opcjonalne (specyficzne dla flavora histologia)
    RS-*) echo 0 ;;               # rstudio placeholder capture
    CL-*) echo 0 ;;               # client known_open (raport ryzyka, nie asercja)
    JL-CONTENTS-BASE64) echo 0 ;; # known_open
    *) echo 1 ;;
  esac
}

# wlb_ch_record ID KIERUNEK OCZEKIWANIE OBSERWACJA WERDYKT OPIS [KONTROLA] [REQUIRED]
wlb_ch_record() {
  local id=$1 dir=$2 exp=$3 obs=$4 verdict=$5 desc=${6:-} control=${7:-0} req=${8:-1}
  local surface owner
  surface=$(wlb_ch_surface "$id")
  owner=$(wlb_ch_owner "$id")
  desc=${desc//$'\t'/ }
  obs=${obs//$'\t'/ }
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$id" "$surface" "$dir" "$exp" "$obs" "$verdict" "$owner" "$control" "$req" "$desc" >>"$WLB_CH_ROWS"
  case $verdict in
    pass) ok "$id: $desc" ;;
    fail)
      if ((req == 1 && WLB_CH_GATING == 1)); then
        ko "$id: $desc (obserwacja: $obs)"
      else
        skip "$id [MISMATCH]: $desc — $obs"
      fi
      ;;
    error)
      if ((req == 1 && WLB_CH_GATING == 1)); then
        ko "$id [ERROR]: $desc (awaria sondy: $obs)"
      else
        skip "$id [ERROR]: $desc — awaria sondy: $obs"
      fi
      ;;
    skip) skip "$id: $desc — $obs" ;;
    known_open) skip "known_open $id (owner=$owner): $desc" ;;
  esac
}

# wlb_probe ID KIERUNEK OCZEKIWANIE OPIS -- POLECENIE...
# 0 = obserwacja zgodna z oczekiwaniem; 1 = niezgodność; 2 = awaria sondy/harnessu (error).
wlb_probe() {
  local id=$1 dir=$2 exp=$3 desc=$4
  shift 4
  [[ ${1:-} == -- ]] && shift
  local rc obs verdict surface state req
  WLB_CH_OBS=""
  WLB_CH_ALWAYS_FAIL=0
  "$@"
  rc=$?
  obs=${WLB_CH_OBS:-rc=$rc}
  surface=$(wlb_ch_surface "$id")
  state=${WLB_CH_CTRL[$surface]:-1}
  req=$(wlb_ch_required "$id")

  if ((rc == 2)) || wlb_is_infra_error "$rc"; then
    # Awaria sondy / brak narzędzia / timeout / błąd curl / brak fixture — NIGDY fałszywy pass/denied!
    verdict=error
    if ((WLB_CH_CONTROL == 1)); then
      WLB_CH_CTRL[$surface]=0
    fi
  elif ((WLB_CH_ALWAYS_FAIL == 1)); then
    if ((rc == 0)); then verdict=pass; else verdict=fail; fi
  elif ((WLB_CH_CONTROL == 1)); then
    if ((rc == 0)); then
      verdict=pass
      WLB_CH_CTRL[$surface]=1
    else
      verdict=fail
      WLB_CH_CTRL[$surface]=0
    fi
  elif ((state == 0)); then
    verdict=error
    obs="$obs; kontrola pozytywna grupy $surface nie przeszła"
  elif ((rc == 0)); then
    verdict=pass
  else
    verdict=fail
  fi

  wlb_ch_record "$id" "$dir" "$exp" "$obs" "$verdict" "$desc" "$WLB_CH_CONTROL" "$req"
  WLB_CH_CONTROL=0
}

wlb_control() {
  WLB_CH_CONTROL=1
  wlb_probe "$@"
  WLB_CH_CONTROL=0
}

wlb_known_open() {
  local id=$1 dir=$2 desc=$3
  local req
  req=$(wlb_ch_required "$id")
  wlb_ch_record "$id" "$dir" known_open "n/a" known_open "$desc" 0 "$req"
}

# wlb_expect_exit OCZEKIWANE(nonzero|N) POLECENIE... — normalizuje kod wyjścia sondy.
# Kody awarii infrastruktury i curla (124, 126, 127, 6, 7, 28, 35, 52, 56, >=128) zwracają rc=2 (error).
wlb_expect_exit() {
  local want=$1 rc
  shift
  "$@"
  rc=$?
  if wlb_is_infra_error "$rc"; then
    WLB_CH_OBS="awaria sondy: rc=$rc"
    return 2
  fi
  [[ -n ${WLB_CH_OBS:-} ]] || WLB_CH_OBS="rc=$rc"
  if [[ $want == nonzero ]]; then
    if ((rc != 0)); then return 0; else return 1; fi
  else
    if ((rc == want)); then return 0; else return 1; fi
  fi
}

# wlb_as_fs read|write KATALOG — system plików widziany przez konto badacza.
wlb_as_fs() {
  local op=$1 path=$2 rc
  id "jupyter-$R1" >/dev/null 2>&1 || {
    WLB_CH_OBS="brak konta jupyter-$R1"
    return 2
  }
  if [[ ! -d $path ]]; then
    WLB_CH_OBS="awaria fixture: brak katalogu $path"
    return 2
  fi
  if [[ $op == read ]]; then
    as "$R1" test -r "$path"
  else
    # shellcheck disable=SC2016 # $1 rozwija powłoka-dziecko (as)
    as "$R1" sh -c 'printf wlb >"$1/wlb-kanaly-probe"' sh "$path" 2>/dev/null
  fi
  rc=$?
  if wlb_is_infra_error "$rc"; then
    WLB_CH_OBS="awaria as_fs: rc=$rc ($op $path)"
    return 2
  fi
  WLB_CH_OBS="rc=$rc ($op $path)"
  return "$rc"
}

# wlb_jamovi SNIPPET — powłoka w sandboxie Flatpaka jamovi (bez GUI/X).
wlb_jamovi() {
  local rc
  flatpak info --system org.jamovi.jamovi >/dev/null 2>&1 || {
    WLB_CH_OBS="brak org.jamovi.jamovi (Flatpak)"
    return 2
  }
  if [[ $1 == *wlb-kanaly-probe.txt* ]] && ! test -f "$WLB_R1_HOME/wlb-kanaly-probe.txt"; then
    WLB_CH_OBS="awaria fixture: brak pliku $WLB_R1_HOME/wlb-kanaly-probe.txt dla jamovi"
    return 2
  fi
  as "$R1" env XDG_RUNTIME_DIR="$WLB_CH_JAMOVI_RUNTIME" \
    timeout --kill-after=5s 60s flatpak run --command=sh org.jamovi.jamovi -c "$1" >/dev/null 2>&1
  rc=$?
  if wlb_is_infra_error "$rc"; then
    WLB_CH_OBS="awaria Flatpak jamovi: rc=$rc"
    return 2
  fi
  WLB_CH_OBS="rc=$rc (jamovi)"
  return "$rc"
}

# wlb_http METODA ŚCIEŻKA DANE KODY... — żądanie z sesją serwera notebooków.
wlb_http() {
  local method=$1 path=$2 data=$3
  shift 3
  local code args=(-X "$method") want rc
  ((WLB_CH_JUPYTER_OK == 1)) || {
    WLB_CH_OBS="brak sesji JupyterLab / awaria fixture (WLB_CH_JUPYTER_OK=0; ${WLB_CH_SETUP_ERR:-setup nieukończony})"
    return 2
  }
  command -v curl >/dev/null 2>&1 || {
    WLB_CH_OBS="brak narzędzia curl"
    return 2
  }

  # Weryfikacja fixture, jeśli ścieżka odwołuje się do pliku testowego badacza
  case $path in
    *wlb-kanaly-probe.csv*)
      test -f "${WLB_R1_HOME:-}/wlb-kanaly-probe.csv" || {
        WLB_CH_OBS="awaria fixture: brak pliku ${WLB_R1_HOME:-}/wlb-kanaly-probe.csv"
        return 2
      }
      ;;
    *wlb-kanaly-probe.ipynb*)
      test -f "${WLB_R1_HOME:-}/wlb-kanaly-probe.ipynb" || {
        WLB_CH_OBS="awaria fixture: brak pliku ${WLB_R1_HOME:-}/wlb-kanaly-probe.ipynb"
        return 2
      }
      ;;
    *wlb-kanaly-probe.txt*)
      test -f "${WLB_R1_HOME:-}/wlb-kanaly-probe.txt" || {
        WLB_CH_OBS="awaria fixture: brak pliku ${WLB_R1_HOME:-}/wlb-kanaly-probe.txt"
        return 2
      }
      ;;
    *wlb-passwd-link*)
      test -L "${WLB_R1_HOME:-}/wlb-passwd-link" || {
        WLB_CH_OBS="awaria fixture: brak symlinka ${WLB_R1_HOME:-}/wlb-passwd-link"
        return 2
      }
      ;;
  esac

  [[ -n $data ]] && args+=(--data "$data")
  [[ -n ${WLB_CH_XSRF:-} ]] && args+=(-H "X-XSRFToken: $WLB_CH_XSRF")
  code=$(curl -s -o /dev/null -w '%{http_code}' --path-as-is --max-time 20 \
    -b "$WLB_CH_JAR" -c "$WLB_CH_JAR" "${args[@]}" "$HUB$path" 2>/dev/null)
  rc=$?
  if ((rc != 0)); then
    WLB_CH_OBS="awaria curl HTTP: rc=$rc ($method $path)"
    return 2
  fi
  if [[ -z $code || $code == "000" ]] || ! [[ $code =~ ^[1-5][0-9][0-9]$ ]]; then
    WLB_CH_OBS="awaria HTTP: brak statusu (${code:-brak}) ($method $path)"
    return 2
  fi
  WLB_CH_OBS="HTTP $code ($method $path)"
  for want in "$@"; do
    [[ $code == "$want" ]] && return 0
  done
  return 1
}

# wlb_net proxy|direct CEL OCZEKIWANE(status lub nonzero).
wlb_net() {
  local via=$1 target=$2 want=$3 code rc
  command -v curl >/dev/null 2>&1 || {
    WLB_CH_OBS="brak narzędzia curl"
    return 2
  }
  if [[ $via == proxy ]]; then
    [[ -n $WLB_CH_PROXY ]] || {
      WLB_CH_OBS="brak proxy (--proxy-allowlist / http_proxy w /etc/environment)"
      return 2
    }
    code=$(as "$R1" curl -q -s -o /dev/null -w '%{http_code}' --noproxy '' -x "$WLB_CH_PROXY" \
      --max-time 8 "$target" 2>/dev/null)
    rc=$?
    if ((rc != 0)); then
      WLB_CH_OBS="awaria curl proxy: rc=$rc"
      return 2
    fi
    if [[ -z $code || $code == "000" ]] || ! [[ $code =~ ^[1-5][0-9][0-9]$ ]]; then
      WLB_CH_OBS="awaria proxy: brak statusu (${code:-brak})"
      return 2
    fi
    WLB_CH_OBS="HTTP $code ($target via proxy)"
    [[ $code == "$want" ]] && return 0
    return 1
  fi
  # direct
  as "$R1" curl -q -s -o /dev/null --noproxy '*' --max-time 5 "$target" >/dev/null 2>&1
  rc=$?
  if ((rc == 124 || rc == 126 || rc == 127 || rc >= 128)); then
    WLB_CH_OBS="awaria curl direct: rc=$rc"
    return 2
  fi
  WLB_CH_OBS="rc=$rc ($target direct)"
  if [[ $want == nonzero ]]; then
    if ((rc != 0)); then return 0; else return 1; fi
  else
    if ((rc == want)); then return 0; else return 1; fi
  fi
}

# wlb_version PAKIET WERSJA — dryf wersji zawsze FAIL (wymaga re-audytu kanałów).
wlb_version() {
  local pkg=$1 want=$2 ver
  [[ -x /opt/tljh/user/bin/python ]] || {
    WLB_CH_OBS="brak interpretera /opt/tljh/user/bin/python"
    return 2
  }
  ver=$(/opt/tljh/user/bin/python -c 'import importlib.metadata as m, sys; print(m.version(sys.argv[1]))' \
    "$pkg" 2>/dev/null) || {
    WLB_CH_OBS="błąd odczytu wersji pakietu $pkg"
    return 2
  }
  WLB_CH_OBS="version=$ver"
  WLB_CH_ALWAYS_FAIL=1
  [[ $ver == "$want" ]]
}

wlb_ch_proxy_url() {
  if ((WLB_CH_FLAG_PROXY == 1)); then
    echo "http://10.0.2.2:3128"
    return 0
  fi
  sed -n 's/^http_proxy=//p' /etc/environment 2>/dev/null | tail -1
}

wlb_ch_jupyter_setup() {
  id "jupyter-$R1" >/dev/null 2>&1 || {
    WLB_CH_SETUP_ERR="brak konta jupyter-$R1"
    return 1
  }
  if [[ ! -s $WLB_CH_JAR ]]; then
    hub_login "$R1" "${PW[$R1]}" >/dev/null 2>&1 || {
      WLB_CH_SETUP_ERR="błąd logowania hub_login dla $R1"
      return 1
    }
  fi
  hub_spawn "$R1" >/dev/null 2>&1 || {
    WLB_CH_SETUP_ERR="błąd startu serwera hub_spawn dla $R1"
    return 1
  }
  curl -s -o /dev/null -b "$WLB_CH_JAR" -c "$WLB_CH_JAR" -L --max-time 25 "$HUB/user/$R1/lab" || {
    WLB_CH_SETUP_ERR="błąd pobrania strony lab dla $R1"
    return 1
  }
  WLB_CH_XSRF=$(awk '$6 == "_xsrf" {print $7}' "$WLB_CH_JAR" 2>/dev/null | tail -1)

  # Przygotowanie plików testowych w domowym katalogu badacza ($WLB_R1_HOME, nie /root!)
  as "$R1" sh -c "printf 'id,wynik\n' >\"$WLB_R1_HOME/wlb-kanaly-probe.csv\"" 2>/dev/null || {
    WLB_CH_SETUP_ERR="błąd tworzenia fixture probe.csv w $WLB_R1_HOME"
    return 1
  }
  as "$R1" sh -c "printf '{\"cells\":[],\"metadata\":{},\"nbformat\":4,\"nbformat_minor\":2}' >\"$WLB_R1_HOME/wlb-kanaly-probe.ipynb\"" 2>/dev/null || {
    WLB_CH_SETUP_ERR="błąd tworzenia fixture probe.ipynb w $WLB_R1_HOME"
    return 1
  }
  as "$R1" sh -c "printf wlb >\"$WLB_R1_HOME/wlb-kanaly-probe.txt\"" 2>/dev/null || {
    WLB_CH_SETUP_ERR="błąd tworzenia fixture probe.txt w $WLB_R1_HOME"
    return 1
  }
  as "$R1" ln -sfn /etc/passwd "$WLB_R1_HOME/wlb-passwd-link" 2>/dev/null || {
    WLB_CH_SETUP_ERR="błąd tworzenia symlinka passwd w $WLB_R1_HOME"
    return 1
  }

  as "$R1" test -f "$WLB_R1_HOME/wlb-kanaly-probe.csv" || {
    WLB_CH_SETUP_ERR="weryfikacja fixture: brak pliku probe.csv"
    return 1
  }
  as "$R1" test -f "$WLB_R1_HOME/wlb-kanaly-probe.ipynb" || {
    WLB_CH_SETUP_ERR="weryfikacja fixture: brak pliku probe.ipynb"
    return 1
  }
  as "$R1" test -f "$WLB_R1_HOME/wlb-kanaly-probe.txt" || {
    WLB_CH_SETUP_ERR="weryfikacja fixture: brak pliku probe.txt"
    return 1
  }
  as "$R1" test -L "$WLB_R1_HOME/wlb-passwd-link" || {
    WLB_CH_SETUP_ERR="weryfikacja fixture: brak symlinka passwd"
    return 1
  }
  return 0
}

# --- Tryb self-test (smoke test bez VM) ---
if [[ ${1:-} == "--self-test" ]]; then
  set -u
  set +e
  ST_FAIL=0
  st_assert() {
    local desc=$1 expected=$2 actual=$3
    if [[ $expected == "$actual" ]]; then
      echo "  PASS  $desc"
    else
      echo "  FAIL  $desc (oczekiwano: $expected, otrzymano: $actual)"
      ST_FAIL=$((ST_FAIL + 1))
    fi
  }

  echo "== Self-test harnessu kanałów (#292) =="

  # --- Testy wlb_expect_exit ---
  wlb_expect_exit 0 true
  st_assert "wlb_expect_exit 0 na sukcesie -> 0" 0 $?
  wlb_expect_exit 0 false
  st_assert "wlb_expect_exit 0 na porażce -> 1" 1 $?
  wlb_expect_exit nonzero false
  st_assert "wlb_expect_exit nonzero na kodzie 1 -> 0" 0 $?
  wlb_expect_exit nonzero true
  st_assert "wlb_expect_exit nonzero na kodzie 0 -> 1" 1 $?

  # Sprawdzenie mapowania błędów infrastrukturalnych na rc=2 (error, NIGDY pass/denied)
  wlb_expect_exit nonzero sh -c 'exit 124'
  st_assert "wlb_expect_exit timeout 124 -> rc=2 (awaria)" 2 $?
  wlb_expect_exit nonzero sh -c 'exit 126'
  st_assert "wlb_expect_exit permission 126 -> rc=2 (awaria)" 2 $?
  wlb_expect_exit nonzero sh -c 'exit 127'
  st_assert "wlb_expect_exit command-not-found 127 -> rc=2 (awaria)" 2 $?
  wlb_expect_exit nonzero sh -c 'exit 137'
  st_assert "wlb_expect_exit sigkill 137 -> rc=2 (awaria)" 2 $?
  wlb_expect_exit 0 sh -c 'exit 127'
  st_assert "wlb_expect_exit 0 na 127 -> rc=2 (awaria)" 2 $?

  # Kody błędu curla (6 DNS, 7 connect, 28 timeout, 35 TLS, 52 empty, 56 recv)
  wlb_expect_exit nonzero sh -c 'exit 6'
  st_assert "wlb_expect_exit curl DNS 6 -> rc=2 (awaria)" 2 $?
  wlb_expect_exit nonzero sh -c 'exit 7'
  st_assert "wlb_expect_exit curl connect 7 -> rc=2 (awaria)" 2 $?
  wlb_expect_exit nonzero sh -c 'exit 28'
  st_assert "wlb_expect_exit curl timeout 28 -> rc=2 (awaria)" 2 $?
  wlb_expect_exit nonzero sh -c 'exit 35'
  st_assert "wlb_expect_exit curl TLS 35 -> rc=2 (awaria)" 2 $?
  wlb_expect_exit nonzero sh -c 'exit 52'
  st_assert "wlb_expect_exit curl empty 52 -> rc=2 (awaria)" 2 $?
  wlb_expect_exit nonzero sh -c 'exit 56'
  st_assert "wlb_expect_exit curl recv 56 -> rc=2 (awaria)" 2 $?
  wlb_expect_exit 0 sh -c 'exit 7'
  st_assert "wlb_expect_exit 0 na curl 7 -> rc=2 (awaria)" 2 $?
  wlb_expect_exit 0 sh -c 'exit 28'
  st_assert "wlb_expect_exit 0 na curl 28 -> rc=2 (awaria)" 2 $?

  # --- Testy wlb_http z atrapą curl oraz weryfikacją fixture ---
  ST_TMP_DIR=$(mktemp -d /tmp/wlb-self-test-XXXXXX)
  WLB_CH_DIR=$ST_TMP_DIR
  WLB_CH_ROWS=$ST_TMP_DIR/rows.tsv
  : >"$WLB_CH_ROWS"

  # Brak sesji JupyterLab -> rc=2
  WLB_CH_JUPYTER_OK=0
  wlb_http GET "/user/u01/api/contents" "" 200
  st_assert "wlb_http gdy WLB_CH_JUPYTER_OK=0 -> rc=2" 2 $?

  # Sesja JupyterLab aktywna
  WLB_CH_JUPYTER_OK=1
  WLB_R1_HOME=$ST_TMP_DIR/home-u01
  mkdir -p "$WLB_R1_HOME"

  # Awaria fixture: plik wlb-kanaly-probe.csv nie istnieje
  wlb_http GET "/user/u01/files/wlb-kanaly-probe.csv?download=1" "" 403
  st_assert "wlb_http brak fixture probe.csv -> rc=2 (awaria)" 2 $?

  # Utworzenie fixture
  touch "$WLB_R1_HOME/wlb-kanaly-probe.csv"

  # Atrapa curl sterowana trybem ST_CURL_MODE
  # shellcheck disable=SC2329 # atrapa curl dla self-testu
  curl() {
    case ${ST_CURL_MODE:-default} in
      ret7) return 7 ;;
      ret28) return 28 ;;
      ret6) return 6 ;;
      code000)
        echo "000"
        return 0
        ;;
      code_empty)
        echo ""
        return 0
        ;;
      code403)
        echo "403"
        return 0
        ;;
      code200)
        echo "200"
        return 0
        ;;
      *) return 1 ;;
    esac
  }

  ST_CURL_MODE=ret7
  wlb_http GET "/user/u01/files/wlb-kanaly-probe.csv?download=1" "" 403
  st_assert "wlb_http gdy curl exit 7 (brak połączenia) -> rc=2" 2 $?

  ST_CURL_MODE=ret28
  wlb_http GET "/user/u01/files/wlb-kanaly-probe.csv?download=1" "" 403
  st_assert "wlb_http gdy curl exit 28 (timeout) -> rc=2" 2 $?

  ST_CURL_MODE=ret6
  wlb_http GET "/user/u01/files/wlb-kanaly-probe.csv?download=1" "" 403
  st_assert "wlb_http gdy curl exit 6 (brak DNS) -> rc=2" 2 $?

  # Atrapa curl symulująca brak statusu HTTP (kod 000 lub pusty)
  ST_CURL_MODE=code000
  wlb_http GET "/user/u01/files/wlb-kanaly-probe.csv?download=1" "" 403
  st_assert "wlb_http gdy kod 000 -> rc=2" 2 $?

  ST_CURL_MODE=code_empty
  wlb_http GET "/user/u01/files/wlb-kanaly-probe.csv?download=1" "" 403
  st_assert "wlb_http gdy brak statusu -> rc=2" 2 $?

  # Atrapa curl symulująca poprawną odpowiedź 403 (oczekiwane 403 -> rc=0)
  ST_CURL_MODE=code403
  wlb_http GET "/user/u01/files/wlb-kanaly-probe.csv?download=1" "" 403
  st_assert "wlb_http gdy HTTP 403 i oczekiwane 403 -> rc=0 (pass)" 0 $?

  # Atrapa curl symulująca niezgodną odpowiedź 200 (oczekiwane 403 -> rc=1)
  ST_CURL_MODE=code200
  wlb_http GET "/user/u01/files/wlb-kanaly-probe.csv?download=1" "" 403
  st_assert "wlb_http gdy HTTP 200 i oczekiwane 403 -> rc=1 (fail)" 1 $?

  unset -f curl

  # --- Testy ścieżki probe i bramkowania gating (Requirement 2) ---
  ST_MOCK_OK=0
  ST_MOCK_KO=0
  ST_MOCK_SKIP=0
  ok() { ST_MOCK_OK=$((ST_MOCK_OK + 1)); }
  ko() { ST_MOCK_KO=$((ST_MOCK_KO + 1)); }
  skip() { ST_MOCK_SKIP=$((ST_MOCK_SKIP + 1)); }
  st_reset_mock() {
    ST_MOCK_OK=0
    ST_MOCK_KO=0
    ST_MOCK_SKIP=0
  }

  st_probe() { wlb_probe "$@"; }
  st_control() { wlb_control "$@"; }
  st_known_open() { wlb_known_open "$@"; }

  # Testy z WLB_CH_GATING=1 (bramkowanie aktywne)
  WLB_CH_GATING=1

  # Gating=1: required sonda z wynikiem fail -> MUSI być ko (blokująca)
  st_reset_mock
  st_probe DT-TEST-REQ-FAIL export denied "test required fail" -- false
  st_assert "gating=1 required+fail -> ko=1" 1 $ST_MOCK_KO
  st_assert "gating=1 required+fail -> skip=0" 0 $ST_MOCK_SKIP
  st_assert "gating=1 required+fail -> ok=0" 0 $ST_MOCK_OK

  # Gating=1: required sonda z wynikiem error (np. curl exit 7) -> MUSI być ko (blokująca)
  st_reset_mock
  st_probe DT-TEST-REQ-ERR export denied "test required error" -- sh -c 'exit 7'
  st_assert "gating=1 required+error (curl 7) -> ko=1" 1 $ST_MOCK_KO
  st_assert "gating=1 required+error (curl 7) -> skip=0" 0 $ST_MOCK_SKIP

  # Gating=1: required sonda z wynikiem error (rc=127) -> MUSI być ko (blokująca)
  st_reset_mock
  st_probe DT-TEST-REQ-ERR127 export denied "test required error 127" -- sh -c 'exit 127'
  st_assert "gating=1 required+error (127) -> ko=1" 1 $ST_MOCK_KO

  # Gating=1: non-required sonda (JM-*, required=0) z wynikiem fail -> skip (NIE ko!)
  st_reset_mock
  st_probe JM-TEST-OPT-FAIL export denied "test non-required fail" -- false
  st_assert "gating=1 non-required+fail -> ko=0" 0 $ST_MOCK_KO
  st_assert "gating=1 non-required+fail -> skip=1" 1 $ST_MOCK_SKIP

  # Gating=1: non-required sonda (JM-*, required=0) z wynikiem error -> skip (NIE ko!)
  st_reset_mock
  st_probe JM-TEST-OPT-ERR export denied "test non-required error" -- sh -c 'exit 28'
  st_assert "gating=1 non-required+error (timeout) -> ko=0" 0 $ST_MOCK_KO
  st_assert "gating=1 non-required+error (timeout) -> skip=1" 1 $ST_MOCK_SKIP

  # Gating=1: known_open (CL-*, wlb_known_open) -> skip (NIE ko!)
  st_reset_mock
  st_known_open CL-TEST-KO export "test known_open w gating"
  st_assert "gating=1 known_open -> ko=0" 0 $ST_MOCK_KO
  st_assert "gating=1 known_open -> skip=1" 1 $ST_MOCK_SKIP

  # Gating=1: sukces (pass) -> ok (nie ko, nie skip)
  st_reset_mock
  st_probe DT-TEST-PASS export denied "test pass" -- true
  st_assert "gating=1 pass -> ok=1" 1 $ST_MOCK_OK
  st_assert "gating=1 pass -> ko=0" 0 $ST_MOCK_KO

  # Testy z WLB_CH_GATING=0 (bramkowanie wyłączone — tryb diagnostyczny)
  WLB_CH_GATING=0

  # Gating=0: required sonda z wynikiem fail -> skip (NIE ko, NIE pass)
  st_reset_mock
  st_probe DT-TEST-REQ-FAIL export denied "test required fail bez gatingu" -- false
  st_assert "gating=0 required+fail -> ko=0" 0 $ST_MOCK_KO
  st_assert "gating=0 required+fail -> skip=1" 1 $ST_MOCK_SKIP
  st_assert "gating=0 required+fail -> ok=0" 0 $ST_MOCK_OK

  # Gating=0: required sonda z wynikiem error -> skip (NIE ko, NIE pass)
  st_reset_mock
  st_probe DT-TEST-REQ-ERR export denied "test required error bez gatingu" -- sh -c 'exit 7'
  st_assert "gating=0 required+error -> ko=0" 0 $ST_MOCK_KO
  st_assert "gating=0 required+error -> skip=1" 1 $ST_MOCK_SKIP

  # Gating=0: non-required sonda z wynikiem fail -> skip
  st_reset_mock
  st_probe JM-TEST-OPT-FAIL export denied "test non-required fail bez gatingu" -- false
  st_assert "gating=0 non-required+fail -> skip=1" 1 $ST_MOCK_SKIP
  st_assert "gating=0 non-required+fail -> ko=0" 0 $ST_MOCK_KO

  # Gating=0: known_open -> skip
  st_reset_mock
  st_known_open CL-TEST-KO export "test known_open bez gatingu"
  st_assert "gating=0 known_open -> skip=1" 1 $ST_MOCK_SKIP

  # Kontrola pozytywna unieważniająca odmowy w grupie:
  st_reset_mock
  WLB_CH_GATING=1
  # Nieudana kontrola pozytywna w grupie desktop (DT-)
  st_control DT-CTRL-TEST internal allowed "kontrola pozytywna fail" -- false
  st_assert "kontrola pozytywna fail -> ko=1" 1 $ST_MOCK_KO
  st_reset_mock
  # Kolejna sonda denied w tej samej grupie MUSI dać error (unieważniona odmowa) -> ko w gating
  st_probe DT-TEST-DENIED-UNSEEN export denied "sonda po padniętej kontroli" -- true
  st_assert "sonda denied po padniętej kontroli daje error -> ko=1" 1 $ST_MOCK_KO

  rm -rf "$ST_TMP_DIR"

  if ((ST_FAIL == 0)); then
    echo "Self-test passed!"
    exit 0
  else
    echo "Self-test FAILED ($ST_FAIL błędów)"
    exit 1
  fi
fi

echo "== Kanały eksportu/importu (#292 — matryca tests/channels.yaml) =="

rm -rf "$WLB_CH_DIR" "$WLB_CH_JAMOVI_RUNTIME"
mkdir -p "$WLB_CH_DIR"
chmod 755 "$WLB_CH_DIR"
: >"$WLB_CH_ROWS"

WLB_CH_PROXY=$(wlb_ch_proxy_url)
if ((WLB_CH_FLAG_PROXY == 1)); then
  WLB_CH_MIRROR=http://pypi.mirror.local/
else
  WLB_CH_MIRROR=${WLB_CH_MIRROR_TARGET:-https://pypi.wlb.local/simple/}
fi
install -d -m 700 -o "jupyter-$R1" -g "jupyter-$R1" "$WLB_CH_JAMOVI_RUNTIME" 2>/dev/null || true

if wlb_ch_jupyter_setup; then
  WLB_CH_JUPYTER_OK=1
else
  skip "Kanały Jupyter: brak sesji serwera notebooków (harness) — grupa SKIP, nie PASS"
fi

# --- Jupyter HTTP: kontrola pozytywna najpierw, potem kanały zamknięte i warianty ścieżek ---
wlb_control JL-API-READ internal allowed "odczyt /api/contents w domu (kontrola sesji)" -- \
  wlb_http GET "/user/$R1/api/contents?content=0" "" 200
wlb_probe JL-SAVE internal allowed "zapis pliku w domu przez /api/contents" -- \
  wlb_http PUT "/user/$R1/api/contents/wlb-kanaly-probe.txt" \
  '{"type": "file", "format": "text", "content": "wlb-kanaly-probe"}' 200 201
wlb_probe JL-FILES-DL export denied "pobranie /files?download=1" -- \
  wlb_http GET "/user/$R1/files/wlb-kanaly-probe.csv?download=1" "" 403
wlb_probe JL-NBCONVERT export denied "eksport /nbconvert/html/wlb-kanaly-probe.ipynb" -- \
  wlb_http GET "/user/$R1/nbconvert/html/wlb-kanaly-probe.ipynb?download=1" "" 403
wlb_known_open JL-CONTENTS-BASE64 export "pobranie treści pliku base64 przez Contents API (?content=1&format=base64)"
wlb_probe JL-TRAVERSAL-DOTDOT export denied "contents ../../etc/passwd" -- \
  wlb_http GET "/user/$R1/api/contents/../../etc/passwd?content=1" "" 403
wlb_probe JL-TRAVERSAL-ENCODED export denied "contents %2e%2e/%2e%2e/etc/passwd" -- \
  wlb_http GET "/user/$R1/api/contents/%2e%2e/%2e%2e/etc/passwd?content=1" "" 403
wlb_probe JL-TRAVERSAL-SLASH export denied "contents //etc/passwd" -- \
  wlb_http GET "/user/$R1/api/contents//etc/passwd?content=1" "" 403
wlb_probe JL-TRAVERSAL-DOT export denied "contents ./../../etc/passwd" -- \
  wlb_http GET "/user/$R1/api/contents/./../../etc/passwd?content=1" "" 403
wlb_probe JL-TRAVERSAL-ABS export denied "contents %2Fetc%2Fpasswd" -- \
  wlb_http GET "/user/$R1/api/contents/%2Fetc%2Fpasswd?content=1" "" 403
wlb_probe JL-TRAVERSAL-SYMLINK export denied "contents symlink w domu -> /etc/passwd" -- \
  wlb_http GET "/user/$R1/api/contents/wlb-passwd-link?content=1" "" 403

# --- jamovi: sandbox Flatpaka; kontrola = odczyt własnego domu (w /workspace) ---
# shellcheck disable=SC2016 # $HOME rozwija powłoka-dziecko (sandbox jamovi)
wlb_control JM-SANDBOX-HOME-READ internal allowed "jamovi czyta plik z domu badacza (kontrola)" -- \
  wlb_expect_exit 0 wlb_jamovi 'test -r "$HOME/wlb-kanaly-probe.txt"'
wlb_probe JM-SLUIZA-IN-READ import allowed "jamovi czyta /sluza-in" -- \
  wlb_expect_exit 0 wlb_jamovi 'test -r /sluza-in'
wlb_probe JM-SLUIZA-OUT-WRITE export allowed "jamovi pisze do /sluza-out" -- \
  wlb_expect_exit 0 wlb_jamovi 'test -w /sluza-out'
wlb_probe JM-ETC-SHADOW-READ export denied "jamovi nie czyta /etc/shadow" -- \
  wlb_expect_exit nonzero wlb_jamovi 'test -r /etc/shadow'
wlb_probe JM-U02-READ export denied "jamovi nie czyta domu innego badacza" -- \
  wlb_expect_exit nonzero wlb_jamovi "test -r /workspace/jupyter-$R2"
wlb_probe JM-U02-WRITE import denied "jamovi nie pisze do domu innego badacza" -- \
  wlb_expect_exit nonzero wlb_jamovi "test -w /workspace/jupyter-$R2"

# --- Pulpit: system plików badacza + pin audytowanej wersji jrdp ---
wlb_control DT-SLUIZA-OUT-WRITE export allowed "badacz tworzy plik w /sluza-out (kontrola)" -- \
  wlb_expect_exit 0 wlb_as_fs write /sluza-out
wlb_probe DT-SLUIZA-IN-WRITE import denied "badacz nie tworzy pliku w /sluza-in" -- \
  wlb_expect_exit nonzero wlb_as_fs write /sluza-in
as "$R1" rm -f /sluza-out/wlb-kanaly-probe 2>/dev/null || true
wlb_probe DT-JRDP-VERSION internal allowed "jrdp w wersji audytowanej (3.0.1)" -- \
  wlb_version jupyter-remote-desktop-proxy 3.0.1

# --- Sieć: proxy z allowlistą (kontrola) i egress bezpośredni (nftables) ---
wlb_control NET-PROXY-MIRROR export allowed "proxy przepuszcza mirror (kontrola)" -- \
  wlb_net proxy "$WLB_CH_MIRROR" 200
wlb_probe NET-PROXY-EXTERNAL export denied "proxy blokuje example.com" -- \
  wlb_net proxy http://example.com/ 403
wlb_probe NET-DIRECT-IP export denied "bezpośrednie połączenie po IP zablokowane" -- \
  wlb_net direct http://1.1.1.1/ nonzero

# --- RStudio: known_open (brak fixture ścieżek) — tylko raport, nie asercja ---
wlb_known_open RS-TRANSFER-PATHS export "RStudio: ścieżki upload/download/export bez fixture \
  tests/fixtures/rstudio-transfer-paths.txt (owner=rstudio; TODO capture mitmproxy, #292 PR-T3)"

# --- Klient niezarządzany: known_open (raport ryzyka, nie asercje) ---
wlb_known_open CL-PRINT export "druk z przeglądarki klienta (Ctrl+P)"
wlb_known_open CL-SAVE-PAGE export "zapis strony w przeglądarce klienta (Save Page As)"
wlb_known_open CL-CLIPBOARD export "schowek systemowy hosta klienta"
wlb_known_open CL-SCREENSHOT export "zrzut ekranu po stronie klienta"

# Sprzątanie plików sond w domu badacza ($WLB_R1_HOME).
as "$R1" rm -f "$WLB_R1_HOME/wlb-kanaly-probe.txt" "$WLB_R1_HOME/wlb-kanaly-probe.csv" \
  "$WLB_R1_HOME/wlb-kanaly-probe.ipynb" "$WLB_R1_HOME/wlb-passwd-link" 2>/dev/null || true

# --- Raport: JSON + tabela markdown (per flavor; ci/integration.sh kopiuje do build/ci-logs) ---
python3 - "$WLB_CH_ROWS" "$WLB_CH_DIR" "$WLB_CH_GATING" <<'PY'
import datetime
import json
import pathlib
import sys

rows_path, outdir, gating = sys.argv[1], pathlib.Path(sys.argv[2]), sys.argv[3] == "1"
rows = []
for line in pathlib.Path(rows_path).read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    fields = line.split("\t", 9)
    while len(fields) < 10:
        fields.append("")
    channel_id, surface, direction, expected, observed, verdict, owner, control, req, detail = fields
    rows.append(
        {
            "id": channel_id,
            "surface": surface,
            "direction": direction,
            "expected": expected,
            "observed": observed,
            "verdict": verdict,
            "owner": owner,
            "control": control == "1",
            "required": req == "1",
            "detail": detail,
        }
    )

summary = {name: sum(1 for row in rows if row["verdict"] == name) for name in ("pass", "fail", "skip", "error", "known_open")}
flavor = ""
release = pathlib.Path("/etc/wlb/image-release")
if release.is_file():
    for line in release.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("WLB_IMAGE_NAME="):
            flavor = line.split("=", 1)[1]
            break

report = {
    "schema": "wlb.channels-report/v1",
    "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "flavor": flavor,
    "gating": gating,
    "summary": summary,
    "channels": rows,
}
(outdir / "channels.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

table = ["| id | surface | direction | expected | observed | verdict | owner |", "|---|---|---|---|---|---|---|"]
table += [
    f"| `{row['id']}` | {row['surface']} | {row['direction']} | {row['expected']} | "
    f"{row['observed']} | **{row['verdict']}** | {row['owner']} |"
    for row in rows
]
(outdir / "channels.md").write_text("\n".join(table) + "\n", encoding="utf-8")
print(
    f"Kanały: {summary['pass']} PASS, {summary['fail']} FAIL, {summary['error']} ERROR, "
    f"{summary['skip']} SKIP, {summary['known_open']} known_open (gating={int(gating)}); raport: {outdir}/channels.json"
)
PY
cat "$WLB_CH_DIR/channels.md"

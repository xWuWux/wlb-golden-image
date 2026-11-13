#!/usr/bin/env bats
# Testy jednostkowe parsera kafelków .desktop → Exec (#314 część A):
# field-codes, pierwszy token, rozwiązywanie na PATH SESJI (nie roota), cel wrappera WLB.

load helpers

setup() {
  # shellcheck source=tests/lib/kafelki-exec.sh
  source "$REPO_ROOT/tests/lib/kafelki-exec.sh"
  W43_TMP="$BATS_TEST_TMPDIR/w43"
  mkdir -p "$W43_TMP/wrappers" "$W43_TMP/fsl/share/fsl/bin"
  W43_SESSION_PATH=/opt/tljh/user/bin:/bin:/usr/bin
  export W43_SESSION_PATH
  export W43_WRAPPER_DIRS="$W43_TMP/wrappers"
  export W43_FSL_PROFILE="$W43_TMP/fsl.sh"
}

tile() {
  local f=$1 exec=$2
  printf '[Desktop Entry]\nType=Application\nName=Test\nExec=%s\n' "$exec" >"$f"
}

@test "PATH sesji nie zawiera /usr/local/bin i zawiera /usr/bin (#199/#202)" {
  run w43_session_path
  [ "$status" -eq 0 ]
  [[ ":$output:" != *":/usr/local/bin:"* ]]
  [[ ":$output:" == *":/usr/bin:"* ]]
}

@test "Exec absolutny istniejący przechodzi" {
  tile "$W43_TMP/a.desktop" "/bin/sh %F"
  run w43_tile_ok "$W43_TMP/a.desktop"
  [ "$status" -eq 0 ]
}

@test "Exec goły rozwiązuje się na PATH sesji (/bin)" {
  tile "$W43_TMP/a.desktop" "sh %U"
  run w43_tile_ok "$W43_TMP/a.desktop"
  [ "$status" -eq 0 ]
}

@test "field-codes są odcinane (%f %F %u %U %i %c %k)" {
  tile "$W43_TMP/a.desktop" "/bin/sh %f %F %u %U %i %c %k"
  run w43_tile_ok "$W43_TMP/a.desktop"
  [ "$status" -eq 0 ]
}

@test "prefix env i przypisania VAR= są pomijane" {
  tile "$W43_TMP/a.desktop" "env LC_ALL=C /bin/sh %F"
  run w43_tile_ok "$W43_TMP/a.desktop"
  [ "$status" -eq 0 ]
}

@test "Exec goły nieobecny na PATH sesji jest odrzucany (nie roota)" {
  tile "$W43_TMP/a.desktop" "wlb-nie-ma-314 %F"
  run w43_tile_ok "$W43_TMP/a.desktop"
  [ "$status" -ne 0 ]
  [[ $output == *"nie istnieje"* ]]
}

@test "Exec absolutny nieistniejący jest odrzucany" {
  tile "$W43_TMP/a.desktop" "/usr/local/bin/wlb-nie-ma-314"
  run w43_tile_ok "$W43_TMP/a.desktop"
  [ "$status" -ne 0 ]
}

@test "brak linii Exec= jest błędem" {
  printf '[Desktop Entry]\nType=Application\nName=Test\n' >"$W43_TMP/a.desktop"
  run w43_tile_ok "$W43_TMP/a.desktop"
  [ "$status" -ne 0 ]
  [[ $output == *"brak linii Exec="* ]]
}

@test "wrapper z absolutnym istniejącym celem przechodzi" {
  printf '#!/bin/sh\nexec /bin/sh "$@"\n' >"$W43_TMP/wrappers/wlb-ok"
  chmod 755 "$W43_TMP/wrappers/wlb-ok"
  run w43_wrapper_target_ok "$W43_TMP/wrappers/wlb-ok"
  [ "$status" -eq 0 ]
}

@test "wrapper z nieistniejącym celem jest odrzucany" {
  printf '#!/bin/sh\nexec /bin/nie-ma-314 "$@"\n' >"$W43_TMP/wrappers/wlb-zly"
  chmod 755 "$W43_TMP/wrappers/wlb-zly"
  run w43_wrapper_target_ok "$W43_TMP/wrappers/wlb-zly"
  [ "$status" -ne 0 ]
}

@test "wrapper z gołym celem na PATH sesji przechodzi" {
  printf '#!/bin/sh\nexec sh "$@"\n' >"$W43_TMP/wrappers/wlb-sh"
  chmod 755 "$W43_TMP/wrappers/wlb-sh"
  run w43_wrapper_target_ok "$W43_TMP/wrappers/wlb-sh"
  [ "$status" -eq 0 ]
}

@test "wrapper źródłujący profil FSL znajduje cel w FSLDIR" {
  printf 'FSLDIR=%s\n' "$W43_TMP/fsl" >"$W43_FSL_PROFILE"
  printf '#!/bin/sh\n. /etc/profile.d/fsl.sh\nexec fsleyes "$@"\n' >"$W43_TMP/wrappers/wlb-fsleyes"
  chmod 755 "$W43_TMP/wrappers/wlb-fsleyes"
  printf '#!/bin/sh\n' >"$W43_TMP/fsl/share/fsl/bin/fsleyes"
  chmod 755 "$W43_TMP/fsl/share/fsl/bin/fsleyes"
  run w43_wrapper_target_ok "$W43_TMP/wrappers/wlb-fsleyes"
  [ "$status" -eq 0 ]
}

@test "wrapper FSL bez celu w FSLDIR jest odrzucany" {
  printf 'FSLDIR=%s\n' "$W43_TMP/fsl" >"$W43_FSL_PROFILE"
  printf '#!/bin/sh\n. /etc/profile.d/fsl.sh\nexec nie-ma-314 "$@"\n' >"$W43_TMP/wrappers/wlb-zly"
  chmod 755 "$W43_TMP/wrappers/wlb-zly"
  run w43_wrapper_target_ok "$W43_TMP/wrappers/wlb-zly"
  [ "$status" -ne 0 ]
}

@test "kafelek z wrapperem WLB bez celu jest odrzucany" {
  printf '#!/bin/sh\nexec /bin/nie-ma-314 "$@"\n' >"$W43_TMP/wrappers/wlb-zly"
  chmod 755 "$W43_TMP/wrappers/wlb-zly"
  tile "$W43_TMP/a.desktop" "$W43_TMP/wrappers/wlb-zly %F"
  run w43_tile_ok "$W43_TMP/a.desktop"
  [ "$status" -ne 0 ]
  [[ $output == *"wrapper"* ]]
}

@test "binarka (nie skrypt) nie jest analizowana jako wrapper" {
  printf '\177ELF\002\001\001' >"$W43_TMP/wrappers/wlb-bin"
  chmod 755 "$W43_TMP/wrappers/wlb-bin"
  run w43_wrapper_target_ok "$W43_TMP/wrappers/wlb-bin"
  [ "$status" -eq 0 ]
}

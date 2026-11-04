#!/usr/bin/env bats
# Raport rozmiaru obrazu (#135).

load helpers

setup() {
  setup_sandbox
  IMG="$BATS_TEST_TMPDIR/obraz.qcow2"
  : >"$IMG"
  # 80 GiB wirtualne, 10 GiB faktyczne
  printf '%s\n' '#!/usr/bin/env bash' \
    'echo "{\"virtual-size\": 85899345920, \"actual-size\": 10737418240}"' >"$STUBS/qemu-img"
  chmod +x "$STUBS/qemu-img"
  unset GITHUB_STEP_SUMMARY WLB_IMAGE_SIZE_MAX_GIB
}

@test "raport: wypisuje rozmiar wirtualny i faktyczny w GiB (#135)" {
  run "$REPO_ROOT/ci/image-size-report.sh" "$IMG" wlb-radiologia
  [ "$status" -eq 0 ]
  [[ $output == *"wirtualny 80.00 GiB, alokacja 10.00 GiB"* ]]
  [[ $output == *"| 80.00 GiB | 10.00 GiB |"* ]]
}

@test "raport: bez progu nie zawodzi nawet dla dużego pliku (#135)" {
  run "$REPO_ROOT/ci/image-size-report.sh" "$IMG"
  [ "$status" -eq 0 ]
}

@test "raport: przekroczenie progu WLB_IMAGE_SIZE_MAX_GIB kończy się błędem (#135)" {
  WLB_IMAGE_SIZE_MAX_GIB=5 run "$REPO_ROOT/ci/image-size-report.sh" "$IMG"
  [ "$status" -eq 1 ]
  [[ $output == *"przekracza próg 5 GiB"* ]]
}

@test "raport: rozmiar poniżej progu przechodzi (#135)" {
  WLB_IMAGE_SIZE_MAX_GIB=20 run "$REPO_ROOT/ci/image-size-report.sh" "$IMG"
  [ "$status" -eq 0 ]
}

@test "raport: brak obrazu lub argumentu to błąd (#135)" {
  run "$REPO_ROOT/ci/image-size-report.sh" "$BATS_TEST_TMPDIR/nie-ma.qcow2"
  [ "$status" -eq 1 ]
  run "$REPO_ROOT/ci/image-size-report.sh"
  [ "$status" -eq 1 ]
}

@test "brak pomiaru jest błędem również bez progu (#135)" {
  stub qemu-img 0 '{"virtual-size": 32}'
  run "$REPO_ROOT/ci/image-size-report.sh" "$IMG"
  [ "$status" -ne 0 ]
}

@test "próg jest dziesiętny, dokładny i nie interpretuje wyrażeń Bash (#135)" {
  WLB_IMAGE_SIZE_MAX_GIB=010 run "$REPO_ROOT/ci/image-size-report.sh" "$IMG"
  [ "$status" -eq 0 ]
  WLB_IMAGE_SIZE_MAX_GIB=5+5 run "$REPO_ROOT/ci/image-size-report.sh" "$IMG"
  [ "$status" -ne 0 ]
  stub qemu-img 0 '{"virtual-size": 21474836480, "actual-size": 10737418241}'
  WLB_IMAGE_SIZE_MAX_GIB=10 run "$REPO_ROOT/ci/image-size-report.sh" "$IMG"
  [ "$status" -ne 0 ]
}

@test "prawdziwy mały qcow2 daje raport i blokuje zerowy limit (#135)" {
  rm "$STUBS/qemu-img"
  command -v qemu-img >/dev/null || skip "wymaga qemu-img"
  qemu-img create -f qcow2 "$IMG" 64M
  run "$REPO_ROOT/ci/image-size-report.sh" "$IMG"
  [ "$status" -eq 0 ]
  WLB_IMAGE_SIZE_MAX_GIB=0 run "$REPO_ROOT/ci/image-size-report.sh" "$IMG"
  [ "$status" -ne 0 ]
}

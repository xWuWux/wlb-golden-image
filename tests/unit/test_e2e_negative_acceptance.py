"""Testy wspólnego kontraktu i realnej asercji negatywnej targetu E2E (#277, S2).

Nie kopiujemy logiki `test ! -e` do testu: uruchamiamy funkcję
`assert_no_e2e_fixture` z `tests/lib/e2e-fixture.sh` na atrapie rootfs.
Kontrakt ścieżek jest jeden (`ci/e2e-fixture-paths.txt`) i ten sam czyta
bramka wydania (`ci/e2e_release_gate.py`) oraz akceptacja.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import REPO_ROOT, load_script

CONTRACT_FILE = REPO_ROOT / "ci/e2e-fixture-paths.txt"
PULPIT_ACCEPTANCE = REPO_ROOT / "tests/acceptance.d/40-pulpit.sh"
HELPER = REPO_ROOT / "tests/lib/e2e-fixture.sh"
ROLE_TASKS = REPO_ROOT / "ansible/roles/desktop/tasks/main.yml"


def contract_paths() -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in CONTRACT_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def run_helper(root: Path, paths: tuple[str, ...] | None = None) -> subprocess.CompletedProcess[str]:
    """Uruchamia prawdziwą funkcję akceptacyjną z atrapą expect_ok i korzeniem testowym."""
    selected = contract_paths() if paths is None else paths
    quoted = " ".join(shlex.quote(path) for path in selected)
    script = f"""
set -uo pipefail
PASS=0
FAIL=0
expect_ok() {{
  local d=$1
  shift
  if "$@" >/dev/null 2>&1; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); fi
}}
WLB_E2E_FIXTURE_PATHS=({quoted})
source {shlex.quote(str(HELPER))}
assert_no_e2e_fixture {shlex.quote(str(root))}
rc=$?
echo "PASS=$PASS FAIL=$FAIL"
exit $rc
"""
    return subprocess.run(  # noqa: S603 # nosec B603
        ["/bin/bash", "-c", script], capture_output=True, text=True, check=False
    )


def test_contract_is_single_source_for_gate() -> None:
    """Bramka wydania czyta dokładnie ten sam plik kontraktu, co testy (#277)."""
    gate = load_script("wlb_e2e_release_gate", REPO_ROOT / "ci/e2e_release_gate.py")
    assert contract_paths() == gate.CONTRACT_PATHS


def test_ansible_role_installs_exactly_contract_paths() -> None:
    """Każda ścieżka instalowana przez rolę dla E2E jest w kontrakcie i odwrotnie (#277).

    Wyjątkiem jest /run/wlb/e2e — katalog markerów tworzony w runtime, nie zawartość obrazu.
    """
    tasks = yaml.safe_load(ROLE_TASKS.read_text(encoding="utf-8"))
    assert isinstance(tasks, list), f"{ROLE_TASKS}: oczekiwano listy zadań"

    installed: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if "wlb_enable_e2e_target" not in str(task.get("when", "")):
            continue
        for module in ("ansible.builtin.copy", "ansible.builtin.file"):
            args = task.get(module)
            if not isinstance(args, dict):
                continue
            dest = args.get("dest") or args.get("path")
            if not isinstance(dest, str) or not dest.startswith("/"):
                continue
            if dest.startswith("/run/"):
                continue
            if "{{" in dest:
                dest = str(Path(dest).parent)
            installed.add(dest.rstrip("/"))

    assert installed == set(contract_paths())


def test_acceptance_uses_shared_contract_and_helper() -> None:
    """Fragment akceptacji nie powtarza listy ścieżek — woła wspólną funkcję (#277)."""
    text = PULPIT_ACCEPTANCE.read_text(encoding="utf-8")
    assert "assert_no_e2e_fixture" in text
    for path in contract_paths():
        assert f"test ! -e {path}" not in text, (
            f"{PULPIT_ACCEPTANCE}: zduplikowana asercja dla {path}; użyj assert_no_e2e_fixture"
        )


def test_helper_passes_when_paths_absent(tmp_path: Path) -> None:
    """Realna funkcja akceptacyjna przechodzi, gdy żadna ścieżka nie istnieje (#277)."""
    done = run_helper(tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"PASS={len(contract_paths())} FAIL=0" in done.stdout


@pytest.mark.parametrize("target_path", contract_paths())
def test_helper_fails_when_any_path_exists(tmp_path: Path, target_path: str) -> None:
    """Realna funkcja akceptacyjna wykrywa każdą pojedynczą ścieżkę fixture (#277)."""
    full_path = tmp_path / target_path.lstrip("/")
    full_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.endswith("/"):
        full_path.mkdir(parents=True, exist_ok=True)
    else:
        full_path.write_text("nielegalny artefakt", encoding="utf-8")

    done = run_helper(tmp_path)
    assert done.returncode != 0, done.stdout + done.stderr
    assert "FAIL=1" in done.stdout


def test_helper_rejects_empty_contract(tmp_path: Path) -> None:
    """Pusty kontrakt to błąd, nie ciche „wszystko czyste” (#277)."""
    done = run_helper(tmp_path, paths=())
    assert done.returncode != 0
    assert "pusty kontrakt" in done.stderr

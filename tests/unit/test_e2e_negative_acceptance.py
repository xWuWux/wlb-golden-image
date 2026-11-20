"""Testy jednostkowe negatywnych asercji akceptacyjnych dla targetu E2E (#277, S2).

Weryfikuje:
1. Obecność 4 asercji `test ! -e` w `tests/acceptance.d/40-pulpit.sh` dla flavoru nie-E2E.
2. Poprawne zaliczenie testu, gdy żadna ze ścieżek nie istnieje w środowisku nie-E2E.
3. Wykrycie naruszenia (FAIL), gdy jakakolwiek ze ścieżek pojawi się w środowisku nie-E2E.
4. Brak uruchamiania negatywnych asercji na flavorach E2E (gdzie fixture jest wymagany).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PULPIT_ACCEPTANCE = REPO_ROOT / "tests/acceptance.d/40-pulpit.sh"

CONTRACT_PATHS = (
    "/opt/wlb/e2e",
    "/etc/xdg/autostart/wlb-e2e-target.desktop",
    "/usr/share/applications/wlb-e2e-mouse.desktop",
    "/etc/tmpfiles.d/wlb-e2e.conf",
)


def test_acceptance_40_pulpit_defines_all_four_negative_assertions() -> None:
    """Weryfikuje, że 40-pulpit.sh zawiera bramkujące asercje test ! -e dla wszystkich 4 ścieżek (#277)."""
    text = PULPIT_ACCEPTANCE.read_text(encoding="utf-8")
    assert "else" in text, f"{PULPIT_ACCEPTANCE}: brak gałęzi else dla flavoru nie-E2E"

    _, non_e2e_part = text.split("else", 1)
    for path in CONTRACT_PATHS:
        pattern = rf'expect_ok\s+"[^"]*"\s+test\s+!\s+-e\s+{re.escape(path)}'
        assert re.search(pattern, non_e2e_part), (
            f"Brak asercji negatywnej `test ! -e {path}` w sekcji nie-E2E pliku {PULPIT_ACCEPTANCE}"
        )


def test_acceptance_negative_assertions_pass_when_paths_absent(tmp_path: Path) -> None:
    """Weryfikuje, że w środowisku bez plików targetu E2E wszystkie 4 asercje przechodzą (#277)."""
    harness = """
PASS=0; FAIL=0
expect_ok() {
  local d=$1; shift
  if "$@" >/dev/null 2>&1; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); fi
}
"""
    checks = "\n".join(f'expect_ok "brak {p}" test ! -e "{tmp_path}{p}"' for p in CONTRACT_PATHS)
    script = f'{harness}\n{checks}\necho "PASS=$PASS FAIL=$FAIL"\n[ $FAIL -eq 0 ]'

    proc = subprocess.run(  # noqa: S603 # nosec B603
        ["/bin/bash", "-c", script], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0
    assert "PASS=4 FAIL=0" in proc.stdout


@pytest.mark.parametrize("target_path", CONTRACT_PATHS)
def test_acceptance_negative_assertions_fail_when_any_path_exists(tmp_path: Path, target_path: str) -> None:
    """Test negatywny bramki: utworzenie którejkolwiek ze ścieżek powoduje FAIL asercji (#277)."""
    full_path = tmp_path / target_path.lstrip("/")
    if target_path.endswith("/"):
        full_path.mkdir(parents=True, exist_ok=True)
    else:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text("nielegalny artefakt")

    harness = """
PASS=0; FAIL=0
expect_ok() {
  local d=$1; shift
  if "$@" >/dev/null 2>&1; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); fi
}
"""
    checks = "\n".join(f'expect_ok "brak {p}" test ! -e "{tmp_path}{p}"' for p in CONTRACT_PATHS)
    script = f'{harness}\n{checks}\necho "PASS=$PASS FAIL=$FAIL"\n[ $FAIL -eq 0 ]'

    proc = subprocess.run(  # noqa: S603 # nosec B603
        ["/bin/bash", "-c", script], capture_output=True, text=True, check=False
    )
    assert proc.returncode != 0
    assert "FAIL=1" in proc.stdout


def test_acceptance_negative_assertions_not_in_e2e_branch() -> None:
    """Weryfikuje, że gałąź dla flavorów E2E (z pulpitem) NIE zawiera negatywnych asercji (#277)."""
    text = PULPIT_ACCEPTANCE.read_text(encoding="utf-8")
    e2e_part, _ = text.split("else", 1)
    for path in CONTRACT_PATHS:
        assert f"test ! -e {path}" not in e2e_part, (
            f"BŁĄD: asercja `test ! -e {path}` znalazła się w gałęzi E2E — spowodowałaby false-FAIL!"
        )

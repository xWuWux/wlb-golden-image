"""Smoke-test bramki E2E na prawdziwym qcow2 (libguestfs), opt-in.

Mocki nie wykryją złego argv virt-ls (#360), dlatego ten test buduje mały obraz
przez virt-make-fs i uruchamia produkcyjną ścieżkę bramki. Wymaga libguestfs-tools
i działającego appliance; w CI jednostkowym tych narzędzi nie ma, więc test jest
opcjonalny:

  WLB_E2E_GATE_SMOKE=1 pytest -q tests/unit/test_e2e_release_gate_smoke.py

Na WSL, gdzie /boot/vmlinuz-* jest nieczytelny dla użytkownika, supermin można
nakierować na rozpakowany kernel pakietu (SUPERMIN_KERNEL, SUPERMIN_KERNEL_VERSION,
SUPERMIN_MODULES) — bez tego libguestfs nie zbuduje appliance.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest
from conftest import REPO_ROOT

pytestmark = pytest.mark.skipif(
    os.environ.get("WLB_E2E_GATE_SMOKE") != "1",
    reason="smoke libguestfs: ustaw WLB_E2E_GATE_SMOKE=1",
)

GATE = REPO_ROOT / "ci/e2e_release_gate.py"
E2E_FILES = (
    "opt/wlb/e2e/target.json",
    "etc/xdg/autostart/wlb-e2e-target.desktop",
    "usr/share/applications/wlb-e2e-mouse.desktop",
    "etc/tmpfiles.d/wlb-e2e.conf",
)
# Bramka raportuje ścieżki kontraktu: katalog /opt/wlb/e2e, nie plik w nim.
E2E_REPORTED = (
    "/opt/wlb/e2e",
    "/etc/xdg/autostart/wlb-e2e-target.desktop",
    "/usr/share/applications/wlb-e2e-mouse.desktop",
    "/etc/tmpfiles.d/wlb-e2e.conf",
)
BASE_DIRS = (
    "etc",
    "usr/lib",
    "usr/bin",
    "usr/sbin",
    "usr/share/applications",
    "bin",
    "sbin",
    "lib",
    "lib64",
    "var/lib",
    "tmp",
    "root",
    "home",
    "run",
    "proc",
    "sys",
    "dev",
    "boot",
    "opt/wlb/bin",
)


def build_image(tmp_path, name, *, e2e):
    """Buduje minimalny obraz, który libguestfs rozpoznaje jako system (inspekcja)."""
    for tool in ("virt-make-fs", "virt-ls"):
        if shutil.which(tool) is None:
            pytest.skip(f"brak {tool} (libguestfs-tools)")

    root = tmp_path / f"{name}-root"
    for rel in BASE_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)
    release = 'ID=ubuntu\nVERSION_ID="24.04"\nVERSION_CODENAME=noble\n'
    (root / "etc/os-release").write_text(release, encoding="utf-8")
    (root / "usr/lib/os-release").write_text(release, encoding="utf-8")
    (root / "etc/fstab").write_text("proc /proc proc defaults 0 0\n", encoding="utf-8")
    (root / "etc/passwd").write_text("root:x:0:0:root:/root:/bin/sh\n", encoding="utf-8")
    (root / "etc/group").write_text("root:x:0:\n", encoding="utf-8")
    (root / "opt/wlb/bin/wlb-health").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    if e2e:
        for rel in E2E_FILES:
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture\n", encoding="utf-8")

    image = tmp_path / f"{name}.qcow2"
    subprocess.run(  # noqa: S603 - stała lista argumentów, ścieżki z tmp_path
        ["virt-make-fs", "--format=qcow2", "--type=ext4", str(root), str(image)],  # noqa: S607 - narzędzie z PATH testu
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return image


def run_gate(image):
    return subprocess.run(  # noqa: S603 - bramka z repozytorium, obraz z tmp_path
        [sys.executable, str(GATE), "--image", str(image)],
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_smoke_obraz_bez_e2e_przechodzi(tmp_path):
    image = build_image(tmp_path, "clean", e2e=False)
    done = run_gate(image)
    assert done.returncode == 0, done.stderr
    assert "czysto" in done.stdout


def test_smoke_obraz_z_e2e_jest_odrzucany(tmp_path):
    image = build_image(tmp_path, "e2e", e2e=True)
    done = run_gate(image)
    assert done.returncode == 3, done.stderr
    for path in E2E_REPORTED:
        assert path in done.stderr

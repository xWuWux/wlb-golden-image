"""Przekroczenie budżetu rozmiaru (#108) musi dotrzeć przez run_check aż do finish.

Analogicznie do test_radiologia_size_gate: histologia_flavor woła ci/image-size-report.sh PRZED
akceptacją, więc jego błąd (np. próg WLB_IMAGE_SIZE_MAX_GIB) musi zatrzymać flavor, a nie zostać
połknięty przed uruchomieniem akceptacji.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_report_failure_stops_acceptance(tmp_path):
    source = (ROOT / "ci/integration.sh").read_text()
    function = source.split("histologia_flavor() {", 1)[1].split("\n}", 1)[0]
    reporter = tmp_path / "ci/image-size-report.sh"
    reporter.parent.mkdir()
    reporter.write_text("#!/bin/sh\ntouch measured\nexit 1\n")
    reporter.chmod(0o755)
    script = (
        'source ci/common.sh\ncd "$TESTDIR"\n'
        "packer() { return 0; }\nacceptance() { touch accepted; }\n"
        "histologia_flavor() {" + function + "\n}\nrun_check test histologia_flavor\nfinish"
    )
    env = dict.fromkeys(
        [
            "IMAGE_VERSION",
            "IMAGE_DATE",
            "IMAGE",
            "LOGS",
            "BUILD_CPUS",
            "BUILD_MEMORY",
            "GIT_COMMIT",
            "GIT_DESCRIBE",
            "GIT_DIRTY",
            "BUILD_RUN",
        ],
        "fixture",
    )
    result = subprocess.run(  # noqa: S603  # lokalna funkcja z repozytorium i atrapy testowe
        ["/bin/bash", "-c", script],
        cwd=ROOT,
        env={**os.environ, **env, "TESTDIR": str(tmp_path), "WLB_BUILD_HISTOLOGIA": "1"},
        check=False,
    )
    assert (tmp_path / "measured").exists()
    assert result.returncode == 1
    assert not (tmp_path / "accepted").exists()

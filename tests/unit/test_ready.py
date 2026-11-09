"""Regression cases for the status check required by the default-branch ruleset."""

import json
import os
import subprocess
import unittest
from pathlib import Path

READY = Path(__file__).resolve().parents[2] / "ci" / "ready.sh"


class RequiredCheckTests(unittest.TestCase):
    def test_required_check_outcomes(self) -> None:
        cases = (
            ("docs", False, "integration", "skipped", 0),
            ("image", True, "integration", "success", 0),
            ("image skipped", True, "integration", "skipped", 1),
            ("image missing", True, "integration", None, 1),
            ("image cancelled", True, "integration", "cancelled", 1),
            ("security failed", False, "security", "failure", 1),
            ("contracts skipped", False, "observability", "skipped", 1),
            ("unit missing", False, "unit", None, 1),
            ("benchmark failed", False, "perf", "failure", 1),
            ("openstack cancelled", False, "ephemeral", "cancelled", 1),
        )
        for name, image, job, result, expected in cases:
            with self.subTest(name=name):
                needs = {
                    key: {"result": "success"}
                    for key in ("lint", "build-check", "security", "observability", "unit")
                }
                needs["lint"]["outputs"] = {"image": str(image).lower()}
                needs.update({key: {"result": "skipped"} for key in ("integration", "perf", "ephemeral")})
                if result is None:
                    del needs[job]
                else:
                    needs[job]["result"] = result

                env = {**os.environ, "NEEDS": json.dumps(needs)}
                env.pop("GITHUB_STEP_SUMMARY", None)
                process = subprocess.run(  # noqa: S603
                    ["/bin/bash", str(READY)],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(process.returncode, expected, process.stdout + process.stderr)
                self.assertEqual("**blokuje**" in process.stdout, expected == 1)

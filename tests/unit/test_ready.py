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
            ("mutation skipped", False, "mutation", "skipped", 1),
            ("benchmark failed", False, "perf", "failure", 1),
            ("openstack cancelled", False, "ephemeral", "cancelled", 1),
            ("mutation failed", False, "mutation", "failure", 1),
            ("mutation skipped", False, "mutation", "skipped", 1),
        )
        self._run_cases(cases)

    # --- publikacja Code scanning wymagana, gdy etap 3 wykonał skan (#257) ---
    def test_code_scanning_publication_outcomes_257(self) -> None:
        cases = (
            ("publication failed", False, "security-report", "failure", 1),
            ("publication missing", False, "security-report", None, 1),
            ("publication skipped after scan", False, "security-report", "skipped", 1),
            ("publication cancelled", False, "security-report", "cancelled", 1),
        )
        self._run_cases(cases)
        # findings w etapie 3: blokuje security, publikacja nadal ma przejść (raport, nie druga bramka)
        self._run_cases((("findings published", False, "security", "failure", 1),))
        # etap 3 pominięty (np. czerwony etap 2): brak publikacji nie dokłada drugiej blokady
        out = self._run({"security": "skipped", "security-report": "skipped"})
        self.assertIn("3r. Publikacja Code scanning | ⏭️ skipped |", out.stdout)
        self.assertNotIn("3r. Publikacja Code scanning | ⏭️ skipped — **blokuje**", out.stdout)

    def _run(self, overrides: dict[str, str | None], image: bool = False) -> subprocess.CompletedProcess[str]:
        needs = {
            key: {"result": "success"}
            for key in ("lint", "build-check", "security", "security-report", "observability", "unit", "mutation")
        }
        needs["lint"]["outputs"] = {"image": str(image).lower()}
        needs.update({key: {"result": "skipped"} for key in ("integration", "perf", "ephemeral")})
        for job, result in overrides.items():
            if result is None:
                del needs[job]
            else:
                needs[job]["result"] = result
        env = {**os.environ, "NEEDS": json.dumps(needs)}
        env.pop("GITHUB_STEP_SUMMARY", None)
        return subprocess.run(  # noqa: S603
            ["/bin/bash", str(READY)],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def _run_cases(self, cases: tuple[tuple[str, bool, str, str | None, int], ...]) -> None:
        for name, image, job, result, expected in cases:
            with self.subTest(name=name):
                process = self._run({job: result}, image=image)
                self.assertEqual(process.returncode, expected, process.stdout + process.stderr)
                self.assertEqual("**blokuje**" in process.stdout, expected == 1)

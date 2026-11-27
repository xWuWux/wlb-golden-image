"""Regression tests for complete samples and the actual stage-6a entrypoint (#10).

No VM, network, root, or application processes are started. The emitter is loaded
up to the first provisioning command; the host entrypoint uses fixture helpers.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")


@unittest.skipUnless(BASH, "bash is required")
class PerfEmitterTests(unittest.TestCase):
    def emit(self, arguments: str) -> subprocess.CompletedProcess[str]:
        source = (ROOT / "tests/perf-remote.sh").read_text()
        prefix, separator, _ = source.partition("password=$(")
        self.assertTrue(separator, "load functions without running provisioning")
        # Median itself is covered by perf-helpers.bats. This stub isolates the
        # cardinality/type contract and must never be called for an invalid set.
        script = prefix + '\nmedian() { echo "$1"; }\n'
        script += f'emit probe_ms ms {arguments}\nexit "$MEASUREMENT_FAILED"\n'
        # Only the repository's fixed function definitions and literal test inputs run.
        return subprocess.run([BASH], input=script, text=True, capture_output=True, check=False)  # noqa: S603

    def test_complete_series_emits_value_and_samples(self):
        result = self.emit("3 10 20 30")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("probe_ms 10 ms\n", result.stdout)
        self.assertIn("SAMPLE probe_ms 10 20 30", result.stdout)

    def test_missing_or_excess_samples_never_emit_a_canonical_value(self):
        for arguments in ("3", "3 10", "3 10 20", "1 10 20"):
            with self.subTest(arguments=arguments):
                result = self.emit(arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ERROR probe_ms expected=", result.stdout)
                self.assertNotRegex(result.stdout, r"(?m)^probe_ms ")

    def test_invalid_samples_fail_without_running_median(self):
        for value in ('""', "nan", "inf", "-1", "1.2"):
            with self.subTest(value=value):
                result = self.emit(f"1 {value}")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid_sample", result.stdout)
                self.assertNotRegex(result.stdout, r"(?m)^probe_ms ")


@unittest.skipUnless(BASH, "bash is required")
class PerfEntrypointTests(unittest.TestCase):
    def stage(
        self, *, enforce: int, remote_status: int = 0, missing: bool = False, slow: bool = False
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in ("ci", "tests/lib"):
                (root / path).mkdir(parents=True)
            shutil.copyfile(ROOT / "ci/perf.sh", root / "ci/perf.sh")
            (root / "image.qcow2").touch()
            (root / "ci/perf-budget.env").write_text("boot_to_ready_s=600\nprobe_ms=100\n")
            (root / "ci/common.sh").write_text("set -euo pipefail\nsummary() { cat; }\n")
            (root / "tests/lib/local-common.sh").write_text(
                "SSH=(true)\n"
                "perf_vm_resources() { export VM_CPUS=1 VM_MEMORY=1024; }\n"
                'remote_run() { cat remote.fixture; return "$REMOTE_STATUS"; }\n'
            )
            for name in ("run-local.sh", "stop-local.sh"):
                path = root / "tests" / name
                path.write_text("#!/usr/bin/env bash\nexit 0\n")
                path.chmod(0o755)
            (root / "remote.fixture").write_text("" if missing else f"probe_ms {200 if slow else 50} ms\n")
            env = os.environ.copy()
            env.update(
                PERF_ENFORCE=str(enforce),
                PERF_REPEAT="1",
                PERF_BOOT_REPEAT="1",
                REMOTE_STATUS=str(remote_status),
            )
            # The real entrypoint runs only fixture VM/SSH helpers in a temporary directory.
            result = subprocess.run(  # noqa: S603
                [BASH, "ci/perf.sh", "image.qcow2"],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            report = root / "build/perf/summary.md"
            self.assertTrue(report.is_file(), result.stderr)
            return result, report.read_text()

    def test_success_passes_in_both_modes(self):
        for enforce in (0, 1):
            with self.subTest(enforce=enforce):
                result, _ = self.stage(enforce=enforce)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_only_budget_exceedance_can_be_report_only(self):
        for enforce in (0, 1):
            with self.subTest(enforce=enforce):
                result, report = self.stage(enforce=enforce, slow=True)
                self.assertEqual(result.returncode, enforce, result.stderr)
                self.assertIn("PRZEKROCZONY", report)

    def test_missing_measurement_fails_even_without_enforcement(self):
        for enforce in (0, 1):
            with self.subTest(enforce=enforce):
                result, report = self.stage(enforce=enforce, missing=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("BŁĄD POMIARU", report)

    def test_remote_error_fails_even_if_all_metrics_were_printed(self):
        for code in (1, 124, 137, 255):
            for enforce in (0, 1):
                with self.subTest(code=code, enforce=enforce):
                    result, report = self.stage(enforce=enforce, remote_status=code)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f"kodem {code}", report)


if __name__ == "__main__":
    unittest.main()

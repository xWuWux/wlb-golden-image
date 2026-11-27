"""Regression tests for complete samples and the actual stage-6a entrypoint (#10).

No VM, network, root, or application processes are started. The remote emitter is
loaded through its explicit test hook; the host entrypoint runs with fixture helpers
and checks the produced report, not the script's internal text layout.
"""

import hashlib
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
        # Median is covered by perf-helpers.bats and remote-common.sh; this stub isolates
        # the cardinality/type contract and must never be called for an invalid set.
        script = (
            'median() { echo "$1"; }\n'
            'source "$PERF_REMOTE_SOURCE"\n'
            f"emit probe_ms ms {arguments}\n"
            'exit "$MEASUREMENT_FAILED"\n'
        )
        env = os.environ.copy()
        env.update(
            PERF_REMOTE_FUNCTIONS_ONLY="1",
            PERF_REMOTE_SOURCE=str(ROOT / "tests/perf-remote.sh"),
        )
        # Only the repository's fixed function definitions and literal test inputs run.
        return subprocess.run(  # noqa: S603
            [BASH, "-c", script], env=env, text=True, capture_output=True, check=False
        )

    def test_complete_series_emits_value_and_samples(self):
        result = self.emit("3 10 20 30")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("probe_ms 10 ms\n", result.stdout)
        self.assertIn("SAMPLE probe_ms 10 20 30", result.stdout)

    def test_missing_or_excess_samples_never_emit_sample_or_value(self):
        for arguments in ("3", "3 10", "3 10 20", "1 10 20"):
            with self.subTest(arguments=arguments):
                result = self.emit(arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ERROR probe_ms expected=", result.stdout)
                self.assertNotIn("SAMPLE ", result.stdout)
                self.assertNotRegex(result.stdout, r"(?m)^probe_ms ")

    def test_invalid_samples_fail_without_running_median_or_emitting_sample(self):
        for value in ('""', "nan", "inf", "-1", "1.2"):
            with self.subTest(value=value):
                result = self.emit(f"1 {value}")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid_sample", result.stdout)
                self.assertNotIn("SAMPLE ", result.stdout)
                self.assertNotRegex(result.stdout, r"(?m)^probe_ms ")

    def test_invalid_expected_count_is_rejected(self):
        for expected in ("0", "-1", "abc"):
            with self.subTest(expected=expected):
                result = self.emit(f"{expected} 10")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid_expected", result.stdout)
                self.assertNotIn("SAMPLE ", result.stdout)


@unittest.skipUnless(BASH, "bash is required")
class PerfEntrypointTests(unittest.TestCase):
    def stage(
        self,
        *,
        enforce: str = "1",
        remote_status: int = 0,
        fixture: str | None = None,
        verify: str = "off",
        argument: bool = True,
        candidates: int = 0,
        extra_env: dict[str, str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], str, str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in ("ci", "tests/lib", "bin"):
                (root / path).mkdir(parents=True)
            shutil.copyfile(ROOT / "ci/perf.sh", root / "ci/perf.sh")
            shutil.copyfile(ROOT / "ci/perf_summary.py", root / "ci/perf_summary.py")

            image = root / "image.qcow2"
            image.write_bytes(b"qcow2 fixture\n")
            (root / "ci/perf-budget.env").write_text("boot_to_ready_s=600\nhub_login_ms=100\n")
            (root / "ci/common.sh").write_text("set -euo pipefail\nsummary() { cat; }\n")
            (root / "tests/lib/local-common.sh").write_text(
                "SSH=(true)\n"
                "perf_vm_resources() { export VM_CPUS=1 VM_MEMORY=1024; }\n"
                'remote_run() { cat remote.fixture; return "$REMOTE_STATUS"; }\n'
            )
            # Boot must take a measurable number of whole seconds; zero is a measurement error.
            for name, body in (
                ("run-local.sh", "#!/usr/bin/env bash\nsleep 1\n"),
                ("stop-local.sh", "#!/usr/bin/env bash\nexit 0\n"),
            ):
                path = root / "tests" / name
                path.write_text(body)
                path.chmod(0o755)
            qemu_img = root / "bin/qemu-img"
            qemu_img.write_text("#!/usr/bin/env bash\nexit 0\n")
            qemu_img.chmod(0o755)

            if fixture is None:
                fixture = "SAMPLE hub_login_ms 40 45 50\nhub_login_ms 45 ms\n"
            (root / "remote.fixture").write_text(fixture)

            for index in range(candidates):
                flavor = root / "output" / f"flavor-{index}"
                flavor.mkdir(parents=True)
                (flavor / f"wlb-general-{index}.qcow2").write_bytes(b"candidate\n")

            checksum = hashlib.sha256(image.read_bytes()).hexdigest()
            if verify == "valid":
                # Packer potrafi zapisać sumę jako "sha256:<hash>"; parser ma to akceptować.
                (root / "image.qcow2.sha256").write_text(f"sha256:{checksum}\n")
            elif verify == "wrong":
                (root / "image.qcow2.sha256").write_text(f"{'0' * 64}  image.qcow2\n")

            env = os.environ.copy()
            env["PATH"] = f"{root / 'bin'}{os.pathsep}{env.get('PATH', '')}"
            env.update(
                PERF_ENFORCE=enforce,
                PERF_REPEAT="1",
                PERF_BOOT_REPEAT="1",
                PERF_VERIFY_IMAGE="0" if verify == "off" else "1",
                REMOTE_STATUS=str(remote_status),
            )
            if extra_env:
                env.update(extra_env)
            command = [BASH, "ci/perf.sh"]
            if argument:
                command.append("image.qcow2")
            # The real entrypoint runs only fixture VM/SSH helpers in a temporary directory.
            result = subprocess.run(  # noqa: S603
                command,
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            report = root / "build/perf/summary.md"
            self.assertTrue(report.is_file(), result.stderr)
            env_file = root / "build/perf/env.txt"
            return result, report.read_text(), env_file.read_text() if env_file.is_file() else ""

    def test_success_passes_in_both_modes(self):
        for enforce in ("0", "1", "true", "yes", "on"):
            with self.subTest(enforce=enforce):
                result, report, _ = self.stage(enforce=enforce)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("**Wynik:** PASS", report)

    def test_only_budget_exceedance_can_be_report_only(self):
        slow = "SAMPLE hub_login_ms 200 200 200\nhub_login_ms 200 ms\n"
        for enforce, expected in (("0", 0), ("1", 1), ("false", 0), ("on", 1)):
            with self.subTest(enforce=enforce):
                result, report, _ = self.stage(enforce=enforce, fixture=slow)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertIn("PRZEKROCZONY", report)

    def test_missing_measurement_fails_even_without_enforcement(self):
        for enforce in ("0", "1"):
            with self.subTest(enforce=enforce):
                result, report, _ = self.stage(enforce=enforce, fixture="")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("BŁĄD POMIARU", report)

    def test_remote_error_line_fails_even_if_all_metrics_were_printed(self):
        fixture = (
            "SAMPLE hub_login_ms 40 45 50\n"
            "hub_login_ms 45 ms\n"
            "ERROR hub_login_ms expected=5 observed=3 reason=incomplete\n"
        )
        result, report, _ = self.stage(fixture=fixture)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Błędy pomiaru", report)

    def test_remote_exit_status_fails_even_if_all_metrics_were_printed(self):
        for code in (1, 124, 137, 255):
            for enforce in ("0", "1"):
                with self.subTest(code=code, enforce=enforce):
                    result, report, _ = self.stage(enforce=enforce, remote_status=code)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f"kodem {code}", report)

    def test_invalid_boolean_or_repeat_is_a_configuration_error(self):
        for env in (
            {"PERF_ENFORCE": "maybe"},
            {"PERF_VERIFY_IMAGE": "perhaps"},
            {"PERF_REPEAT": "0"},
            {"PERF_REPEAT": "abc"},
            {"PERF_BOOT_REPEAT": "0"},
            {"PERF_BOOT_REPEAT": "6"},
        ):
            with self.subTest(env=env):
                result, report, _ = self.stage(extra_env=env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("BŁĄD POMIARU/KONFIGURACJI", report)

    def test_value_must_be_median_of_samples(self):
        fixture = "SAMPLE hub_login_ms 40 45 50\nhub_login_ms 99 ms\n"
        result, report, _ = self.stage(fixture=fixture)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nie jest medianą", report)

    def test_metric_without_budget_is_rejected(self):
        fixture = "SAMPLE unknown_ms 1\nunknown_ms 1 ms\n"
        result, report, _ = self.stage(fixture=fixture)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bez progu w budżecie", report)

    def test_checksum_is_verified_and_recorded(self):
        result, report, env_file = self.stage(verify="valid")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("**Wynik:** PASS", report)
        self.assertRegex(env_file, r"image_sha256 [0-9a-f]{64}")

        for mode in ("wrong", "missing"):
            with self.subTest(mode=mode):
                result, report, _ = self.stage(verify=mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("BŁĄD POMIARU/KONFIGURACJI", report)

    def test_image_selection_requires_exactly_one_candidate(self):
        result, report, _ = self.stage(argument=False, candidates=2)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("niejednoznaczny obraz", report)

        result, report, _ = self.stage(argument=False, candidates=0)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("brak obrazu", report)

        result, report, _ = self.stage(argument=False, candidates=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("**Wynik:** PASS", report)


if __name__ == "__main__":
    unittest.main()

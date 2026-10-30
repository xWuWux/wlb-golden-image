"""Exercise launcher acceptance with isolated executables, without FSL or a GUI."""

import subprocess
import tempfile
import unittest
from pathlib import Path


class NeuroLauncherAcceptanceTests(unittest.TestCase):
    def run_checks(self, wrapper: str, overrides: dict[str, str] | None = None, *, direct: bool = False) -> int:
        """Run the real acceptance commands against temporary launcher fixtures."""
        source = (Path(__file__).resolve().parents[1] / "acceptance.d/70-radiologia.sh").read_text()
        # Only the launcher contract block; GUI runtime needs a real image.
        block = source.split("  # Kafelek musi", 1)[1].split("  # desktop-file-validate", 1)[0]
        block = "  # Kafelek musi" + block
        if direct:
            block = source.split('  expect_ok "FSLeyes uruchamia się', 1)[1].split("  # 3DSlicer:", 1)[0]
            block = '  expect_ok "FSLeyes uruchamia się' + block
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apps = root / "applications"
            binaries = root / "bin"
            apps.mkdir()
            binaries.mkdir()
            profile = root / "fsl.sh"
            profile.write_text(f'export PATH="{binaries}:$PATH"\n')
            block = block.replace("/etc/profile.d/fsl.sh", str(profile))
            entries = {
                "wlb-slicer": "Exec=/usr/local/bin/Slicer %F",
                "wlb-fsleyes": "Exec=wlb-fsleyes %F",
                "wlb-fsl": "Exec=wlb-fsl",
            }
            entries.update(overrides or {})
            for name, entry in entries.items():
                (apps / (name + ".desktop")).write_text(entry.replace("/usr/local/bin", str(binaries)) + "\n")
            for name, body in (("wlb-fsleyes", wrapper), ("fsleyes", wrapper), ("wlb-fsl", "exit 0")):
                executable = binaries / name
                executable.write_text("#!/bin/sh\n" + body + "\n")
                executable.chmod(0o755)
            block = block.replace("/usr/share/applications", str(apps)).replace("/usr/local/bin", str(binaries))
            # Keep the timeout path real but make the hanging-fixture test fast.
            block = block.replace("--kill-after=5s 60s", "--kill-after=0.1s 0.2s")
            harness = 'expect_ok() { shift; "$@" || exit 1; }\n'
            # Only repository-controlled code and fixtures are executed.
            return subprocess.run(  # noqa: S603
                ["/bin/bash", "-c", harness + block],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            ).returncode

    def test_success_requires_actual_wrapper_with_clean_environment(self) -> None:
        self.assertEqual(
            self.run_checks(
                '[ -z "${FSLDIR+x}" ] || exit 9\n'
                '[ "$PATH" = /usr/bin:/bin ] || exit 9\n'
                '[ "$#" = 1 ] && [ "$1" = --version ] || exit 9\n'
                'printf "FSLeyes version 1.18.0\\n"'
            ),
            0,
        )

    def test_broken_wrapper_fails(self) -> None:
        self.assertNotEqual(self.run_checks("exit 17"), 0)

    def test_version_marker_does_not_hide_nonzero_exit(self) -> None:
        self.assertNotEqual(self.run_checks('echo "FSLeyes version 1.18.0"; exit 17'), 0)

    def test_missing_version_marker_fails(self) -> None:
        self.assertNotEqual(self.run_checks("exit 0"), 0)

    def test_hung_wrapper_fails(self) -> None:
        self.assertNotEqual(self.run_checks("sleep 10"), 0)

    def test_wrong_exec_fails_for_each_launcher(self) -> None:
        for app, entry in (
            ("wlb-fsleyes", "Exec=wlb-fsleyes-broken %F"),
            ("wlb-slicer", "Exec=/missing/Slicer %F"),
            ("wlb-fsl", "Exec=missing-fsl"),
        ):
            with self.subTest(app=app):
                self.assertNotEqual(self.run_checks('echo "FSLeyes version 1.18.0"', {app: entry}), 0)

    def test_direct_smoke_requires_marker_and_successful_exit(self) -> None:
        for body, expected in (
            ('echo "FSLeyes version 1.18.0"', 0),
            ('echo "FSLeyes version 1.18.0"; exit 17', 1),
            ('echo "FSLeyes version 1.18.0"; sleep 10', 1),
            ("exit 0", 1),
        ):
            with self.subTest(body=body):
                result = self.run_checks(body, direct=True)
                self.assertEqual(result == 0, expected == 0)

"""Testy walidatora wyników etapu 6a (ci/perf_summary.py, #10)."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ci import perf_summary as ps  # noqa: E402


class ParseBoolTests(unittest.TestCase):
    def test_accepts_supported_spellings(self):
        for raw in ("1", "true", "TRUE", "yes", "on"):
            with self.subTest(raw=raw):
                self.assertTrue(ps.parse_bool(raw))
        for raw in ("0", "false", "FALSE", "no", "off"):
            with self.subTest(raw=raw):
                self.assertFalse(ps.parse_bool(raw))

    def test_rejects_unknown_value(self):
        for raw in ("", "maybe", "2"):
            with self.subTest(raw=raw), self.assertRaises(ps.PerfError):
                ps.parse_bool(raw, "PERF_ENFORCE")


class ParseStatusTests(unittest.TestCase):
    def test_accepts_range(self):
        self.assertEqual(ps.parse_status("0"), 0)
        self.assertEqual(ps.parse_status("255"), 255)

    def test_rejects_invalid_status(self):
        for raw in ("-1", "256", "x", ""):
            with self.subTest(raw=raw), self.assertRaises(ps.PerfError):
                ps.parse_status(raw)


class BudgetTests(unittest.TestCase):
    def parse(self, text: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "budget.env"
            path.write_text(text)
            return ps.parse_budget(path)

    def test_parses_comments_and_values(self):
        budget = self.parse("# komentarz\n\nhub_login_ms=100 # inline\nworkspace_read_mbps=2000\n")
        self.assertEqual(budget, {"hub_login_ms": 100.0, "workspace_read_mbps": 2000.0})

    def test_rejects_malformed_or_unknown_budget(self):
        cases = (
            "hub_login_ms",
            "Bad_ms=1",
            "hub_login_ms=1\nhub_login_ms=2",
            "unknown_ms=1",
            "hub_login_ms=abc",
            "hub_login_ms=0",
            "",
        )
        for text in cases:
            with self.subTest(text=text), self.assertRaises(ps.PerfError):
                self.parse(text)


class ResultsTests(unittest.TestCase):
    def parse(self, text: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.txt"
            path.write_text(text)
            return ps.parse_results(path)

    def test_parses_metrics_and_ignores_diagnostics(self):
        measured, errors = self.parse(
            "DETAIL hub_login attempt=1 status=500\n"
            "RAW hub_login_ms 10 20\n"
            "hub_login_ms 15 ms\n"
            "ERROR hub_login_ms expected=5 observed=3 reason=incomplete\n"
        )
        self.assertEqual(measured, {"hub_login_ms": (15.0, "ms")})
        self.assertEqual(len(errors), 1)

    def test_rejects_malformed_lines(self):
        cases = (
            "ERROR\n",
            "ERROR bad-name x\n",
            "hub_login_ms 10\n",
            "hub_login_ms 10 ms extra\n",
            "hub_login_ms abc ms\n",
            "hub_login_ms 10 MB/s\n",
            "hub_login_ms 10 ms\nhub_login_ms 20 ms\n",
        )
        for text in cases:
            with self.subTest(text=text), self.assertRaises(ps.PerfError):
                self.parse(text)


class SamplesTests(unittest.TestCase):
    def parse(self, text: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "samples.txt"
            path.write_text(text)
            return ps.parse_samples(path)

    def test_missing_file_is_empty(self):
        self.assertEqual(ps.parse_samples(Path("/nonexistent/samples.txt")), {})

    def test_parses_complete_series(self):
        self.assertEqual(self.parse("SAMPLE hub_login_ms 1 2 3\n"), {"hub_login_ms": (1, 2, 3)})

    def test_rejects_malformed_series(self):
        cases = (
            "hub_login_ms 1\n",
            "SAMPLE bad-name 1\n",
            "SAMPLE hub_login_ms\n",
            "SAMPLE hub_login_ms 1 x\n",
            "SAMPLE hub_login_ms 1\nSAMPLE hub_login_ms 2\n",
        )
        for text in cases:
            with self.subTest(text=text), self.assertRaises(ps.PerfError):
                self.parse(text)


class RenderTests(unittest.TestCase):
    def render(self, **overrides):
        arguments = {
            "budget": {"hub_login_ms": 100.0},
            "measured": {"hub_login_ms": (50.0, "ms")},
            "samples": {"hub_login_ms": (40, 45, 50)},
            "errors": [],
            "remote_status": 0,
            "enforce": True,
        }
        arguments.update(overrides)
        return ps.render(**arguments)

    def test_pass(self):
        text, code = self.render()
        self.assertEqual(code, 0)
        self.assertIn("**Wynik:** PASS", text)

    def test_budget_exceedance_depends_on_enforce(self):
        slow = {"hub_login_ms": (200.0, "ms")}
        text, code = self.render(measured=slow)
        self.assertEqual(code, 1)
        self.assertIn("PRZEKROCZENIE BUDŻETU", text)

        text, code = self.render(measured=slow, enforce=False)
        self.assertEqual(code, 0)
        self.assertIn("tylko raport", text)

    def test_min_direction_metric(self):
        budget = {"workspace_write_mbps": 60.0}
        text, code = self.render(
            budget=budget,
            measured={"workspace_write_mbps": (59.0, "MiB/s")},
            samples={"workspace_write_mbps": (59, 59, 59)},
        )
        self.assertEqual(code, 1)
        self.assertIn("≥ 60", text)

    def test_missing_and_sampleless_metrics_are_measurement_errors(self):
        text, code = self.render(measured={}, samples={})
        self.assertEqual(code, 2)
        self.assertIn("BŁĄD POMIARU", text)

        text, code = self.render(samples={})
        self.assertEqual(code, 2)
        self.assertIn("brak próbek", text)

    def test_small_n_and_remote_status_are_reported(self):
        text, code = self.render(samples={"hub_login_ms": (50, 50)})
        self.assertEqual(code, 0)
        self.assertIn("n<3", text)

        text, code = self.render(remote_status=7)
        self.assertEqual(code, 2)
        self.assertIn("kodem 7", text)

    def test_errors_are_listed(self):
        text, code = self.render(errors=["ERROR hub_login_ms incomplete"])
        self.assertEqual(code, 2)
        self.assertIn("#### Błędy pomiaru", text)
        self.assertIn("ERROR hub_login_ms incomplete", text)


class MainTests(unittest.TestCase):
    def run_main(self, root: Path, *, budget: str, results: str, samples: str, extra=()):
        (root / "budget.env").write_text(budget)
        (root / "results.txt").write_text(results)
        (root / "samples.txt").write_text(samples)
        output = root / "out/summary.md"
        code = ps.main(
            [
                "--results",
                str(root / "results.txt"),
                "--samples",
                str(root / "samples.txt"),
                "--budget",
                str(root / "budget.env"),
                "--output",
                str(output),
                *extra,
            ]
        )
        return code, output.read_text()

    def test_writes_pass_report(self):
        with tempfile.TemporaryDirectory() as directory:
            code, text = self.run_main(
                Path(directory),
                budget="hub_login_ms=100\n",
                results="hub_login_ms 45 ms\n",
                samples="SAMPLE hub_login_ms 40 45 50\n",
            )
            self.assertEqual(code, 0)
            self.assertIn("**Wynik:** PASS", text)

    def test_configuration_and_measurement_errors_exit_two(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, text = self.run_main(
                root,
                budget="hub_login_ms=100\n",
                results="hub_login_ms 99 ms\n",
                samples="SAMPLE hub_login_ms 40 45 50\n",
            )
            self.assertEqual(code, 2)
            self.assertIn("nie jest medianą", text)

            code, text = self.run_main(
                root,
                budget="hub_login_ms=100\n",
                results="unknown_ms 1 ms\n",
                samples="SAMPLE unknown_ms 1\n",
            )
            self.assertEqual(code, 2)
            self.assertIn("bez progu w budżecie", text)

            code, text = self.run_main(
                root,
                budget="hub_login_ms=100\n",
                results="ERROR\n",
                samples="",
            )
            self.assertEqual(code, 2)
            self.assertIn("BŁĄD POMIARU/KONFIGURACJI", text)


if __name__ == "__main__":
    unittest.main()

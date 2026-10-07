"""Tests for the command line and the Makefile."""

import contextlib
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import synthetic  # noqa: E402
from synthetic import ROOT  # noqa: E402

import report  # noqa: E402
import replenishment  # noqa: E402


def run(*args):
    """Run the command line in-process; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = replenishment.main([str(arg) for arg in args])
    return code, out.getvalue(), err.getvalue()


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.workbook = self.folder / "workbook.xlsx"
        self.workbook.write_bytes(b"stand-in for the workbook")
        digest = hashlib.sha256(self.workbook.read_bytes()).hexdigest()
        self.config = self.folder / "config.toml"
        self.config.write_text(synthetic.config_text(digest, self.workbook.stat().st_size), encoding="utf-8")
        self.reader = mock.patch("data.read_workbook", return_value=synthetic.source())
        self.read = self.reader.start()

    def tearDown(self):
        self.reader.stop()
        self.temporary.cleanup()

    def test_invalid_configuration_is_rejected_before_the_workbook_is_read(self):
        for old, new in (("capacity_factor = 1.0", "capacity_factor = -1.0"), ("skus = 4", "skus = -1"),
                         ("holding_rate = 0.05", "holding_rate = nan"), ('window = "trailing_52"', 'window = "x"')):
            self.config.write_text(synthetic.config_text().replace(old, new, 1), encoding="utf-8")
            with self.subTest(change=new):
                code, out, err = run("analyze", "--config", self.config, "--input", self.folder / "missing.xlsx",
                                     "--output", self.folder / "exports")
                self.assertEqual(code, 2)
                self.assertIn("error:", err)
                self.assertNotIn("missing.xlsx", err)
        self.read.assert_not_called()
        self.assertFalse((self.folder / "exports").exists())

    def test_workbook_must_match_the_configuration(self):
        self.workbook.write_bytes(b"a different file")
        code, _, err = run("check", "--config", self.config, "--input", self.workbook)
        self.assertEqual(code, 2)
        self.assertIn("not the expected workbook", err)
        code, _, err = run("analyze", "--config", self.config, "--input", self.folder / "missing.xlsx",
                           "--output", self.folder / "exports")
        self.assertEqual((code, "make data" in err), (2, True))
        self.read.assert_not_called()

    def test_analyze_names_the_best_policy_within_capacity_and_verify_checks_the_bundle(self):
        exports = self.folder / "exports"
        code, out, _ = run("analyze", "--config", self.config, "--input", self.workbook, "--output", exports)
        self.assertEqual(code, 0)
        best = json.loads((exports / "summary.json").read_text(encoding="utf-8"))["best_within_capacity"]
        self.assertIn(f"lowest modeled cost within capacity: {replenishment.experiment.POLICIES[best]}", out)
        self.assertIn("reference without the limit: Unconstrained newsvendor", out)
        code, out, _ = run("verify", "--config", self.config, "--input", self.workbook, "--output", exports)
        self.assertEqual((code, out.strip()), (0, "verify: every artifact matches"))
        manifest = exports / report.MANIFEST
        original = manifest.read_text(encoding="utf-8")
        record = json.loads(original)
        record["artifacts"]["summary.json"]["sha256"] = "0" * 64
        del record["sources"]["src/experiment.py"]
        manifest.write_text(json.dumps(record), encoding="utf-8")
        code, _, err = run("verify", "--config", self.config, "--input", self.workbook, "--output", exports)
        self.assertEqual(code, 1)
        self.assertIn("src/experiment.py differs from the file the manifest records", err)
        self.assertIn("summary.json is missing or does not match the manifest", err)
        manifest.write_text(original, encoding="utf-8")
        with open(exports / "weekly_sales.csv", "a", encoding="utf-8") as handle:
            handle.write("tampered\n")
        code, _, err = run("verify", "--config", self.config, "--input", self.workbook, "--output", exports)
        self.assertEqual(code, 1)
        self.assertIn("weekly_sales.csv differs from a fresh rebuild", err)

    def test_zero_capacity_factor_runs_with_zero_capacity(self):
        self.config.write_text(self.config.read_text().replace("capacity_factor = 1.0", "capacity_factor = 0.0", 1),
                               encoding="utf-8")
        exports = self.folder / "exports"
        code, out, _ = run("analyze", "--config", self.config, "--input", self.workbook, "--output", exports)
        self.assertEqual(code, 0)
        self.assertIn("capacity 0 units", out)
        rows = json.loads((exports / "summary.json").read_text())["policies"]
        self.assertEqual({row["id"]: row["allocated_units"] == 0 for row in rows},
                         {policy: policy != "unconstrained" for policy in replenishment.experiment.POLICIES})

    def test_zero_shortage_rate_runs_and_undefined_ratios_are_unavailable(self):
        self.config.write_text(self.config.read_text().replace("shortage_rate = 0.30", "shortage_rate = 0.0", 1),
                               encoding="utf-8")
        exports = self.folder / "exports"
        code, _, err = run("analyze", "--config", self.config, "--input", self.workbook, "--output", exports)
        self.assertEqual((code, err), (0, ""))
        summary = json.loads((exports / "summary.json").read_text(encoding="utf-8"))
        costs = {row["id"]: row["total_cost"] for row in summary["policies"]}
        self.assertEqual(costs["optimizer"], 0)  # no shortage cost: holding nothing is optimal
        for entry in summary["comparisons"]:
            expected = 0 if costs[entry["baseline"]] == 0 else -1
            self.assertEqual(entry["relative"], expected)
        report_text = (exports / "insight_report.md").read_text(encoding="utf-8")
        self.assertNotRegex(report_text, r"\b(nan|NaN|None)\b")

    def test_readme_command_rewrites_the_block(self):
        exports = self.folder / "exports"
        self.assertEqual(run("analyze", "--config", self.config, "--input", self.workbook, "--output", exports)[0], 0)
        readme = self.folder / "README.md"
        readme.write_text(f"# Title\n\n{report.README_START}\n{report.README_END}\n", encoding="utf-8")
        with mock.patch.object(report, "ROOT", self.folder):
            code, out, _ = run("readme", "--output", exports)
        self.assertEqual((code, out.strip()), (0, "README.md results block updated"))
        summary = json.loads((exports / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(readme.read_text(encoding="utf-8"), f"# Title\n\n{report.readme_block(summary)}\n")


@unittest.skipUnless(shutil.which("make"), "make is not installed")
class MakefileTests(unittest.TestCase):
    def dry_run(self, target):
        return subprocess.run(["make", "-n", target, "PYTHON=python3"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout

    def test_clean_removes_temporary_files_only(self):
        commands = self.dry_run("clean")
        self.assertIn("exports.staging", commands)
        for line in commands.splitlines():
            self.assertNotRegex(line, r"exports/|exports\s|\*\.csv|\*\.md|\*\.svg|\*\.json")

    def test_targets_run_the_published_configuration(self):
        self.assertIn("src/replenishment.py analyze --config configs/published.toml", self.dry_run("analyze"))
        self.assertIn("src/replenishment.py verify --config configs/published.toml", self.dry_run("verify"))
        self.assertIn("src/replenishment.py readme --output exports", self.dry_run("readme"))


if __name__ == "__main__":
    unittest.main()

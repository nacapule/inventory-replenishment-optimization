"""Tests for the summary, the report wording, the figure, the README block, the exports
and staged publishing."""

import copy
import json
import re
import string
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from functools import cache
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import synthetic  # noqa: E402
from synthetic import ROOT  # noqa: E402

import experiment  # noqa: E402
import report  # noqa: E402

EXPORTS = ROOT / "exports"
NAMES = experiment.POLICIES
INFO = {"file": "synthetic.xlsx", "bytes": 1, "sha256": "0" * 64}
CONFIG = ROOT / "configs" / "published.toml"


def comparison(relative, low, high, won=20, lost=32, tied=0, baseline="scaled_fractile"):
    return {"policy": "optimizer", "baseline": baseline, "relative": relative, "confidence": 0.95,
            "interval": {"relative": [low, high]}, "weeks_won": won, "weeks_lost": lost, "weeks_tied": tied}


@cache
def summary(weeks=52):
    return report.summarize(synthetic.result(weeks))


class WordingTests(unittest.TestCase):
    def test_lower_cost_is_described_as_lower(self):
        text = report.describe(comparison(-0.05, -0.08, -0.02, won=30, lost=22), 52)
        self.assertIn("5.0% lower than the scaled critical-fractile rule's", text)
        self.assertIn("95% interval 2.0% to 8.0% lower", text)
        self.assertIn("it cost less in 30 of the 52 weeks and more in 22", text)
        self.assertNotIn("higher", text)
        self.assertNotIn("−", text)

    def test_higher_cost_is_described_as_higher(self):
        text = report.describe(comparison(0.04, 0.006, 0.083), 52)
        self.assertIn("4.0% higher than the scaled critical-fractile rule's", text)
        self.assertIn("0.6% to 8.3% higher", text)
        self.assertNotIn("lower", text)
        self.assertNotIn("reduc", text)

    def test_interval_including_zero_is_no_clear_difference(self):
        text = report.describe(comparison(-0.013, -0.049, 0.033), 52)
        self.assertIn("no clear difference", text)
        self.assertIn("from 4.9% lower to 3.3% higher", text)
        follow = report.describe(comparison(-0.013, -0.049, 0.033, baseline="proportional"), 52, lead=False)
        self.assertTrue(follow.startswith("Against proportional allocation, there was no clear difference: "
                                          "1.3% lower in total"))

    def test_equal_costs_are_described_as_equal(self):
        text = report.describe(comparison(0.0, 0.0, 0.0, won=0, lost=0, tied=52), 52)
        self.assertIn("equal to the scaled critical-fractile rule's", text)
        self.assertIn("the same in every resample", text)
        self.assertIn("the same in 52", text)
        self.assertEqual(report.change(0.0004), "less than 0.1% higher")

    def test_generated_prose_never_states_a_negative_change(self):
        for weeks in (52, 13):
            values = report.insight_values(summary(weeks))
            prose = " ".join([values["headline"], values["bridge_sentence"], values["sensitivity_sentence"],
                              values["largest_week"]])
            self.assertIsNone(re.search(r"(lower|higher|reduced|increased)[^.]*−\d", prose))
            self.assertNotIn("reduced", prose)

    def test_sentences_and_figure_follow_the_run_length(self):
        short = summary(13)
        self.assertIn("Over the 13 evaluation weeks", report.insight_values(short)["headline"])
        self.assertIn("of the 13 weeks", report.readme_values(short)["headline"])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "figure.svg"
            report.write_cost_difference_figure(report.weekly_cost(synthetic.result(13).primary), NAMES, path)
            self.assertIn("(13 weeks)", path.read_text(encoding="utf-8"))

    def test_largest_week_cites_a_credit_only_when_one_exists(self):
        current = summary()
        self.assertIn("matched by credit C900006", report._largest(current))
        without = copy.deepcopy(current)
        without["largest_week"]["credit"] = None
        text = report._largest(without)
        self.assertIn("No credit in the source matches that line.", text)
        self.assertNotIn("credit C", text)


class SummaryTests(unittest.TestCase):
    def test_best_policy_within_the_limit_excludes_the_reference(self):
        rows = [
            {"id": "unconstrained", "name": NAMES["unconstrained"], "reference": True, "within_capacity": False,
             "total_cost": 1.0},
            {"id": "optimizer", "name": NAMES["optimizer"], "reference": False, "within_capacity": True,
             "total_cost": 3.0},
            {"id": "scaled_fractile", "name": NAMES["scaled_fractile"], "reference": False, "within_capacity": True,
             "total_cost": 2.0},
        ]
        self.assertEqual(report.best_within_capacity(rows), "scaled_fractile")
        fake = {"policies": rows, "best_within_capacity": "scaled_fractile",
                "study": {"cohort_size": 20, "capacity_units": 6455}}
        line = report.console_line(fake, "exports")
        self.assertIn("lowest modeled cost within capacity: Scaled critical-fractile (£2)", line)
        self.assertIn("reference without the limit: Unconstrained newsvendor (£1)", line)
        self.assertNotIn("best policy", line)

    def test_summary_is_plain_json_with_every_policy(self):
        current = summary()
        text = json.dumps(current, allow_nan=False)
        self.assertEqual(json.loads(text), current)
        self.assertEqual([row["id"] for row in current["policies"]], list(NAMES))
        self.assertEqual([row["id"] for row in current["sensitivity"]],
                         ["primary", "ratio_0.95", "seasonal_analog", "bulk_cap"])
        capacities = {row["capacity_units"] for row in current["sensitivity"]}
        self.assertEqual(capacities, {current["study"]["capacity_units"]})


class TemplateTests(unittest.TestCase):
    def test_placeholders_match_the_generated_values(self):
        current = summary()
        values = {
            "insight_report.md": report.insight_values(current),
            "data_quality.md": report.quality_values(current, synthetic.result().tables),
            "readme_results.md": report.readme_values(current),
        }
        for name, generated in values.items():
            template = string.Template((report.TEMPLATES / name).read_text(encoding="utf-8"))
            with self.subTest(template=name):
                self.assertTrue(template.is_valid())
                self.assertEqual(set(template.get_identifiers()), set(generated))

    def test_column_tables_list_every_exported_column(self):
        text = (report.TEMPLATES / "data_quality.md").read_text(encoding="utf-8")
        documented = {}
        for name, body in re.findall(r"### `([a-z_]+\.csv)`\n(.*?)(?=\n### |\Z)", text, flags=re.S):
            cells = [row.split("|")[1] for row in body.splitlines() if row.startswith("| `")]
            documented[name] = {column for cell in cells for column in re.findall(r"`([a-z_0-9]+)`", cell)}
        frames = report.frames(synthetic.result())
        self.assertEqual(set(documented), set(report.CSVS))
        for name, frame in frames.items():
            with self.subTest(file=name):
                self.assertEqual(set(frame.columns), documented[name])
                if (EXPORTS / name).exists():
                    self.assertEqual(list(pd.read_csv(EXPORTS / name, nrows=0).columns), list(frame.columns))


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, name):
        folder = self.folder / name
        folder.mkdir()
        report.write_bundle(synthetic.result(), folder, CONFIG, INFO)
        return folder

    def test_rebuilt_bundle_is_byte_identical(self):
        first, second = self.write("a"), self.write("b")
        names = sorted(path.name for path in first.iterdir())
        self.assertEqual(names, sorted(report.ARTIFACTS + (report.MANIFEST,)))
        for name in names:
            with self.subTest(file=name):
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())

    def test_manifest_records_inputs_sources_and_artifacts(self):
        folder = self.write("bundle")
        text = (folder / report.MANIFEST).read_text(encoding="utf-8")
        record = json.loads(text)
        self.assertNotIn(str(Path.home()), text)
        self.assertEqual(record["input"], INFO)
        self.assertEqual(set(record["sources"]), set(report.SOURCES) | {"configs/published.toml"})
        for name, entry in record["artifacts"].items():
            self.assertEqual(entry["sha256"], report.sha256(folder / name))
        self.assertEqual(record["artifacts"]["weekly_results.csv"]["rows"], 5 * 52 * 4)
        self.assertEqual(record["calendar"]["closure_weeks"], ["2009-12-28", "2010-12-27"])
        self.assertEqual(record["calendar"]["partial_weeks"], ["2009-11-30", "2011-12-05"])
        self.assertFalse({"time", "created", "commit", "date"} & set(record))

    def test_failed_run_leaves_the_previous_bundle(self):
        output = self.folder / "exports"
        report.publish(output, lambda folder: report.write_bundle(synthetic.result(), folder, CONFIG, INFO))
        before = {path.name: path.read_bytes() for path in output.iterdir()}

        def failing(folder):
            (folder / "policy_comparison.csv").write_text("partial\n")
            raise OSError("disk full")

        def incomplete(folder):
            report.write_bundle(synthetic.result(), folder, CONFIG, INFO)
            (folder / "summary.json").write_text("{}\n")

        for write, error in ((failing, OSError), (incomplete, RuntimeError)):
            with self.subTest(write=write.__name__), self.assertRaises(error):
                report.publish(output, write)
            self.assertEqual({path.name: path.read_bytes() for path in output.iterdir()}, before)
            self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["exports"])


class ReadmeTests(unittest.TestCase):
    def test_committed_block_matches_the_committed_summary(self):
        summary_ = json.loads((EXPORTS / "summary.json").read_text(encoding="utf-8"))
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        start, end = readme.index(report.README_START), readme.index(report.README_END) + len(report.README_END)
        self.assertEqual(readme[start:end], report.readme_block(summary_))

    def test_update_rewrites_only_the_block(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "README.md"
            path.write_text(f"intro\n\n{report.README_START}\nold\n{report.README_END}\n\nrest\n", encoding="utf-8")
            self.assertTrue(report.update_readme(path, summary()))
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("intro\n\n" + report.README_START))
            self.assertTrue(text.endswith(report.README_END + "\n\nrest\n"))
            self.assertNotIn("\nold\n", text)
            self.assertFalse(report.update_readme(path, summary()))
            path.write_text("no markers\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                report.update_readme(path, summary())


class CommittedExportTests(unittest.TestCase):
    def test_dashboard_files_keep_their_columns_and_grain(self):
        expected = {
            "policy_comparison.csv": (["policy", "allocated_units", "fill_rate", "stockout_rate", "holding_cost",
                                       "shortage_cost", "total_cost"], len(NAMES)),
            "sku_decisions.csv": (["sku", "description", "unit_price", "train_mean", "train_std",
                                   "train_positive_median", "train_max", "active_train_weeks", "proportional_qty",
                                   "optimized_qty", "newsvendor_qty", "spike_ratio"], 20),
            "forecast_metrics.csv": (["method", "wape", "bias", "mae"], len(experiment.WINDOWS)),
        }
        for name, (columns, rows) in expected.items():
            frame = pd.read_csv(EXPORTS / name)
            with self.subTest(file=name):
                self.assertEqual(list(frame.columns[:len(columns)]), columns)
                self.assertEqual(len(frame), rows)

    def test_committed_manifest_matches_the_committed_artifacts(self):
        record = json.loads((EXPORTS / report.MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(set(record["artifacts"]), set(report.ARTIFACTS))
        for name, entry in record["artifacts"].items():
            with self.subTest(file=name):
                self.assertEqual(report.sha256(EXPORTS / name), entry["sha256"])
        self.assertEqual(sorted(path.name for path in EXPORTS.iterdir()),
                         sorted(report.ARTIFACTS + (report.MANIFEST,)))


# The figure -------------------------------------------------------------------------------


def weekly_cost(weeks: int, seed: int, optimizer_factor) -> pd.DataFrame:
    """Synthetic weekly totals; `optimizer_factor(week_number)` scales the optimizer's cost."""
    index = pd.date_range("2010-12-06", periods=weeks, freq="W-MON", name="week_start")
    rng = np.random.default_rng(seed)
    base = rng.uniform(900.0, 1600.0, size=weeks)
    frame = pd.DataFrame({policy: base * rng.uniform(0.95, 1.05, size=weeks) for policy in NAMES}, index=index)
    frame["optimizer"] = base * np.array([optimizer_factor(i) for i in range(weeks)])
    return frame


FAVOURABLE = weekly_cost(52, 1, lambda i: 0.9)
UNFAVOURABLE = weekly_cost(52, 2, lambda i: 1.1)
MIXED = weekly_cost(52, 3, lambda i: 0.8 if i % 2 else 1.2)
QUARTER = weekly_cost(13, 4, lambda i: 0.9)
ONE_WEEK = weekly_cost(1, 5, lambda i: 0.9)


def running_totals(frame: pd.DataFrame, reference: str, baseline: str) -> list[float]:
    totals, running = [], 0.0
    for week in frame.index:
        running += float(frame.at[week, reference]) - float(frame.at[week, baseline])
        totals.append(running)
    return totals


class CostDifferenceTests(unittest.TestCase):
    def test_matches_running_totals_for_every_sign_and_length(self):
        for frame in (FAVOURABLE, UNFAVOURABLE, MIXED, QUARTER, ONE_WEEK):
            result = report.cost_difference(frame)
            self.assertEqual(list(result.columns), ["scaled_fractile", "proportional"])
            self.assertTrue(result.index.equals(frame.index))
            for baseline in result.columns:
                expected = running_totals(frame, "optimizer", baseline)
                np.testing.assert_allclose(result[baseline].to_numpy(), expected, rtol=1e-12)

    def test_sign_follows_reference_minus_baseline(self):
        self.assertTrue((report.cost_difference(FAVOURABLE) < 0).all().all())
        self.assertTrue((report.cost_difference(UNFAVOURABLE) > 0).all().all())
        result = report.cost_difference(FAVOURABLE, reference="scaled_fractile", baselines=("unconstrained",))
        np.testing.assert_allclose(result["unconstrained"].to_numpy(),
                                   running_totals(FAVOURABLE, "scaled_fractile", "unconstrained"), rtol=1e-12)


class FigureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, frame, name, **kwargs) -> str:
        path = self.folder / f"{name}.svg"
        report.write_cost_difference_figure(frame, NAMES, path, **kwargs)
        return path.read_text(encoding="utf-8")

    def test_same_data_gives_the_same_file_without_a_date(self):
        for frame in (MIXED, QUARTER):
            self.assertEqual(self.write(frame, "a"), self.write(frame, "b"))
        svg = self.write(FAVOURABLE, "favourable")
        self.assertGreater(len(ET.fromstring(svg).findall(".//{http://www.w3.org/2000/svg}text")), 10)
        self.assertNotIn("dc:date", svg)
        self.assertNotIn("Matplotlib v", svg)

    def test_labels_come_from_the_names_and_the_data(self):
        svg = self.write(UNFAVOURABLE, "unfavourable")
        for policy in ("optimizer", "scaled_fractile", "proportional"):
            self.assertIn(NAMES[policy], svg)
        for policy in ("optimizer_unit", "unconstrained"):
            self.assertNotIn(NAMES[policy], svg)
        for text in ("6 December 2010", "4 December 2011", "(52 weeks)", "has cost more so far"):
            self.assertIn(text, svg)
        for baseline in ("scaled_fractile", "proportional"):
            self.assertIn(report.money(running_totals(UNFAVOURABLE, "optimizer", baseline)[-1]), svg)
        other = self.write(MIXED, "other", reference="scaled_fractile", baselines=("proportional",))
        self.assertNotIn(NAMES["optimizer"], other)

    def test_short_and_flat_inputs_render(self):
        self.assertIn("(13 weeks)", self.write(QUARTER, "quarter"))
        self.assertIn("(1 week)", self.write(ONE_WEEK, "one"))
        flat = FAVOURABLE.copy()
        flat["optimizer"] = flat["proportional"] = flat["scaled_fractile"]
        self.assertIn("£0 at the end", self.write(flat, "flat"))

    def test_global_settings_are_left_unchanged(self):
        before = dict(matplotlib.rcParams)
        self.write(MIXED, "settings")
        self.assertEqual(dict(matplotlib.rcParams), before)


if __name__ == "__main__":
    unittest.main()

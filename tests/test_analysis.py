"""Offline tests for scripts/analyze.py, on synthetic matrices with known answers.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import analyze  # noqa: E402
import make_matrix  # noqa: E402

STABLE, RARE, UNSTABLE, COIN, BELOW = (*analyze.BINS, analyze.BELOW)


def runs_of(*runs: str) -> list[list[str]]:
    """Runs from short codes: s skip, c comment, t comment+tool, u upvote,
    A api error, P parse error. One string per run, or one string for all six."""
    codes = {"s": "skip", "c": "comment", "t": "comment+tool", "u": "upvote",
             "A": "!api", "P": "!parse"}
    if len(runs) == 1:
        runs = runs * 6
    assert all(len(r) == 5 for r in runs)
    return [[codes[ch] for ch in r] for r in runs]


def split(k: int) -> list[list[str]]:
    """Six runs with k skip then 30 - k comment."""
    values = ["skip"] * k + ["comment"] * (30 - k)
    return [values[i:i + 5] for i in range(0, 30, 5)]


def matrix(cases: dict[str, list[list[str]]], stratum: dict[str, str] | None = None,
           expected: dict[str, str] | None = None, thinking: dict[str, list[str]] | None = None,
           start_hours: list[int] | None = None) -> str:
    """Runs start at 07:00 and 13:00 UTC on 12, 13 and 14 October unless
    start_hours (hours after 12 October 00:00 UTC, one per run) says otherwise."""
    stratum, expected, thinking = stratum or {}, expected or {}, thinking or {}
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(make_matrix.COLUMNS), lineterminator="\n")
    writer.writeheader()
    for public_id, runs in sorted(cases.items()):
        tokens = iter(thinking.get(public_id, []))
        for run, values in enumerate(runs, 1):
            hours = start_hours[run - 1] if start_hours else 24 * ((run - 1) // 2) + 7 + 6 * ((run - 1) % 2)
            day, hour = 12 + hours // 24, hours % 24
            for sample, value in enumerate(values, 1):
                error = value[1:] if value.startswith("!") else ""
                row = {name: "" for name in make_matrix.COLUMNS}
                row.update(
                    public_id=public_id, stratum=stratum.get(public_id, "skipped"),
                    label_status="labelled" if public_id in expected else "deferred",
                    expected=expected.get(public_id, ""), day_label="A", text_empty="false",
                    run=str(run), seed=str(100 + run), sample=str(sample),
                    started_at=f"2026-10-{day:02d}T{hour:02d}:00:0{sample}+00:00",
                    error_type=error, attempts="1", hook_failed="false",
                    verdict_raw="" if error else value,
                    verdict_settled="" if error else ("comment" if value == "comment+tool" else value),
                    thinking_tokens=next(tokens, "" if error == "api" else "100"))
                writer.writerow(row)
    return out.getvalue()


def load(text: str) -> tuple[list[analyze.Case], int]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "matrix.csv"
        path.write_text(text)
        return analyze.load_matrix(path)


def analyse(cases: dict, permutations: int = 200, **kw) -> dict:
    loaded, planned = load(matrix(cases, **kw))
    return analyze.analyse(loaded, planned, permutations=permutations)


def by_id(result: dict) -> dict[str, dict]:
    return {c["public_id"]: c for c in result["cases"]}


class DefinitionsTest(unittest.TestCase):
    def test_bin_names_are_those_of_the_protocol(self):
        self.assertEqual(analyze.BINS, ("stable", "rare flips", "unstable", "coin-like"))

    def test_all_stable(self):
        result = analyse({"p001": runs_of("sssss"), "p002": runs_of("ccccc"),
                          "p003": runs_of("ttttt")}, stratum={"p003": "proposed"})
        dist = result["7.1"]["distribution"]
        self.assertEqual(dist["all"]["bins"][STABLE]["count"], 3)
        for b in (RARE, UNSTABLE, COIN, BELOW):
            entry = dist["all"]["bins"][b]
            self.assertEqual(entry["count"], 0)
            self.assertAlmostEqual(entry["upper_bound"], 1 - 0.025 ** (1 / 3), 6)
            self.assertEqual(entry["upper_bound"], entry["ci95"][1])
        self.assertEqual(result["7.2"]["skipped"]["non_unanimous"]["count"], 0)
        self.assertIn("upper_bound", result["7.2"]["proposed"]["between_run_unstable"])
        self.assertEqual(result["7.3"]["observed"], 0)
        self.assertEqual(result["7.3"]["reference"], {"0": 200})
        self.assertEqual(result["7.3"]["p_one_sided"], 1.0)
        breakdowns = result["7.1"]["breakdowns"]
        self.assertEqual(set(breakdowns), {"all", "proposed", "skipped"})
        self.assertEqual(breakdowns["proposed"]["by_modal_verdict"]["comment+tool"][STABLE], 1)
        self.assertEqual(breakdowns["all"]["by_label_status"]["deferred"][STABLE], 3)
        settled = result["8.1"]["settled"]["all"]["bins"]
        self.assertEqual(settled[STABLE]["count"], 3)
        self.assertNotIn("upper_bound", settled[RARE])

    def test_bin_boundaries(self):
        expected = {30: STABLE, 29: RARE, 24: RARE, 23: UNSTABLE, 18: UNSTABLE, 17: COIN, 15: COIN}
        result = analyse({f"p{k:03d}": split(k) for k in expected})
        self.assertEqual({c["modal_count"]: c["bin"] for c in result["cases"]}, expected)

    def test_threshold_follows_the_runs_present(self):
        self.assertEqual([analyze.threshold(5 * k) for k in range(1, 7)], [5, 9, 13, 17, 21, 25])
        four_runs = analyse({"p001": runs_of("sssss", "sssss", "sssss", "sssAA"),
                             "p002": runs_of("sssss", "sssss", "sssss", "sAAAA")})
        self.assertEqual(four_runs["threshold"], {"planned_samples": 20, "min_valid": 17})
        self.assertEqual(by_id(four_runs)["p001"]["bin"], STABLE)
        self.assertEqual(by_id(four_runs)["p002"]["bin"], BELOW)

    def test_one_coin_like_case(self):
        result = analyse({"p001": runs_of("sssss"), "p002": split(15)})
        coin = by_id(result)["p002"]
        self.assertEqual((coin["modal_count"], coin["modal_share"], coin["bin"]), (15, 0.5, COIN))
        self.assertEqual(coin["non_unanimous_runs"], 0)
        self.assertTrue(coin["between_run_unstable"])
        self.assertEqual(result["7.1"]["distribution"]["all"]["bins"][COIN]["count"], 1)
        self.assertEqual(result["7.1"]["breakdowns"]["all"]["by_modal_verdict"][analyze.TIE][COIN], 1)

    def test_run_tie_is_one_value(self):
        case = runs_of("sssss", "sssss", "sscuc", "sssss", "sssss", "sssss")
        result = analyse({"p001": case})
        entry = by_id(result)["p001"]
        self.assertEqual(entry["run_verdicts"], ["skip", "skip", analyze.TIE, "skip", "skip", "skip"])
        self.assertTrue(entry["between_run_unstable"])
        self.assertEqual(entry["non_unanimous_runs"], 1)
        self.assertEqual(result["7.2"]["skipped"]["between_run_unstable"]["count"], 1)

    def test_ties_on_different_verdicts_are_equal(self):
        case = runs_of("sscuc", "ssuuc", "sscuc", "sscuc", "sscuc", "sscuc")
        self.assertFalse(by_id(analyse({"p001": case}))["p001"]["between_run_unstable"])

    def test_run_without_valid_samples_is_left_out(self):
        case = runs_of("AAAAA", "sssss", "sssss", "sssss", "sssss", "sssss")
        entry = by_id(analyse({"p001": case}))["p001"]
        self.assertEqual(entry["run_verdicts"][0], analyze.NO_VALID)
        self.assertFalse(entry["between_run_unstable"])

    def test_errors_take_a_case_below_the_threshold(self):
        cases = {"p001": runs_of("sssss"),
                 "p002": runs_of("AAAAA", "Ascss", "sssss", "sssss", "sssss", "sssss")}
        result = analyse(cases, expected={"p001": "skip", "p002": "skip"})
        entry = by_id(result)["p002"]
        self.assertEqual((entry["valid"], entry["bin"]), (24, BELOW))
        self.assertEqual(entry["errors"], {"api": 6, "parse": 0, "refusal": 0, "max_tokens": 0})
        dist = result["7.1"]["distribution"]["all"]["bins"]
        self.assertEqual(dist[STABLE], analyze.proportion(1, 2))
        self.assertEqual(dist[BELOW], analyze.proportion(1, 2))
        s72 = result["7.2"]["skipped"]
        self.assertEqual((s72["cases"], s72["below_threshold_left_out"]), (1, 1))
        self.assertEqual(s72["non_unanimous"]["count"], 0)
        self.assertEqual((result["7.3"]["cases"], result["7.3"]["below_threshold_left_out"]), (1, 1))
        self.assertEqual((result["8.3"]["cases"], result["8.3"]["below_threshold_left_out"]), (1, 1))
        s82 = result["8.2"]["skipped"]
        self.assertEqual((s82["cases"], s82["below_threshold_left_out"], s82["agree"]), (1, 1, 1))
        pairs = result["8.4"]["run_pairs"]
        self.assertEqual((pairs["cases"], pairs["below_threshold_left_out"]), (1, 1))
        # p002's run 2 differs from the others, but p002 is left out.
        self.assertTrue(all(p["cases_differing"] == 0 for p in pairs["pairs"]))
        self.assertEqual(result["8.4"]["by_day_label"]["A"][BELOW], 1)
        self.assertEqual(result["8.1"]["pass_fail"]["all"]["bins"][BELOW]["count"], 1)
        self.assertEqual(result["8.6"]["1"]["errors"], 5)
        self.assertEqual(result["8.6"]["2"]["by_type"]["api"], 1)

    def test_sensitivity_counts_an_error_as_one_value(self):
        cases = {"p001": runs_of("AAAAA", "AAAAA", "PPPPP", "PPPPP", "sssss", "sssss"),
                 "p002": runs_of("Assss", "sssss", "sssss", "sssss", "sssss", "sssss")}
        result = analyse(cases)
        self.assertEqual(by_id(result)["p001"]["bin"], BELOW)
        bins = result["8.7"]["all"]["bins"]
        # p001: 20 errors of two types as one value, 20/30 -> unstable; p002: 29/30.
        self.assertEqual((bins[UNSTABLE]["count"], bins[RARE]["count"], bins[BELOW]["count"]), (1, 1, 0))

    def test_pass_fail_and_agreement(self):
        cases = {"p001": runs_of("ttttt"), "p002": split(20), "p003": runs_of("ccccc"),
                 "p004": split(15), "p005": runs_of("sssss")}
        result = analyse(cases, expected={"p001": "comment", "p002": "skip", "p003": "comment+tool",
                                          "p004": "skip"},
                         stratum={"p001": "proposed", "p003": "proposed"})
        pf = result["8.1"]["pass_fail"]["all"]
        self.assertEqual(pf["cases"], 4)
        self.assertEqual(pf["bins"][STABLE]["count"], 2)    # p001 all pass, p003 all fail
        self.assertEqual(pf["bins"][UNSTABLE]["count"], 1)  # p002: 20 pass, 10 fail
        self.assertEqual(pf["bins"][COIN]["count"], 1)      # p004: 15 and 15
        proposed, skipped = result["8.2"]["proposed"], result["8.2"]["skipped"]
        self.assertEqual((proposed["agree"], proposed["disagree"]), (1, 1))
        self.assertEqual((skipped["agree"], skipped["tied_left_out"]), (1, 1))
        self.assertEqual(skipped["bins"]["agree"][UNSTABLE], 1)

    def test_thinking_over_every_call_that_reports_it(self):
        cases = {"p001": runs_of("sssss"), "p002": runs_of("sssss"),
                 "p003": runs_of("PPsss", "sssss", "sssss", "sssss", "sssss", "sssss")}
        result = analyse(cases, thinking={"p001": ["100"] * 30, "p002": ["0"] * 30,
                                          "p003": ["0", "0"] + ["50"] * 28})
        groups = result["8.3"]["groups"]
        # p003's two zeros are on its parse errors: counted, so p003 is "some".
        self.assertEqual({g: v["cases"] for g, v in groups.items()}, {"always": 1, "never": 1, "some": 1})
        self.assertEqual(groups["some"]["bins"][STABLE], 1)

    def test_spearman(self):
        self.assertAlmostEqual(analyze.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(analyze.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        self.assertEqual(analyze.ranks([5, 1, 5, 2]), [3.5, 1.0, 3.5, 2.0])
        self.assertIsNone(analyze.spearman([1, 1, 1], [1, 2, 3]))

    def test_run_pairs_and_run_days(self):
        case = runs_of("sssss", "sssss", "ccccc", "ccccc", "sssss", "sssss")
        result = analyse({"p001": case, "p002": runs_of("sssss")})
        self.assertEqual(result["8.4"]["run_day"],
                         {"1": "2026-10-12", "2": "2026-10-12", "3": "2026-10-13",
                          "4": "2026-10-13", "5": "2026-10-14", "6": "2026-10-14"})
        pairs = {tuple(p["runs"]): p for p in result["8.4"]["run_pairs"]["pairs"]}
        self.assertEqual(len(pairs), 15)
        self.assertEqual((pairs[(1, 2)]["same_day"], pairs[(1, 2)]["cases_differing"]), (True, 0))
        self.assertEqual((pairs[(2, 3)]["same_day"], pairs[(2, 3)]["cases_differing"]), (False, 1))
        self.assertEqual(pairs[(3, 4)]["cases_differing"], 0)

    def test_run_day_is_the_rome_date_of_the_first_call(self):
        # Run 2 starts at 22:00 UTC on 12 October: midnight on the 13th in Rome.
        result = analyse({"p001": runs_of("sssss")}, start_hours=[7, 22, 31, 37, 55, 61])
        self.assertEqual(result["8.4"]["run_day"]["2"], "2026-10-13")


class IntervalTest(unittest.TestCase):
    def test_closed_forms(self):
        for n in (1, 10, 30, 533):
            lo, hi = analyze.clopper_pearson(0, n)
            self.assertEqual(lo, 0.0)
            self.assertAlmostEqual(hi, 1 - 0.025 ** (1 / n), 9)
            lo, hi = analyze.clopper_pearson(n, n)
            self.assertAlmostEqual(lo, 0.025 ** (1 / n), 9)
            self.assertEqual(hi, 1.0)
            if n > 1:
                lo, _ = analyze.clopper_pearson(1, n)
                self.assertAlmostEqual(lo, 1 - 0.975 ** (1 / n), 9)
                _, hi = analyze.clopper_pearson(n - 1, n)
                self.assertAlmostEqual(hi, 0.975 ** (1 / n), 9)

    def test_known_values(self):
        lo, hi = analyze.clopper_pearson(5, 10)
        self.assertAlmostEqual(lo, 0.187086, 6)
        self.assertAlmostEqual(hi, 0.812914, 6)

    def test_symmetry(self):
        for x, n in ((3, 17), (104, 144), (40, 533)):
            lo, hi = analyze.clopper_pearson(x, n)
            lo2, hi2 = analyze.clopper_pearson(n - x, n)
            self.assertAlmostEqual(lo, 1 - hi2, 9)
            self.assertAlmostEqual(hi, 1 - lo2, 9)


class PermutationTest(unittest.TestCase):
    CASES = {
        "p001": runs_of("sssss"),
        "p002": runs_of("sssss", "sssss", "sssss", "ccccc", "ccccc", "ccccc"),
        "p003": runs_of("sscss", "sssss", "csssc", "sssss", "sssss", "sssss"),
        "p004": runs_of("sAsss", "ccccc", "sscss", "sscuc", "ccccc", "sssss"),
        "p005": runs_of("ccccc", "ccccc", "ccccc", "ccccc", "ccccc", "cccuc"),
    }

    def cases(self) -> list[analyze.Case]:
        return load(matrix(self.CASES))[0]

    def test_same_seed_same_distribution(self):
        first = analyze.permutation_test(self.cases(), seed=2606, permutations=300)
        self.assertEqual(first, analyze.permutation_test(self.cases(), seed=2606, permutations=300))
        other = analyze.permutation_test(self.cases(), seed=1, permutations=300)
        self.assertNotEqual(first["reference"], other["reference"])

    def test_observed_reference_and_p(self):
        result = analyze.permutation_test(self.cases(), permutations=300)
        self.assertEqual(result["observed"], 2)  # p002, p004; p003 is skip in every run
        self.assertEqual(sum(result["reference"].values()), 300)
        self.assertEqual(result["seed"], 2606)
        at_least = sum(v for k, v in result["reference"].items() if int(k) >= 2)
        self.assertEqual(result["p_one_sided"], round((at_least + 1) / 301, 6))

    def test_errors_keep_their_place(self):
        slots = [["skip", None, "skip", "comment", "skip"]] + [["skip"] * 5] * 5
        runs = analyze.permuted_runs(slots, analyze.random.Random(3))
        self.assertEqual([len(r) for r in runs], [4, 5, 5, 5, 5, 5])
        self.assertEqual(sorted(v for r in runs for v in r), ["comment"] + ["skip"] * 28)


def write_with_manifest(directory: Path, text: str) -> Path:
    path = directory / "matrix.csv"
    path.write_text(text)
    (directory / "MANIFEST.txt").write_text(f"{'0' * 64}  run-01.jsonl\n"
                                            f"{make_matrix.sha256(path)}  matrix.csv\n")
    return path


class MainTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.matrix = write_with_manifest(self.dir, matrix(PermutationTest.CASES))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def refused(self) -> str:
        with self.assertRaises(SystemExit) as stopped:
            analyze.main(["--matrix", str(self.matrix), "--out", str(self.dir / "out")])
        self.assertFalse((self.dir / "out").exists())
        return str(stopped.exception.code)

    def test_missing_manifest_stops(self):
        (self.dir / "MANIFEST.txt").unlink()
        self.assertIn("MANIFEST.txt is missing", self.refused())

    def test_matrix_other_than_the_manifest_stops(self):
        with self.matrix.open("a") as handle:
            handle.write(self.matrix.read_text().splitlines()[1] + "\n")
        self.assertIn("MANIFEST.txt says", self.refused())

    def test_manifest_without_the_matrix_stops(self):
        (self.dir / "MANIFEST.txt").write_text(f"{'0' * 64}  run-01.jsonl\n")
        self.assertIn("does not state one sha256 for matrix.csv", self.refused())

    def test_zero_count_is_an_upper_bound_in_every_table(self):
        self.assertEqual(analyze.pct(analyze.proportion(0, 30)), "0 / 30 (≤ 11.6%)")
        analyze.main(["--matrix", str(self.matrix), "--out", str(self.dir / "out")])
        tables = (self.dir / "out" / "tables.md").read_text()
        for section in ("## 8.1", "## 8.7"):
            body = tables.split(section, 1)[1].split("\n## ", 1)[0]
            self.assertIn("0 / 5 (≤ ", body)

    def test_output_is_deterministic_and_labelled_in_english(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            write_with_manifest(tmp, matrix(PermutationTest.CASES))
            outputs = []
            for name in ("a", "b"):
                analyze.main(["--matrix", str(tmp / "matrix.csv"), "--out", str(tmp / name)])
                outputs.append([(tmp / name / f).read_bytes() for f in ("analysis.json", "tables.md")])
        self.assertEqual(outputs[0], outputs[1])
        tables = outputs[0][1].decode()
        for label in ("| rare flips |", "| coin-like |", "| below threshold |"):
            self.assertIn(label, tables)
        self.assertEqual(json.loads(outputs[0][0])["threshold"]["min_valid"], 25)


if __name__ == "__main__":
    unittest.main()

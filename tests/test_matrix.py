"""Offline tests for scripts/make_matrix.py, on synthetic raw files.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import make_matrix  # noqa: E402
import run  # noqa: E402

# Planted in every free-text field and unpublished header; must never reach the matrix.
SECRET = "SENTINEL-free-text"
CASES = 3


def case_record(n: int) -> dict:
    return {"case_id": f"c{n:03d}", "stratum": "proposed" if n == 1 else "skipped",
            "title": f"{SECRET} title", "subreddit": SECRET, "flair": "",
            "text": f"{SECRET} body", "commented_titles": SECRET,
            "judged_day": f"2026-09-{17 + n:02d}",
            "mark": "commented" if n == 1 else "deferred",
            "expected": "comment" if n == 1 else None, "text_empty": n == 3}


def raw_line(case: dict, run_index: int, sample: int) -> dict:
    error = case["case_id"] == "c002" and sample == 5
    refused = case["case_id"] == "c001" and sample == 1
    return {
        "case_id": case["case_id"], "stratum": case["stratum"], "run": run_index,
        "seed": run.SEEDS[run_index], "sample": sample,
        "started_at": f"2026-10-0{run_index}T07:00:0{sample}.123+00:00",
        "latency_ms": 1234.5, "request_id": "req_011Abc",
        "response_headers": {
            "request-id": "req_011Abc",
            "traceresponse": "00-" + "a" * 32 + "-" + "b" * 16 + "-01",
            "cf-ray": SECRET, "date": SECRET,
            "anthropic-organization-id": SECRET, "anthropic-workspace-id": SECRET,
        },
        "attempts": 2 if error else 1, "attempt_statuses": [529, 200] if error else [200],
        "hook_failed": False, "model": None if error else "claude-sonnet-5",
        "stop_reason": None if error else "end_turn",
        "raw_text": None if error else f'{{"why": "{SECRET}"}}',
        "verdict_raw": None if error else ("comment+tool" if refused else "skip"),
        "verdict_settled": None if error else ("comment" if refused else "skip"),
        "why": None if error else SECRET, "angle": None if error else SECRET,
        "tool_refused": None if error else (f"{SECRET} refused" if refused else ""),
        "usage": None if error else {
            "input_tokens": 987654, "output_tokens": 300, "service_tier": "standard",
            "inference_geo": "global", "output_tokens_details": {"thinking_tokens": 120}},
        "thinking_tokens": None if error else 120, "cost_usd": None if error else 0.0072,
        "error_type": "api" if error else None,
        "error": f"APIStatusError: {SECRET}" if error else None,
    }


class MatrixTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.raw, self.out, self.ids = root / "raw", root / "results", root / "public_ids.json"
        self.raw.mkdir()
        self.cases_path = root / "cases.jsonl"
        self.cases = [case_record(n) for n in range(1, CASES + 1)]
        self.cases_path.write_text("".join(json.dumps(c) + "\n" for c in self.cases))
        self.lines = {i: [raw_line(c, i, s) for c in self.cases for s in range(1, 6)]
                      for i in run.RUNS}
        self.write_runs()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_runs(self) -> None:
        for i, lines in self.lines.items():
            (self.raw / f"run-{i:02d}.jsonl").write_text(
                "".join(json.dumps(line) + "\n" for line in lines))

    def make(self, *extra: str) -> list[dict]:
        with contextlib.redirect_stdout(io.StringIO()):
            make_matrix.main(["--raw", str(self.raw), "--cases", str(self.cases_path),
                              "--ids", str(self.ids), "--out", str(self.out), *extra])
        with (self.out / "matrix.csv").open(newline="") as handle:
            return list(csv.DictReader(handle))

    def maps(self) -> dict:
        return json.loads(self.ids.read_text())

    def refused(self, *extra: str) -> str:
        with self.assertRaises(SystemExit) as stopped:
            self.make(*extra)
        self.assertFalse((self.out / "matrix.csv").exists())
        return str(stopped.exception.code)

    def test_no_free_text_reaches_the_matrix(self):
        rows = self.make()
        text = (self.out / "matrix.csv").read_text()
        self.assertNotIn("SENTINEL", text)
        self.assertNotIn("987654", text)  # input tokens
        self.assertNotIn("0.0072", text)  # cost
        self.assertEqual(list(rows[0]), list(make_matrix.COLUMNS))
        for name in ("input_tokens", "cost_usd", "cf_ray", "date", "case_id", "judged_day"):
            self.assertNotIn(name, make_matrix.COLUMNS)
        for row in rows:
            for name, value in row.items():
                self.assertRegex(value, "^(?:" + make_matrix.COLUMNS[name] + ")$", name)

    def test_original_ids_and_days_do_not_reach_the_matrix(self):
        text = self.make() and (self.out / "matrix.csv").read_text()
        for case in self.cases:
            self.assertNotIn(case["case_id"], text)
            self.assertNotIn(case["judged_day"][5:], text)

    def test_values_are_carried_over_under_public_ids(self):
        rows = self.make()
        maps = self.maps()
        self.assertEqual(sorted(maps["cases"].values()), ["p001", "p002", "p003"])
        self.assertEqual(sorted(maps["days"].values()), ["A", "B", "C"])
        self.assertEqual(len(rows), 6 * CASES * 5)
        first = next(r for r in rows if r["public_id"] == maps["cases"]["c001"] and r["sample"] == "1")
        self.assertEqual((first["run"], first["seed"]), ("1", "101"))
        self.assertEqual((first["verdict_raw"], first["verdict_settled"], first["tool_refused"]),
                         ("comment+tool", "comment", "true"))
        self.assertEqual((first["label_status"], first["expected"], first["day_label"]),
                         ("labelled", "comment", maps["days"]["2026-09-18"]))
        self.assertEqual((first["output_tokens"], first["thinking_tokens"]), ("300", "120"))
        error = next(r for r in rows if r["error_type"])
        self.assertEqual((error["public_id"], error["sample"], error["attempt_statuses"],
                          error["verdict_raw"], error["tool_refused"]),
                         (maps["cases"]["c002"], "5", "529;200", "", ""))
        third = next(r for r in rows if r["public_id"] == maps["cases"]["c003"])
        self.assertEqual((third["label_status"], third["expected"], third["text_empty"]),
                         ("deferred", "", "true"))

    def test_rows_are_sorted_by_run_public_id_and_sample(self):
        rows = self.make()
        keys = [(int(r["run"]), r["public_id"], int(r["sample"])) for r in rows]
        self.assertEqual(keys, sorted(keys))

    def test_public_ids_are_reused(self):
        self.make()
        first = (self.out / "matrix.csv").read_bytes()
        maps = self.ids.read_bytes()
        self.make()
        self.assertEqual(self.ids.read_bytes(), maps)
        self.assertEqual((self.out / "matrix.csv").read_bytes(), first)

    def test_public_ids_for_other_cases_stop(self):
        self.make()
        maps = self.maps()
        maps["cases"]["c999"] = maps["cases"].pop("c003")
        self.ids.write_text(json.dumps(maps))
        (self.out / "matrix.csv").unlink()
        self.assertIn("are not those of the case file", self.refused())

    def test_public_ids_not_one_to_one_stop(self):
        self.make()
        maps = self.maps()
        maps["days"]["2026-09-18"] = maps["days"]["2026-09-19"]
        self.ids.write_text(json.dumps(maps))
        (self.out / "matrix.csv").unlink()
        self.assertIn("not one to one", self.refused())

    def test_a_refused_run_creates_no_public_ids(self):
        self.lines[2].pop()
        self.write_runs()
        self.refused()
        self.assertFalse(self.ids.exists())

    def test_manifest_has_the_six_raw_files_and_the_matrix(self):
        self.make()
        lines = (self.out / "MANIFEST.txt").read_text().splitlines()
        names = [line.split("  ")[1] for line in lines]
        self.assertEqual(names, [f"run-{i:02d}.jsonl" for i in run.RUNS] + ["matrix.csv"])
        self.assertEqual(lines[-1].split("  ")[0], make_matrix.sha256(self.out / "matrix.csv"))

    def test_missing_run_stops(self):
        (self.raw / "run-06.jsonl").unlink()
        self.assertIn("missing run-06.jsonl", self.refused())

    def test_accept_incomplete_takes_complete_runs_1_to_k(self):
        (self.raw / "run-05.jsonl").unlink()
        (self.raw / "run-06.jsonl").unlink()
        rows = self.make("--accept-incomplete")
        self.assertEqual({r["run"] for r in rows}, {"1", "2", "3", "4"})
        manifest = (self.out / "MANIFEST.txt").read_text()
        self.assertIn("incomplete: 4 of 6 runs, accepted with --accept-incomplete", manifest)

    def test_accept_incomplete_refuses_a_gap(self):
        (self.raw / "run-03.jsonl").unlink()
        self.assertIn("needs runs 1 to k", self.refused("--accept-incomplete"))

    def test_accept_incomplete_refuses_a_partial_run(self):
        self.lines[5].pop()
        self.write_runs()
        (self.raw / "run-06.jsonl").unlink()
        self.assertIn("missing", self.refused("--accept-incomplete"))

    def test_missing_line_stops(self):
        self.lines[2].pop()
        self.write_runs()
        self.assertIn("missing", self.refused())

    def test_duplicate_line_stops(self):
        self.lines[3].append(self.lines[3][0])
        self.write_runs()
        self.assertIn("duplicate", self.refused())

    def test_seed_other_than_the_run_stops(self):
        self.lines[4][0]["seed"] = 101
        self.write_runs()
        self.assertIn("not run 4 seed 104", self.refused())

    def test_unknown_case_stops(self):
        self.lines[1][0]["case_id"] = "c999"
        self.write_runs()
        self.assertIn("not in the case file", self.refused())

    def test_free_text_in_a_published_field_stops(self):
        self.lines[1][0]["model"] = SECRET
        self.write_runs()
        self.assertIn("model does not match", self.refused())


class IgnoredTest(unittest.TestCase):
    def test_private_and_unpublished_files_are_ignored_by_git(self):
        for path in ("corpus/public_ids.json", "results/matrix.csv", "results/analysis.json",
                     "results/tables.md", "results/MANIFEST.txt"):
            ignored = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", path])
            self.assertEqual(ignored.returncode, 0, path)


if __name__ == "__main__":
    unittest.main()

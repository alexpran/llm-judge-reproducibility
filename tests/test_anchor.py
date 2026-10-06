"""Offline tests for scripts/anchor_smoke.py. A synthetic harness zip with
invented items, prompt and pattern, a fake client, no network.

The one test that reads the real harness looks for it in ANCHOR_HARNESS or in
~/scout-corpora/tamba-harness-2026-10-06, and is skipped when it is absent.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import anchor_smoke  # noqa: E402
import run  # noqa: E402
from test_run import FakeClient, http, reply  # noqa: E402

SOURCE = '''
import re
ITEMS = [
{items}
]
INSPECT_DEFAULT_INSTRUCTIONS = (
    "Finish with 'MARK: $X' where X is A or B."
)
AISEV_TEMPLATE = (
    "Q={{q}} / S={{s}} / C={{c}} / {{instructions}}"
)
GRADE_PATTERN = r"(?is).*MARK\\s*:\\s*([AB])"
def _prompt(item):
    raise SystemExit("the harness must not be executed")
'''

FIELDS = ("case_id", "stratum", "run", "seed", "sample", "started_at", "latency_ms",
          "request_id", "response_headers", "attempts", "attempt_statuses",
          "hook_failed", "model", "stop_reason", "raw_text", "verdict_raw",
          "verdict_settled", "why", "angle", "tool_refused", "usage",
          "thinking_tokens", "cost_usd", "error_type", "error", "grade")


def synthetic_zip(folder: Path, count: int = 7) -> Path:
    items = ",\n".join(
        f'    {{"q": "question {n}", "c": "criterion {n}", "s": "submission {n}"}}'
        for n in range(1, count + 1))
    path = folder / "harness.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("harness-abc/src/repro_v11_extended.py",
                         SOURCE.format(items=items))
        archive.writestr("harness-abc/README.md", "synthetic")
    return path


class AnchorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.zip = synthetic_zip(self.folder)
        self.out = self.folder / "raw" / "anchor" / "anchor.jsonl"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def go(self, client, *extra: str) -> str:
        printed = io.StringIO()
        with redirect_stdout(printed):
            anchor_smoke.main([str(self.folder), *extra], make_client=lambda: client,
                              out=self.out, expected_sha256=None)
        return printed.getvalue()

    def rows(self) -> list[dict]:
        return [json.loads(line) for line in self.out.read_text().splitlines()]

    def test_seven_lines_with_every_field_and_the_grade(self):
        client = FakeClient(lambda n: reply("reasoning... MARK: a" if n % 2 else "MARK: B"))
        self.go(client)
        rows = self.rows()
        self.assertEqual([r["case_id"] for r in rows], [f"item{n}" for n in range(1, 8)])
        for row in rows:
            self.assertEqual(set(row), set(FIELDS))
            self.assertIsNone(row["error_type"])
            self.assertEqual((row["run"], row["seed"], row["sample"]), (0, None, 1))
            self.assertEqual((row["attempts"], row["attempt_statuses"]), (1, [200]))
            for scout_field in ("verdict_raw", "verdict_settled", "why", "angle",
                                "tool_refused"):
                self.assertIsNone(row[scout_field])
        self.assertEqual([r["grade"] for r in rows], ["A", "B", "A", "B", "A", "B", "A"])

    def test_requests_are_the_grader_prompt_with_section_2_settings(self):
        client = FakeClient(lambda n: reply("MARK: A"))
        self.go(client)
        self.assertEqual(len(client.calls), 7)
        first = client.calls[0]
        self.assertEqual(set(first), {"model", "max_tokens", "messages", "thinking"})
        self.assertEqual(first["model"], "claude-sonnet-5")
        self.assertEqual(first["max_tokens"], 2000)
        self.assertEqual(first["thinking"], {"type": "adaptive"})
        self.assertEqual(first["messages"], [{"role": "user", "content":
            "Q=question 1 / S=submission 1 / C=criterion 1 / "
            "Finish with 'MARK: $X' where X is A or B."}])

    def test_reply_without_a_grade_is_a_parse_error(self):
        self.go(FakeClient(lambda n: reply("no mark here")))
        row = self.rows()[0]
        self.assertEqual(row["error_type"], "parse")
        self.assertIsNone(row["grade"])
        self.assertEqual(row["raw_text"], "no mark here")

    def test_cut_at_the_cap_without_a_grade_is_max_tokens(self):
        self.go(FakeClient(lambda n: reply("thinking out lo", stop_reason="max_tokens")))
        self.assertEqual(self.rows()[0]["error_type"], "max_tokens")

    def test_api_error_without_a_response(self):
        def behaviour(n):
            raise RuntimeError("connection refused")
        self.go(FakeClient(behaviour, responses=lambda n: []))
        rows = self.rows()
        self.assertEqual(len(rows), 7)
        self.assertEqual({r["error_type"] for r in rows}, {"api"})
        self.assertEqual({r["attempts"] for r in rows}, {0})

    def test_log_records_sdk_repo_environment_and_zip(self):
        self.go(FakeClient(lambda n: reply("MARK: A")))
        log = self.out.with_suffix(".log").read_text()
        self.assertIn("sdk=anthropic injected", log)
        self.assertIn("repo=", log)
        self.assertIn(run.environment(), log)
        self.assertIn(f"harness_zip_sha256={run.sha256(self.zip)}", log)

    def test_existing_output_is_not_overwritten(self):
        self.out.parent.mkdir(parents=True)
        self.out.write_text("{}\n")
        with self.assertRaises(SystemExit):
            self.go(FakeClient())
        self.assertEqual(self.out.read_text(), "{}\n")

    def test_dry_run_needs_no_client_and_is_stable(self):
        first = self.go(None, "--dry-run")
        self.assertIn("requests  7 (1 per item)", first)
        self.assertEqual(first, self.go(None, "--dry-run"))
        self.assertFalse(self.out.exists())

    def test_wrong_zip_hash_refuses(self):
        with self.assertRaises(run.Stop):
            anchor_smoke.load_harness(self.zip, "0" * 64)

    def test_six_items_refuse(self):
        other = self.folder / "six"
        other.mkdir()
        with self.assertRaises(run.Stop):
            anchor_smoke.load_harness(synthetic_zip(other, count=6), None)


REAL_HARNESS = Path(os.environ.get(
    "ANCHOR_HARNESS", Path.home() / "scout-corpora" / "tamba-harness-2026-10-06"))


@unittest.skipUnless(REAL_HARNESS.exists(), "the harness copy is not on this machine")
class NotInRepoTest(unittest.TestCase):
    def test_no_harness_text_in_the_repository(self):
        harness = anchor_smoke.load_harness(REAL_HARNESS)
        texts = [harness.instructions, harness.template, harness.pattern]
        texts += [value for item in harness.items for value in item.values()]
        files = subprocess.run(
            ["git", "-C", str(run.REPO), "ls-files", "--cached", "--others",
             "--exclude-standard"], check=True, capture_output=True, text=True,
        ).stdout.splitlines()
        self.assertTrue(files)
        found = []
        for name in files:
            path = run.REPO / name
            if not path.is_file():
                continue
            content = path.read_bytes().decode("utf-8", errors="replace")
            found += [name for text in texts if text in content]
        self.assertEqual(found, [], "harness text found in tracked or unignored files")


if __name__ == "__main__":
    unittest.main()

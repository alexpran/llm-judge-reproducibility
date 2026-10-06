"""Offline tests for scripts/run.py. A fake client, synthetic cases, no network.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import judge  # noqa: E402
import run  # noqa: E402

PROMPTS = judge.load_prompts()


def make_case(n: int, stratum: str = "skipped", text: str = "Some body text.") -> dict:
    return {
        "case_id": f"c{n:03d}",
        "stratum": stratum,
        "title": f"Synthetic thread {n}",
        "subreddit": "test",
        "flair": "",
        "text": text,
        "commented_titles": "",
        "judged_day": "2026-01-01",
        "mark": "deferred",
        "expected": None,
        "text_empty": text == "",
    }


def reply(text: str, stop_reason: str = "end_turn", thinking: int = 40) -> SimpleNamespace:
    message = SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking="..."),
                 SimpleNamespace(type="text", text=text)],
        model="claude-sonnet-5",
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200,
                              cache_read_input_tokens=0,
                              cache_creation_input_tokens=0,
                              output_tokens_details=SimpleNamespace(
                                  thinking_tokens=thinking)),
    )
    message._request_id = "req_test"
    return message


def answer(verdict: str = "skip", angle: str = "") -> str:
    return json.dumps({"verdict": verdict, "why": "because", "angle": angle})


class APIError(Exception):
    request_id = "req_failed"


def http(status: int, **headers: str) -> SimpleNamespace:
    """An HTTP response as the response hook sees it: status and headers."""
    return SimpleNamespace(status_code=status, headers={"request-id": "req_test", **headers})


class FakeClient:
    """Replies from a function of the call number (1-based). The function may
    return a reply or raise. Before that, the HTTP responses given by
    `responses` (default: one 200) go through the response hooks, as the
    SDK's HTTP client would send them."""

    def __init__(self, behaviour=None, responses=None) -> None:
        self.calls: list[dict] = []
        self.behaviour = behaviour or (lambda n: reply(answer()))
        self.responses = responses or (lambda n: [http(200)])
        self.messages = self
        self._client = SimpleNamespace(event_hooks={"request": [], "response": []})

    def create(self, **kwargs):
        self.calls.append(kwargs)
        n = len(self.calls)
        for response in self.responses(n):
            for hook in self._client.event_hooks["response"]:
                hook(response)
        return self.behaviour(n)


class RunTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "raw" / "run-01.jsonl"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def go(self, cases, client, *, seed=7, samples=5, max_usd=None):
        return run.run(cases, run_index=1, seed=seed, samples=samples, out=self.out,
                       client=client, prompts=PROMPTS, max_usd=max_usd)

    def rows(self) -> list[dict]:
        return [json.loads(line) for line in self.out.read_text().splitlines()]

    def test_exception_on_third_sample_keeps_the_other_four(self):
        def behaviour(n):
            if n == 3:
                raise APIError("overloaded")
            return reply(answer())
        self.go([make_case(1)], FakeClient(behaviour))
        rows = self.rows()
        self.assertEqual([r["sample"] for r in rows], [1, 2, 3, 4, 5])
        self.assertEqual([r["error"] is None for r in rows], [True, True, False, True, True])
        self.assertEqual(sum(r["verdict_raw"] == "skip" for r in rows), 4)
        self.assertEqual([r["error_type"] for r in rows], [None, None, "api", None, None])
        self.assertIn("APIError", rows[2]["error"])
        self.assertEqual(rows[2]["request_id"], "req_failed")
        self.assertIsNone(rows[2]["verdict_raw"])

    def test_invalid_reply_is_an_error_line_with_raw_text(self):
        bad = 'I think {"verdict": "maybe", "why": "x", "angle": ""}'
        client = FakeClient(lambda n: reply(bad if n == 2 else answer()))
        self.go([make_case(1)], client, samples=3)
        rows = self.rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["error_type"], "parse")
        self.assertIsNone(rows[0]["error_type"])
        self.assertEqual(rows[1]["raw_text"], bad)
        self.assertEqual(rows[1]["request_id"], "req_test")
        self.assertIsNone(rows[1]["verdict_raw"])
        self.assertIsNone(rows[0]["error"])

    def test_refusal_is_an_error_not_a_verdict(self):
        client = FakeClient(lambda n: reply(answer(), stop_reason="refusal"))
        self.go([make_case(1)], client, samples=1)
        row = self.rows()[0]
        self.assertEqual(row["error_type"], "refusal")
        self.assertIsNone(row["verdict_raw"])

    def test_cut_at_max_tokens_without_verdict_is_max_tokens_not_parse(self):
        cut = '{"verdict": "comment", "why": "the thread asks ab'
        client = FakeClient(lambda n: reply(cut, stop_reason="max_tokens"))
        self.go([make_case(1)], client, samples=1)
        row = self.rows()[0]
        self.assertEqual(row["error_type"], "max_tokens")
        self.assertEqual(row["raw_text"], cut)
        self.assertIsNone(row["verdict_raw"])

    def test_empty_reply_at_max_tokens_is_max_tokens(self):
        client = FakeClient(lambda n: reply("", stop_reason="max_tokens"))
        self.go([make_case(1)], client, samples=1)
        self.assertEqual(self.rows()[0]["error_type"], "max_tokens")

    def test_readable_verdict_at_max_tokens_is_a_verdict(self):
        client = FakeClient(lambda n: reply(answer("upvote"), stop_reason="max_tokens"))
        self.go([make_case(1)], client, samples=1)
        row = self.rows()[0]
        self.assertIsNone(row["error_type"])
        self.assertEqual(row["verdict_raw"], "upvote")

    def test_resume_neither_duplicates_nor_loses_lines(self):
        cases = [make_case(n) for n in range(1, 5)]

        def interrupt(n):
            if n == 8:
                raise KeyboardInterrupt
            return reply(answer())
        with self.assertRaises(KeyboardInterrupt):
            self.go(cases, FakeClient(interrupt))
        self.assertEqual(len(self.rows()), 7)
        second = FakeClient()
        result = self.go(cases, second)
        rows = self.rows()
        self.assertEqual(len(second.calls), 20 - 7)
        self.assertEqual(result["previous"], 7)
        self.assertEqual(len(rows), 20)
        pairs = [(r["case_id"], r["sample"]) for r in rows]
        self.assertEqual(len(set(pairs)), 20)
        expected = [(c, s) for c in run.run_order([c["case_id"] for c in cases], 7)
                    for s in range(1, 6)]
        self.assertEqual(pairs, expected)
        log = self.out.with_suffix(".log").read_text()
        self.assertIn("interrupted: KeyboardInterrupt", log)
        self.assertIn("resume run=1 seed=7: 7 of 20 lines present", log)

    def test_resume_refuses_another_seed(self):
        self.go([make_case(1)], FakeClient(), samples=1)
        with self.assertRaises(run.Stop):
            self.go([make_case(1)], FakeClient(), seed=8, samples=1)

    def test_same_seed_same_order_different_seed_different_order(self):
        ids = [f"c{n:03d}" for n in range(1, 534)]
        self.assertEqual(run.run_order(ids, 11), run.run_order(list(reversed(ids)), 11))
        self.assertNotEqual(run.run_order(ids, 11), run.run_order(ids, 12))
        self.assertEqual(sorted(run.run_order(ids, 11)), ids)

    def test_raw_comment_tool_is_kept_when_settle_tool_downgrades(self):
        unquoted = answer("comment+tool", angle="asks which tool to use -> digline")
        self.go([make_case(1)], FakeClient(lambda n: reply(unquoted)), samples=1)
        row = self.rows()[0]
        self.assertEqual(row["verdict_raw"], "comment+tool")
        self.assertEqual(row["verdict_settled"], "comment")
        self.assertTrue(row["tool_refused"])

    def test_raw_comment_tool_kept_when_quote_is_in_post(self):
        text = "Which regression testing tool do you all use for prompts?"
        quoted = answer("comment+tool", angle=f'"{text}" -> digline')
        self.go([make_case(1, text=text)], FakeClient(lambda n: reply(quoted)), samples=1)
        row = self.rows()[0]
        self.assertEqual((row["verdict_raw"], row["verdict_settled"]),
                         ("comment+tool", "comment+tool"))

    def test_line_records_usage_thinking_and_identity(self):
        self.go([make_case(1)], FakeClient(), samples=1)
        row = self.rows()[0]
        for key in ("case_id", "stratum", "run", "sample", "started_at", "latency_ms",
                    "request_id", "model", "stop_reason", "raw_text", "verdict_raw",
                    "verdict_settled", "usage", "thinking_tokens", "cost_usd", "seed",
                    "error_type", "error", "response_headers", "attempts",
                    "attempt_statuses", "hook_failed"):
            self.assertIn(key, row)
        self.assertEqual(row["thinking_tokens"], 40)
        self.assertEqual(row["usage"]["output_tokens_details"]["thinking_tokens"], 40)
        self.assertAlmostEqual(row["cost_usd"], (1000 * 3 + 200 * 15) / 1e6)

    def test_every_line_has_the_response_fields(self):
        self.go([make_case(1), make_case(2)], FakeClient(), samples=2)
        for row in self.rows():
            self.assertEqual(row["response_headers"], {"request-id": "req_test"})
            self.assertEqual((row["attempts"], row["attempt_statuses"]), (1, [200]))
            self.assertIs(row["hook_failed"], False)

    def test_retry_keeps_the_headers_of_the_last_response(self):
        client = FakeClient(responses=lambda n: [http(529, **{"request-id": "req_first"}),
                                                 http(200, **{"request-id": "req_last"})])
        self.go([make_case(1)], client, samples=1)
        row = self.rows()[0]
        self.assertEqual(row["response_headers"], {"request-id": "req_last"})
        self.assertEqual((row["attempts"], row["attempt_statuses"]), (2, [529, 200]))
        self.assertIsNone(row["error_type"])

    def test_api_error_with_a_response_keeps_its_headers(self):
        def behaviour(n):
            raise APIError("overloaded")
        client = FakeClient(behaviour, responses=lambda n: [http(529), http(529), http(529)])
        self.go([make_case(1)], client, samples=1)
        row = self.rows()[0]
        self.assertEqual(row["error_type"], "api")
        self.assertEqual(row["response_headers"], {"request-id": "req_test"})
        self.assertEqual((row["attempts"], row["attempt_statuses"]), (3, [529, 529, 529]))

    def test_api_error_without_a_response_has_null_headers(self):
        def behaviour(n):
            raise APIError("connection refused")
        self.go([make_case(1)], FakeClient(behaviour, responses=lambda n: []), samples=1)
        row = self.rows()[0]
        self.assertEqual(row["error_type"], "api")
        self.assertIsNone(row["response_headers"])
        self.assertEqual((row["attempts"], row["attempt_statuses"]), (0, []))
        self.assertIs(row["hook_failed"], False)

    def test_counts_do_not_leak_between_calls(self):
        client = FakeClient(responses=lambda n: [http(529), http(200)] if n == 1 else [http(200)])
        self.go([make_case(1)], client, samples=2)
        self.assertEqual([r["attempt_statuses"] for r in self.rows()], [[529, 200], [200]])

    def test_a_failing_hook_is_logged_and_the_call_goes_on(self):
        class BadHeaders:
            def items(self):
                raise ValueError("unreadable")
        broken = SimpleNamespace(status_code=200, headers=BadHeaders())
        client = FakeClient(responses=lambda n: [http(529), broken] if n == 1 else [http(200)])
        self.go([make_case(1)], client, samples=2)
        first, second = self.rows()
        self.assertEqual(first["verdict_raw"], "skip")
        self.assertIs(first["hook_failed"], True)
        self.assertEqual((first["attempts"], first["attempt_statuses"]), (1, [529]))
        self.assertIs(second["hook_failed"], False)
        self.assertEqual(second["attempts"], 1)
        self.assertIn("response hook failed on c001 sample 1: ValueError: unreadable",
                      self.out.with_suffix(".log").read_text())

    def test_the_hook_is_removed_after_the_run(self):
        client = FakeClient()
        self.go([make_case(1)], client, samples=1)
        self.assertEqual(client._client.event_hooks["response"], [])

    def test_a_client_without_response_hooks_refuses_to_start(self):
        client = FakeClient()
        del client._client
        with self.assertRaises(run.Stop):
            self.go([make_case(1)], client, samples=1)
        self.assertFalse(self.out.exists())

    def test_max_usd_stops_before_the_call(self):
        client = FakeClient()  # each call costs 0.006
        result = self.go([make_case(1)], client, max_usd=0.015)
        self.assertEqual(result["status"], "budget")
        self.assertEqual(len(client.calls), 3)
        self.assertIn("--max-usd", self.out.with_suffix(".log").read_text())

    def test_requests_carry_no_sampling_parameters(self):
        client = FakeClient()
        self.go([make_case(1)], client, samples=1)
        sent = client.calls[0]
        self.assertEqual(set(sent), {"model", "max_tokens", "messages", "system",
                                     "output_config", "thinking"})
        self.assertEqual(sent["thinking"], {"type": "adaptive"})

    def test_inputs_are_refused_when_a_hash_differs_from_the_protocol(self):
        tmp = Path(self.tmp.name)
        cases = tmp / "cases.jsonl"
        cases.write_text(json.dumps(make_case(1)) + "\n")
        prompts = Path(judge.PROMPTS_DIR)
        good = (f"`JUDGE.md`, sha256 `{run.sha256(prompts / 'JUDGE.md')}`\n"
                f"`THREAD.md`, sha256 `{run.sha256(prompts / 'THREAD.md')}`\n"
                f"sha256 of the case file: `{run.sha256(cases)}`.\n")
        protocol = tmp / "PROTOCOL.md"
        protocol.write_text(good)
        run.verify_inputs(cases, prompts, protocol)
        cases.write_text(json.dumps(make_case(2)) + "\n")
        with self.assertRaises(run.Stop):
            run.verify_inputs(cases, prompts, protocol)
        cases.write_text(json.dumps(make_case(1)) + "\n")
        run.verify_inputs(cases, prompts, protocol)
        protocol.write_text(good.replace(run.sha256(prompts / "JUDGE.md"), "`TBD`"))
        with self.assertRaises(run.Stop):
            run.verify_inputs(cases, prompts, protocol)

    def test_raw_lines_carry_only_case_ids(self):
        self.go([make_case(1)], FakeClient(), samples=1)
        self.assertNotIn("Synthetic thread", self.out.read_text())


try:
    import anthropic
    import httpx2
except ImportError:  # the tests above need neither
    anthropic = None


@unittest.skipIf(anthropic is None, "anthropic is not installed")
class SdkHookTest(unittest.TestCase):
    """The real pinned SDK, with its transport replaced by a function: no
    network. The hook reaches the client the SDK builds, and adding it does not
    change what is sent."""

    def setUp(self) -> None:
        self.sent: list[tuple] = []
        self.statuses: list[int] = []
        sent, statuses = self.sent, self.statuses

        def transport(_self, request):
            request.read()
            sent.append((request.method, str(request.url), dict(request.headers),
                         request.content))
            status = statuses.pop(0) if statuses else 200
            body = reply_json() if status == 200 else {"type": "error", "error": {
                "type": "overloaded_error", "message": "Overloaded"}}
            return httpx2.Response(status, json=body, request=request, headers={
                "request-id": f"req_{len(sent)}", "retry-after-ms": "1"})

        patch = mock.patch.object(httpx2.HTTPTransport, "handle_request", transport)
        patch.start()
        self.addCleanup(patch.stop)
        self.request = judge.build_request(run.case_vars(make_case(1)), PROMPTS)

    def test_sdk_client_has_event_hooks(self):
        client = anthropic.Anthropic(api_key="test")
        self.assertIsInstance(client._client.event_hooks["response"], list)
        self.assertIsInstance(run.hooks_of(client), list)

    def test_the_hook_does_not_change_the_request(self):
        volatile = {"x-stainless-retry-count"}

        def wire(entry):
            method, url, headers, body = entry
            return method, url, {k: v for k, v in headers.items() if k not in volatile}, body

        anthropic.Anthropic(api_key="test").messages.create(**self.request)
        hooked = anthropic.Anthropic(api_key="test")
        recorder = run.ResponseRecorder()
        run.hooks_of(hooked).append(recorder)
        run.call_once(hooked, self.request, run.case_vars(make_case(1)), recorder)
        self.assertEqual(wire(self.sent[0]), wire(self.sent[1]))
        self.assertEqual(recorder.statuses, [200])

    def test_sdk_retry_is_seen_as_two_responses(self):
        self.statuses.append(529)
        client = anthropic.Anthropic(api_key="test")
        recorder = run.ResponseRecorder()
        run.hooks_of(client).append(recorder)
        line = run.call_once(client, self.request, run.case_vars(make_case(1)), recorder)
        self.assertEqual((line["attempts"], line["attempt_statuses"]), (2, [529, 200]))
        self.assertEqual(line["response_headers"]["request-id"], "req_2")
        self.assertEqual(line["request_id"], "req_2")
        self.assertIs(line["hook_failed"], False)


def reply_json() -> dict:
    return {"id": "msg_test", "type": "message", "role": "assistant",
            "model": "claude-sonnet-5", "content": [{"type": "text", "text": answer()}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1}}


class MainTest(unittest.TestCase):
    """The checks main() makes before a real run. Inputs are faked; the
    protocol hash check has its own test above."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.cases = tmp / "cases.jsonl"
        self.cases.write_text(json.dumps(make_case(1)) + "\n")
        self.out = tmp / "raw" / "run-01.jsonl"
        self.patches = [mock.patch.object(run, "verify_inputs", lambda *a: None)]
        for patch in self.patches:
            patch.start()

    def tearDown(self) -> None:
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def argv(self, *extra: str) -> list[str]:
        return ["--cases", str(self.cases), "--run-index", "1", "--seed", "3",
                "--samples", "1", "--out", str(self.out), *extra]

    def test_dirty_tree_refuses_a_real_run(self):
        with mock.patch.object(run, "repo_state", lambda: ("abc123", [" M x.py"])):
            with self.assertRaises(SystemExit) as stopped:
                run.main(self.argv(), make_client=FakeClient)
        self.assertIn("not clean", str(stopped.exception.code))
        self.assertFalse(self.out.exists())

    def test_allow_dirty_runs_and_is_logged_with_the_commit(self):
        with mock.patch.object(run, "repo_state", lambda: ("abc123", [" M x.py"])):
            run.main(self.argv("--allow-dirty"), make_client=FakeClient)
        log = self.out.with_suffix(".log").read_text()
        self.assertIn("repo=abc123", log)
        self.assertIn("allow_dirty: working tree had 1 uncommitted path(s)", log)

    def test_dry_run_ignores_a_dirty_tree(self):
        with mock.patch.object(run, "repo_state", side_effect=AssertionError("asked")):
            run.main(self.argv("--dry-run"))

    def test_sdk_other_than_pinned_refuses(self):
        fake = types.ModuleType("anthropic")
        fake.__version__ = "0.0.1"
        fake.Anthropic = lambda: self.fail("client built despite version mismatch")
        with mock.patch.object(run, "repo_state", lambda: ("abc123", [])), \
                mock.patch.dict(sys.modules, {"anthropic": fake}):
            with self.assertRaises(SystemExit) as stopped:
                run.main(self.argv())
        self.assertIn("pins 1.4.0", str(stopped.exception.code))

    def test_pinned_sdk_reads_requirements(self):
        self.assertEqual(run.pinned_sdk(), "1.4.0")

    def test_repo_state_sees_untracked_but_not_ignored(self):
        repo = Path(self.tmp.name) / "repo"
        repo.mkdir()
        git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True,
                                        capture_output=True)
        git("init", "-q")
        (repo / ".gitignore").write_text("raw/\n")
        git("add", ".gitignore")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        (repo / "raw").mkdir()
        (repo / "raw" / "run-01.jsonl").write_text("{}\n")
        sha, dirty = run.repo_state(repo)
        self.assertEqual(len(sha), 40)
        self.assertEqual(dirty, [])
        (repo / "new.py").write_text("")
        self.assertEqual(run.repo_state(repo)[1], ["?? new.py"])


if __name__ == "__main__":
    unittest.main()

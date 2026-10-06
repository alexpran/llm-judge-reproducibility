#!/usr/bin/env python3
"""Smoke test of the call-and-record loop (PROTOCOL.md §9.2). Real calls.

Usage:
    python3 scripts/smoke_test.py --scout PATH/TO/scout [--plan]

Cases: the first 10 of scout's cases.json in id order (a fixed rule), never a
case of the corpus: the script refuses to start if any of them shares a Reddit
id with corpus/case_ids.json. Requests are built by scripts/judge.py from the
vars stored in cases.json; 2 consecutive calls per case, in id order.

Lines go to raw/smoke/smoke.jsonl in run.py's format, with case ids s01..s10
in place of scout's ids, which carry the Reddit id. run = 0 and seed = null
mark them as not belonging to any run. The script stops after the first call
if that call is an error, and before any call that would start past --max-usd.
It refuses to overwrite an existing output file.

--plan prints the number of calls and the estimate, and makes none.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import judge  # noqa: E402
import run  # noqa: E402

CASES = 10
SAMPLES = 2
OUT = run.REPO / "raw" / "smoke" / "smoke.jsonl"
CORPUS_IDS = run.REPO / "corpus" / "case_ids.json"

# Per call, from scout's own measurement on the 145-case suite with this
# model and prompt (scout.py, FALLBACK_COST_PER_THREAD note): mean and worst.
MEAN_USD_PER_CALL = 0.0113
WORST_USD_PER_CALL = 0.0168


def reddit_id(scout_case_id: str) -> str:
    """scout's case id ends with the Reddit id without its t3_ prefix."""
    return scout_case_id.rsplit("-", 1)[-1]


def select(scout_dir: Path) -> list[dict]:
    stored = json.loads((scout_dir / "cases.json").read_text(encoding="utf-8"))
    chosen = sorted(stored, key=lambda c: c["id"])[:CASES]
    corpus = json.loads(CORPUS_IDS.read_text(encoding="utf-8")).values()
    in_corpus = {original.split("_")[-1] for original in corpus} | set(corpus)
    clash = [c for c in chosen if c["id"] in in_corpus or reddit_id(c["id"]) in in_corpus]
    if clash:
        raise run.Stop(f"{len(clash)} of the selected cases are in the corpus")
    return chosen


def verify_prompts() -> None:
    text = run.PROTOCOL_PATH.read_text(encoding="utf-8")
    for name in ("JUDGE.md", "THREAD.md"):
        found = run.PROTOCOL_HASHES[name].findall(text)
        actual = run.sha256(judge.PROMPTS_DIR / name)
        if found != [actual]:
            raise run.Stop(f"sha256 of prompts/{name} does not match PROTOCOL.md")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scout", type=Path, required=True)
    parser.add_argument("--max-usd", type=float, default=1.0)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()

    try:
        verify_prompts()
        chosen = select(args.scout)
        calls = len(chosen) * SAMPLES
        print(f"cases {len(chosen)}, calls {calls}, estimated "
              f"{calls * MEAN_USD_PER_CALL:.2f} USD (mean) to "
              f"{calls * WORST_USD_PER_CALL:.2f} USD (worst), cap {args.max_usd} USD")
        if args.plan:
            return
        if OUT.exists():
            raise run.Stop(f"{OUT} exists; the smoke test is not resumed")
        pinned = run.pinned_sdk()
        import anthropic

        if anthropic.__version__ != pinned:
            raise run.Stop(f"anthropic {anthropic.__version__} is installed, "
                           f"requirements.txt pins {pinned}")
        repo_sha, dirty = run.repo_state()
        client = anthropic.Anthropic()
        recorder = run.ResponseRecorder()
        run.hooks_of(client).append(recorder)
    except run.Stop as exc:
        sys.exit(f"smoke_test: {exc}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    log_path = OUT.with_suffix(".log")
    prompts = judge.load_prompts()
    run.log(log_path, f"start smoke cases={len(chosen)} samples={SAMPLES} "
                      f"max_usd={args.max_usd} sdk=anthropic {anthropic.__version__} "
                      f"repo={repo_sha} dirty_paths={len(dirty)}")
    spent = 0.0
    made = 0
    with OUT.open("a", encoding="utf-8") as handle:
        for index, case in enumerate(chosen, start=1):
            vars = judge.judge_vars(**case["vars"])
            request = judge.build_request(vars, prompts)
            verdict = case["metadata"].get("judge_verdict")
            stratum = "skipped" if verdict == "skip" else "proposed"
            for sample in range(1, SAMPLES + 1):
                if spent >= args.max_usd:
                    run.log(log_path, f"stop: estimated cost {spent:.4f} USD reached "
                                      f"--max-usd {args.max_usd}")
                    sys.exit(f"smoke_test: budget reached after {made} calls")
                line = run.call_once(client, request, vars, recorder)
                run.log_hook_failures(log_path, recorder, f"s{index:02d} sample {sample}")
                run.append_line(handle, {"case_id": f"s{index:02d}", "stratum": stratum,
                                         "run": 0, "seed": None, "sample": sample,
                                         **line})
                made += 1
                spent += line["cost_usd"] or 0.0
                if made == 1 and line["error_type"] is not None:
                    run.log(log_path, f"stop: first call failed ({line['error_type']})")
                    sys.exit(f"smoke_test: first call failed: {line['error_type']}: "
                             f"{line['error']}")
    run.log(log_path, f"end smoke: {made} calls, estimated cost {spent:.4f} USD")
    print(f"done: {made} calls, estimated {spent:.4f} USD -> {OUT}")


if __name__ == "__main__":
    main()

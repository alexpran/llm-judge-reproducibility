#!/usr/bin/env python3
"""One run of the experiment (PROTOCOL.md §4, §5, §6).

Usage:
    python3 scripts/run.py --cases corpus/cases.jsonl --run-index 1 [--seed 101]
    python3 scripts/run.py --cases corpus/cases.jsonl --run-index 1 --dry-run

Every call is serial. The order of cases is shuffled with the run's seed, fixed
by PROTOCOL.md §4 (runs 1 to 6: 101 to 106). Without --seed it is taken from
that table; a --seed that does not match --run-index refuses to start. The
samples of a case are consecutive calls. One JSONL line per call is written
and synced to disk before the next call starts. Nothing is ever discarded or
redrawn: an error is a line with `error` set.

Resuming: if the output file exists, the (case, sample) pairs already in it are
skipped and the run continues in the same order. Each session, interruption and
resumption is logged next to the output, in run-0N.log.

A real run refuses to start unless the installed anthropic SDK is the version
pinned in requirements.txt and the git working tree is clean (--allow-dirty
overrides the second, and is logged). The log records the SDK version, the
repository commit, and the operating system, architecture and Python version.

The SDK reads ANTHROPIC_API_KEY from the environment. --dry-run builds every
request and needs neither the key, the SDK, a clean tree nor the network.

Every line has `error_type`: null, "api", "parse", "refusal" or "max_tokens"
(PROTOCOL.md §6), and `error` with the detail. It also has the headers of the
last HTTP response of the call (`response_headers`, null if none arrived) and
the status of every response, retries included (`attempts`,
`attempt_statuses`). They are read by a response hook on the HTTP client the
SDK builds; the hook reads no body and leaves the request as it is. If the hook
fails on a response, the failure is logged and `hook_failed` is true: that
response is then missing from `attempts`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import re
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import judge  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PROTOCOL_PATH = REPO / "PROTOCOL.md"
REQUIREMENTS_PATH = REPO / "requirements.txt"

RUNS = range(1, 7)
# The shuffle seed of each run, as fixed in PROTOCOL.md §4.
SEEDS = {1: 101, 2: 102, 3: 103, 4: 104, 5: 105, 6: 106}

# Where PROTOCOL.md states each hash. A TBD in its place fails the check.
PROTOCOL_HASHES = {
    "JUDGE.md": re.compile(r"`JUDGE\.md`, sha256 `([0-9a-f]{64})`"),
    "THREAD.md": re.compile(r"`THREAD\.md`, sha256 `([0-9a-f]{64})`"),
    "cases": re.compile(r"sha256 of the case file: `([0-9a-f]{64})`"),
}


class Stop(Exception):
    """A refusal to start or to continue, with the reason."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


# --- Inputs --------------------------------------------------------------------


def verify_inputs(cases_path: Path, prompts_dir: Path, protocol_path: Path) -> None:
    text = protocol_path.read_text(encoding="utf-8")
    files = {
        "JUDGE.md": prompts_dir / "JUDGE.md",
        "THREAD.md": prompts_dir / "THREAD.md",
        "cases": cases_path,
    }
    for name, pattern in PROTOCOL_HASHES.items():
        found = pattern.findall(text)
        if len(found) != 1:
            raise Stop(f"{protocol_path.name} does not state one sha256 for {name}")
        actual = sha256(files[name])
        if actual != found[0]:
            raise Stop(f"sha256 of {files[name]} is {actual}, "
                       f"{protocol_path.name} says {found[0]}")


def pinned_sdk(requirements: Path = REQUIREMENTS_PATH) -> str:
    """The anthropic version fixed in requirements.txt."""
    for raw in requirements.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"\s*anthropic==([^\s#]+)\s*(#.*)?", raw)
        if match:
            return match.group(1)
    raise Stop(f"{requirements.name} does not pin anthropic==<version>")


def repo_state(repo: Path = REPO) -> tuple[str, list[str]]:
    """(HEAD sha, paths `git status --porcelain` reports). Ignored files, such
    as raw/ and the corpus, are not reported and do not make the tree dirty."""
    def git(*args: str) -> str:
        try:
            return subprocess.run(["git", "-C", str(repo), *args], check=True,
                                  capture_output=True, text=True).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise Stop(f"cannot read the git state of {repo}: {exc}") from exc
    return git("rev-parse", "HEAD").strip(), git("status", "--porcelain").splitlines()


def load_cases(path: Path) -> list[dict]:
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    ids = [c["case_id"] for c in cases]
    if len(set(ids)) != len(ids):
        raise Stop(f"{path} holds duplicate case ids")
    return cases


def case_vars(case: dict) -> dict[str, str]:
    return judge.judge_vars(
        title=case["title"],
        subreddit=case["subreddit"],
        flair=case["flair"],
        text=case["text"],
        commented_titles=case["commented_titles"],
    )


def run_order(case_ids: list[str], seed: int) -> list[str]:
    """Sorted first, so the order depends on the seed and on nothing else."""
    order = sorted(case_ids)
    random.Random(seed).shuffle(order)
    return order


# --- One call ------------------------------------------------------------------


def plain(obj: Any) -> Any:
    """An SDK object (or a test double) as JSON-ready data."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {str(k): plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [plain(v) for v in obj]
    if hasattr(obj, "__dict__"):
        return {k: plain(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return repr(obj)


def thinking_tokens(usage: dict | None) -> int | None:
    details = (usage or {}).get("output_tokens_details") or {}
    found = details.get("thinking_tokens")
    return None if found is None else int(found)


def cost_of(usage: dict | None) -> float:
    """Estimated from the list price. Thinking tokens are inside output_tokens."""
    usage = usage or {}
    return sum(
        (usage.get(field) or 0) * price / 1_000_000
        for field, price in judge.PRICE_PER_MTOK.items()
    )


class ResponseRecorder:
    """Response hook on the SDK's own HTTP client. It sees every HTTP response
    of a call, retries included, and reads only the status and the headers,
    never the body. It never raises: a failure is kept in `failures` for the
    caller to log, and the call goes on. The request is not touched."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.statuses: list[int] = []
        self.headers: dict[str, str] | None = None
        self.failures: list[str] = []

    def __call__(self, response: Any) -> None:
        try:
            status = int(response.status_code)
            headers = dict(response.headers.items())
            self.statuses.append(status)
            self.headers = headers
        except Exception as exc:  # noqa: BLE001 — must never break the call
            try:
                self.failures.append(f"{type(exc).__name__}: {exc}")
            except Exception:  # noqa: BLE001
                pass


def hooks_of(client: Any) -> list:
    """The response hook list of the HTTP client the SDK built. `_client` is
    private: anthropic is pinned (requirements.txt) and a test checks it."""
    try:
        hooks = client._client.event_hooks["response"]
    except (AttributeError, KeyError, TypeError) as exc:
        raise Stop(f"cannot reach the SDK's response hooks: {exc}") from exc
    if not isinstance(hooks, list):
        raise Stop(f"the SDK's response hooks are a {type(hooks).__name__}, not a list")
    return hooks


def log_hook_failures(path: Path, recorder: ResponseRecorder, where: str) -> None:
    for failure in recorder.failures:
        log(path, f"response hook failed on {where}: {failure}")


def call_once(client: Any, request: dict, vars: dict[str, str],
              recorder: ResponseRecorder,
              read: Callable[[str], dict] | None = None) -> dict:
    """One call and everything known about it. Never raises for an API or
    parsing failure: that becomes `error` on the line. `recorder` must be
    attached to the client's response hooks.

    `read` replaces scout's parser for another prompt (PROTOCOL.md §9.3): it
    takes the reply text, returns the fields to add to the line, and raises
    when the reply cannot be read. scout's verdict fields then stay null."""
    recorder.reset()
    line: dict[str, Any] = {
        "started_at": utc_now(),
        "latency_ms": None,
        "request_id": None,
        "response_headers": None,
        "attempts": 0,
        "attempt_statuses": [],
        "hook_failed": False,
        "model": None,
        "stop_reason": None,
        "raw_text": None,
        "verdict_raw": None,
        "verdict_settled": None,
        "why": None,
        "angle": None,
        "tool_refused": None,
        "usage": None,
        "thinking_tokens": None,
        "cost_usd": None,
        "error_type": None,
        "error": None,
    }
    started = time.perf_counter()
    try:
        reply = client.messages.create(**request)
    except Exception as exc:  # noqa: BLE001 — after the SDK's own retries
        line["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        record_responses(line, recorder)
        line["request_id"] = getattr(exc, "request_id", None)
        line["error_type"] = "api"
        line["error"] = f"{type(exc).__name__}: {exc}"
        return line
    line["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    record_responses(line, recorder)
    line["request_id"] = getattr(reply, "_request_id", None)
    line["model"] = getattr(reply, "model", None)
    line["stop_reason"] = getattr(reply, "stop_reason", None)
    line["usage"] = plain(getattr(reply, "usage", None))
    line["thinking_tokens"] = thinking_tokens(line["usage"])
    line["cost_usd"] = round(cost_of(line["usage"]), 8)
    try:
        line["raw_text"] = judge.text_of(reply)
    except Exception as exc:  # noqa: BLE001
        line["error_type"] = "parse"
        line["error"] = f"no readable text: {type(exc).__name__}: {exc}"
        return line
    if line["stop_reason"] == "refusal":
        line["error_type"] = "refusal"
        line["error"] = "stop_reason refusal"
        return line
    try:
        answer = (read or judge.parse)(line["raw_text"])
    except Exception as exc:  # noqa: BLE001
        # Cut at the cap before a readable verdict is the cap's failure, not
        # the parser's. A readable verdict at the cap is still a verdict.
        cut = line["stop_reason"] == "max_tokens"
        line["error_type"] = "max_tokens" if cut else "parse"
        line["error"] = f"{type(exc).__name__}: {exc}"
        return line
    if read is not None:
        line.update(answer)
        return line
    settled = judge.settle_tool(answer, vars)
    line["verdict_raw"] = answer["verdict"]
    line["verdict_settled"] = settled["verdict"]
    line["why"] = answer["why"]
    line["angle"] = answer["angle"]
    line["tool_refused"] = settled["tool_refused"]
    return line


def record_responses(line: dict, recorder: ResponseRecorder) -> None:
    """Headers of the last HTTP response, and the status of every one. A
    response the hook failed on is missing from both: `hook_failed` says so."""
    line["response_headers"] = recorder.headers
    line["attempts"] = len(recorder.statuses)
    line["attempt_statuses"] = list(recorder.statuses)
    line["hook_failed"] = bool(recorder.failures)


# --- The run -------------------------------------------------------------------


def read_existing(out: Path, run_index: int, seed: int) -> list[dict]:
    if not out.exists():
        return []
    rows = []
    for number, raw in enumerate(out.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise Stop(f"{out}:{number} is not a complete JSON line ({exc}); "
                       "inspect it by hand before resuming") from exc
        if row.get("run") != run_index or row.get("seed") != seed:
            raise Stop(f"{out}:{number} belongs to run {row.get('run')} "
                       f"seed {row.get('seed')}, not run {run_index} seed {seed}")
        rows.append(row)
    return rows


def environment() -> str:
    """The machine as the SDK describes it in its request headers (operating
    system, architecture, Python runtime), for the run's log."""
    return (f"os={platform.system()} {platform.release()} arch={platform.machine()} "
            f"python={platform.python_implementation()} {platform.python_version()}")


def append_line(handle, row: dict) -> None:
    handle.write(canonical(row) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def log(path: Path, message: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{utc_now()} {message}\n")
        handle.flush()
        os.fsync(handle.fileno())


def run(
    cases: list[dict],
    *,
    run_index: int,
    seed: int,
    samples: int,
    out: Path,
    client: Any,
    prompts: tuple[str, str],
    max_usd: float | None = None,
    log_path: Path | None = None,
    sdk_version: str = "",
    repo_sha: str = "",
    allow_dirty: bool = False,
    dirty_paths: int = 0,
) -> dict:
    log_path = log_path or out.with_suffix(".log")
    hooks = hooks_of(client)
    out.parent.mkdir(parents=True, exist_ok=True)
    by_id = {c["case_id"]: c for c in cases}
    order = run_order(list(by_id), seed)
    existing = read_existing(out, run_index, seed)
    done = {(r["case_id"], r["sample"]) for r in existing}
    spent = sum(r.get("cost_usd") or 0.0 for r in existing)
    planned = len(order) * samples

    if existing:
        last = max(r["started_at"] for r in existing)
        log(log_path, f"resume run={run_index} seed={seed}: {len(existing)} of "
                      f"{planned} lines present, last call started {last}; "
                      f"previous session ended before completion")
    log(log_path, f"start run={run_index} seed={seed} samples={samples} "
                  f"cases={len(order)} planned={planned} max_usd={max_usd} "
                  f"sdk=anthropic {sdk_version} repo={repo_sha} {environment()}")
    if allow_dirty:
        log(log_path, f"allow_dirty: working tree had {dirty_paths} uncommitted "
                      f"path(s) at start")

    written = 0
    status = "complete"
    recorder = ResponseRecorder()
    hooks.append(recorder)
    try:
        with out.open("a", encoding="utf-8") as handle:
            for case_id in order:
                case = by_id[case_id]
                vars = case_vars(case)
                request = judge.build_request(vars, prompts)
                for sample in range(1, samples + 1):
                    if (case_id, sample) in done:
                        continue
                    if max_usd is not None and spent >= max_usd:
                        status = "budget"
                        log(log_path, f"stop: estimated cost {spent:.4f} USD reached "
                                      f"--max-usd {max_usd} before {case_id} "
                                      f"sample {sample}")
                        return summary(status, existing, written, planned, spent)
                    line = call_once(client, request, vars, recorder)
                    log_hook_failures(log_path, recorder, f"{case_id} sample {sample}")
                    row = {"case_id": case_id, "stratum": case["stratum"],
                           "run": run_index, "seed": seed, "sample": sample, **line}
                    append_line(handle, row)
                    written += 1
                    spent += line["cost_usd"] or 0.0
    except BaseException as exc:
        log(log_path, f"interrupted: {type(exc).__name__}: {exc} "
                      f"after {written} lines in this session")
        raise
    finally:
        hooks.remove(recorder)
    log(log_path, f"end run={run_index}: {written} lines in this session, "
                  f"{len(existing) + written} of {planned} in total, "
                  f"estimated cost {spent:.4f} USD")
    return summary(status, existing, written, planned, spent)


def summary(status: str, existing: list, written: int, planned: int, spent: float) -> dict:
    return {"status": status, "previous": len(existing), "written": written,
            "planned": planned, "estimated_usd": round(spent, 6)}


def dry_run(cases: list[dict], samples: int, prompts: tuple[str, str]) -> tuple[int, str]:
    """Every request of a run, in case-id order, hashed together. The order of
    the run does not enter the hash: it is the same request set for any seed."""
    digest = hashlib.sha256()
    count = 0
    for case in sorted(cases, key=lambda c: c["case_id"]):
        request = canonical(judge.build_request(case_vars(case), prompts))
        for _ in range(samples):
            digest.update(request.encode("utf-8") + b"\n")
            count += 1
    return count, digest.hexdigest()


def main(argv: list[str] | None = None,
         make_client: Callable[[], Any] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--run-index", type=int, required=True, choices=RUNS)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--max-usd", type=float)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="start a real run with uncommitted changes (logged)")
    args = parser.parse_args(argv)
    if args.samples < 1:
        parser.error("--samples must be at least 1")
    if not args.dry_run:
        expected = SEEDS[args.run_index]
        if args.seed is None:
            args.seed = expected
        elif args.seed != expected:
            parser.error(f"--seed {args.seed} is not the seed of run {args.run_index}: "
                         f"PROTOCOL.md §4 fixes {expected}")
    out = args.out or REPO / "raw" / f"run-{args.run_index:02d}.jsonl"

    try:
        verify_inputs(args.cases, judge.PROMPTS_DIR, PROTOCOL_PATH)
        cases = load_cases(args.cases)
        prompts = judge.load_prompts()
        if args.dry_run:
            count, digest = dry_run(cases, args.samples, prompts)
            print(f"cases     {len(cases)}")
            print(f"requests  {count} ({args.samples} per case)")
            print(f"sha256    {digest}")
            return
        repo_sha, dirty = repo_state()
        if dirty and not args.allow_dirty:
            raise Stop(f"working tree is not clean ({len(dirty)} path(s)); commit, "
                       "or pass --allow-dirty to start anyway (it is logged)")
        pinned = pinned_sdk()
        if make_client is None:
            import anthropic

            version = anthropic.__version__
            if version != pinned:
                raise Stop(f"anthropic {version} is installed, requirements.txt "
                           f"pins {pinned}")
            client = anthropic.Anthropic()
        else:
            client, version = make_client(), "injected"
        result = run(cases, run_index=args.run_index, seed=args.seed,
                     samples=args.samples, out=out, client=client,
                     prompts=prompts, max_usd=args.max_usd, sdk_version=version,
                     repo_sha=repo_sha, allow_dirty=args.allow_dirty,
                     dirty_paths=len(dirty))
    except Stop as exc:
        sys.exit(f"run: {exc}")
    print(canonical(result))


if __name__ == "__main__":
    main()

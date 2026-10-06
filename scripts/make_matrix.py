#!/usr/bin/env python3
"""The raw run files as one matrix, one row per call (PROTOCOL.md §5, §14).

Usage:
    python3 scripts/make_matrix.py [--raw raw] [--cases corpus/cases.jsonl]
        [--ids corpus/public_ids.json] [--out results] [--accept-incomplete]

Reads raw/run-01.jsonl … run-06.jsonl and, from corpus/cases.jsonl, only the
metadata of each case (stratum, label, judging day, whether the text is
empty): never title, text or any other thread field. Writes results/matrix.csv
and results/MANIFEST.txt (sha256 of the raw files and of the matrix).

Public ids. In the matrix a case is public_id p001…, assigned in random order,
and its judging day is day_label A…, assigned in random order to the days. Both maps are
in corpus/public_ids.json (ignored by git): reused if the file exists, created
with a system random source if it does not. Rows are sorted by (run, public
id, sample), so their order says nothing about the original one.

No text enters the matrix: not raw_text, why, angle, the text of tool_refused,
error, any header other than request-id and traceresponse, nor the original
ids. Every value is checked against a closed pattern for its column before
anything is written; a value that does not match stops the script.

The script stops, writing nothing, unless: the six runs are present; each has
one line per (case, sample) of the case file, 5 samples per case, with no
duplicate and none missing; each line's run and seed are those of its file
(seed table in run.py, PROTOCOL.md §4); every case_id is in the case file with
the same stratum. With --accept-incomplete, fewer runs are accepted if they are
runs 1 to k, each complete; MANIFEST.txt then says so (PROTOCOL.md §10).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import re
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SAMPLES = 5

# Response headers published by name (PROTOCOL.md §5), with their column.
HEADERS = {"request-id": "request_id", "traceresponse": "traceresponse"}

VERDICT = r"(skip|upvote|comment|comment\+tool)?"
COUNT = r"\d*"
# Every column and the only values it may hold. Empty means null.
COLUMNS = {
    "public_id": r"p\d{3}",
    "stratum": r"proposed|skipped",
    "label_status": r"labelled|deferred",
    "expected": VERDICT,
    "day_label": r"[A-Z]",
    "text_empty": r"true|false",
    "run": r"[1-6]",
    "seed": r"10[1-6]",
    "sample": r"[1-5]",
    "started_at": r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?\+00:00",
    "latency_ms": r"(\d+(\.\d+)?)?",
    "model": r"[a-z0-9.-]*",
    "stop_reason": r"(end_turn|max_tokens|stop_sequence|tool_use|pause_turn|refusal)?",
    "verdict_raw": VERDICT,
    "verdict_settled": VERDICT,
    "tool_refused": r"(true|false)?",
    "error_type": r"(api|parse|refusal|max_tokens)?",
    "attempts": r"\d+",
    "attempt_statuses": r"(\d{3}(;\d{3})*)?",
    "hook_failed": r"true|false",
    "output_tokens": COUNT,
    "thinking_tokens": COUNT,
    "service_tier": r"[a-z_]*",
    "inference_geo": r"[a-z_]*",
    "request_id": r"(req_[A-Za-z0-9]+)?",
    "traceresponse": r"(00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2})?",
}
PATTERNS = {name: re.compile(pattern) for name, pattern in COLUMNS.items()}


class Stop(Exception):
    """A refusal to write the matrix, with the reason."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def load_cases(path: Path) -> dict[str, dict]:
    """Metadata only."""
    keep = ("stratum", "judged_day", "expected", "text_empty")
    cases = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(raw)
        cases[record["case_id"]] = {name: record[name] for name in keep}
    return cases


def public_ids(path: Path, cases: dict[str, dict]) -> dict[str, dict[str, str]]:
    """{"cases": case_id -> pNNN, "days": judged_day -> letter}, reused or created."""
    ids = sorted(cases)
    days = sorted({c["judged_day"] for c in cases.values()})
    if len(ids) > 999 or len(days) > 26:
        raise Stop("too many cases or days for the public id format")
    if path.exists():
        maps = json.loads(path.read_text(encoding="utf-8"))
        for name, keys, pattern in (("cases", ids, r"p\d{3}"), ("days", days, r"[A-Z]")):
            found = maps.get(name, {})
            if sorted(found) != keys:
                raise Stop(f"{path.name}: its {name} are not those of the case file")
            values = list(found.values())
            if len(set(values)) != len(values) or not all(re.fullmatch(pattern, v) for v in values):
                raise Stop(f"{path.name}: its {name} map is not one to one onto valid ids")
        return maps
    source = random.SystemRandom()
    public = [f"p{n:03d}" for n in range(1, len(ids) + 1)]
    letters = list(string.ascii_uppercase[:len(days)])
    source.shuffle(public)
    source.shuffle(letters)
    maps = {"cases": dict(zip(ids, public)), "days": dict(zip(days, letters))}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(maps, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return maps


def read_run(path: Path, run_index: int, cases: dict[str, dict]) -> list[dict]:
    seed = run.SEEDS[run_index]
    lines = [json.loads(raw) for raw in path.read_text(encoding="utf-8").splitlines()]
    seen = set()
    for number, line in enumerate(lines, 1):
        where = f"{path.name} line {number}"
        if line.get("run") != run_index or line.get("seed") != seed:
            raise Stop(f"{where}: run {line.get('run')} seed {line.get('seed')}, "
                       f"not run {run_index} seed {seed}")
        case = cases.get(line.get("case_id"))
        if case is None:
            raise Stop(f"{where}: case_id not in the case file")
        if line.get("stratum") != case["stratum"]:
            raise Stop(f"{where}: stratum differs from the case file")
        key = (line["case_id"], line.get("sample"))
        if key in seen:
            raise Stop(f"{where}: duplicate (case, sample)")
        seen.add(key)
    expected = {(c, s) for c in cases for s in range(1, SAMPLES + 1)}
    if seen != expected:
        raise Stop(f"{path.name}: {len(expected - seen)} (case, sample) pairs missing, "
                   f"{len(seen - expected)} unexpected")
    if len(lines) != len(expected):
        raise Stop(f"{path.name}: {len(lines)} lines, expected {len(expected)}")
    return lines


def present_runs(raw_dir: Path, accept_incomplete: bool) -> list[int]:
    present = [i for i in run.RUNS if (raw_dir / f"run-{i:02d}.jsonl").exists()]
    if len(present) == len(run.RUNS):
        return present
    missing = ", ".join(f"run-{i:02d}.jsonl" for i in run.RUNS if i not in present)
    if not accept_incomplete:
        raise Stop(f"missing {missing}; --accept-incomplete uses the complete runs present")
    if not present or present != list(range(1, len(present) + 1)):
        raise Stop(f"missing {missing}; --accept-incomplete needs runs 1 to k")
    return present


def row_of(line: dict, case: dict, maps: dict) -> dict[str, str]:
    usage = line.get("usage") or {}
    headers = {k.lower(): v for k, v in (line.get("response_headers") or {}).items()}
    tool_refused = line.get("tool_refused")
    values = {
        "public_id": maps["cases"][line["case_id"]],
        "stratum": case["stratum"],
        "label_status": "labelled" if case["expected"] is not None else "deferred",
        "expected": case["expected"],
        "day_label": maps["days"][case["judged_day"]],
        "text_empty": case["text_empty"],
        "run": line["run"],
        "seed": line["seed"],
        "sample": line["sample"],
        "started_at": line["started_at"],
        "latency_ms": line["latency_ms"],
        "model": line["model"],
        "stop_reason": line["stop_reason"],
        "verdict_raw": line["verdict_raw"],
        "verdict_settled": line["verdict_settled"],
        "tool_refused": None if tool_refused is None else bool(tool_refused),
        "error_type": line["error_type"],
        "attempts": line["attempts"],
        "attempt_statuses": ";".join(str(s) for s in line["attempt_statuses"]),
        "hook_failed": line["hook_failed"],
        "output_tokens": usage.get("output_tokens"),
        "thinking_tokens": line["thinking_tokens"],
        "service_tier": usage.get("service_tier"),
        "inference_geo": usage.get("inference_geo"),
        **{column: headers.get(name) for name, column in HEADERS.items()},
    }
    row = {name: cell(values[name]) for name in COLUMNS}
    for name, value in row.items():
        if not PATTERNS[name].fullmatch(value):
            raise Stop(f"run {line['run']} {line['case_id']} sample {line['sample']}: "
                       f"value of {name} does not match its pattern")
    return row


def build(raw_dir: Path, cases_path: Path, ids_path: Path,
          accept_incomplete: bool = False) -> tuple[str, list[Path]]:
    cases = load_cases(cases_path)
    runs = present_runs(raw_dir, accept_incomplete)
    paths = [raw_dir / f"run-{i:02d}.jsonl" for i in runs]
    lines = [line for i, path in zip(runs, paths) for line in read_run(path, i, cases)]
    maps = public_ids(ids_path, cases)
    rows = [row_of(line, cases[line["case_id"]], maps) for line in lines]
    rows.sort(key=lambda r: (int(r["run"]), r["public_id"], int(r["sample"])))
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(COLUMNS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue(), paths


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", type=Path, default=REPO / "raw")
    parser.add_argument("--cases", type=Path, default=REPO / "corpus" / "cases.jsonl")
    parser.add_argument("--ids", type=Path, default=REPO / "corpus" / "public_ids.json")
    parser.add_argument("--out", type=Path, default=REPO / "results")
    parser.add_argument("--accept-incomplete", action="store_true")
    args = parser.parse_args(argv)
    try:
        matrix, paths = build(args.raw, args.cases, args.ids, args.accept_incomplete)
    except Stop as exc:
        sys.exit(f"make_matrix: {exc}")
    args.out.mkdir(parents=True, exist_ok=True)
    matrix_path = args.out / "matrix.csv"
    matrix_path.write_bytes(matrix.encode("utf-8"))
    manifest = [f"{sha256(p)}  {p.name}" for p in paths]
    manifest.append(f"{sha256(matrix_path)}  {matrix_path.name}")
    if len(paths) < len(run.RUNS):
        manifest.append(f"incomplete: {len(paths)} of {len(run.RUNS)} runs, "
                        f"accepted with --accept-incomplete")
    (args.out / "MANIFEST.txt").write_bytes(("\n".join(manifest) + "\n").encode("utf-8"))
    print(f"rows      {matrix.count(chr(10)) - 1}")
    print(f"sha256    {sha256(matrix_path)}  matrix.csv")


if __name__ == "__main__":
    main()

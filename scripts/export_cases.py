#!/usr/bin/env python3
"""Export the experiment's case file from the frozen copy of scout's seen.json.

Usage:
    python3 scripts/export_cases.py PATH/TO/seen-<timestamp>.json

Reads only the file given on the command line, after checking its sha256.
Writes corpus/cases.jsonl and corpus/case_ids.json (both ignored by git).
Deterministic: two runs on the same input produce byte-identical files.
Standard library only. Makes no network calls.

Inclusion rule (PROTOCOL.md §3): every record judged from 2026-09-18 to
2026-10-05 inclusive, Europe/Rome time, excluding `duplicate` records.
The rule does not look at the verdict or at the mark.
"""

import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

EXPECTED_SHA256 = "d76b72b9b2b8e9ec0ad55deef4faab1ad8dda285a8f5188166f05015ad4de567"

TZ = ZoneInfo("Europe/Rome")
FIRST_DAY = date(2026, 9, 18)
LAST_DAY = date(2026, 10, 5)

VERDICT_DUPLICATE = "duplicate"
PROPOSED_VERDICTS = frozenset({"comment", "comment+tool", "upvote"})
SKIPPED_VERDICTS = frozenset({"skip"})

# Copied from scout at commit dfd5187ac0ddaa5968c6b777a1f56f406f21203b
# (scout.py, MARK_TO_VERDICT). `deferred` is absent on purpose: it implies no
# verdict. Any mark not in this map, and a missing mark, give expected = None.
MARK_TO_VERDICT = {
    "commented": "comment",
    "commented_with_tool": "comment+tool",
    "upvoted": "upvote",
    "declined": "skip",
    "ignored": "skip",
}

# The judge's inputs, copied from the record unchanged.
JUDGE_INPUTS = ("title", "subreddit", "flair", "text", "commented_titles")

# Checks from PROTOCOL.md §3. The script stops if any of them fails.
EXPECTED_COUNTS = {
    "cases": 533,
    "proposed": 49,
    "skipped": 484,
    "with_expected": 211,
    "with_expected_proposed": 43,
    "with_expected_skipped": 168,
}

OUT_DIR = Path(__file__).resolve().parent.parent / "corpus"
CASES_PATH = OUT_DIR / "cases.jsonl"
IDS_PATH = OUT_DIR / "case_ids.json"


def fail(message: str) -> None:
    sys.exit(f"export_cases: {message}")


def judged_utc(record: dict) -> datetime:
    moment = datetime.fromisoformat(record["judged_at"])
    if moment.tzinfo is None:
        fail(f"record {record['id']}: judged_at has no timezone")
    return moment


def stratum(verdict: str) -> str:
    if verdict in PROPOSED_VERDICTS:
        return "proposed"
    if verdict in SKIPPED_VERDICTS:
        return "skipped"
    fail(f"verdict {verdict!r} is neither proposed nor skipped")


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        fail("usage: export_cases.py PATH/TO/seen.json")
    source = Path(argv[1]).expanduser()
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_SHA256:
        fail(f"sha256 mismatch: got {digest}, expected {EXPECTED_SHA256}")
    seen = json.loads(raw.decode("utf-8"))

    selected = []
    for record in seen.values():
        if record.get("verdict") == VERDICT_DUPLICATE:
            continue
        day = judged_utc(record).astimezone(TZ).date()
        if FIRST_DAY <= day <= LAST_DAY:
            selected.append((judged_utc(record), record["id"], day, record))
    selected.sort(key=lambda item: (item[0], item[1]))

    cases = []
    case_ids = {}
    for n, (_, original_id, day, record) in enumerate(selected, start=1):
        case_id = f"c{n:03d}"
        mark = record.get("action")
        case = {name: record[name] for name in JUDGE_INPUTS}
        case.update(
            case_id=case_id,
            stratum=stratum(record["verdict"]),
            judged_day=day.isoformat(),
            mark=mark,
            expected=MARK_TO_VERDICT.get(mark),
            text_empty=record["text"] == "",
        )
        cases.append(case)
        case_ids[case_id] = original_id

    strata = Counter(c["stratum"] for c in cases)
    labelled = Counter(c["stratum"] for c in cases if c["expected"] is not None)
    counts = {
        "cases": len(cases),
        "proposed": strata["proposed"],
        "skipped": strata["skipped"],
        "with_expected": sum(labelled.values()),
        "with_expected_proposed": labelled["proposed"],
        "with_expected_skipped": labelled["skipped"],
    }
    for name, expected in EXPECTED_COUNTS.items():
        if counts[name] != expected:
            fail(f"check failed: {name} = {counts[name]}, expected {expected}")

    OUT_DIR.mkdir(exist_ok=True)
    cases_bytes = "".join(dumps(c) + "\n" for c in cases).encode("utf-8")
    CASES_PATH.write_bytes(cases_bytes)
    IDS_PATH.write_bytes((dumps(case_ids) + "\n").encode("utf-8"))

    empty = Counter(c["stratum"] for c in cases if c["text_empty"])
    days = sorted({c["judged_day"] for c in cases})
    print(f"source sha256      {digest}")
    print(f"cases.jsonl sha256 {hashlib.sha256(cases_bytes).hexdigest()}")
    print(f"cases              {counts['cases']} "
          f"(proposed {counts['proposed']}, skipped {counts['skipped']})")
    print(f"with expected      {counts['with_expected']} "
          f"(proposed {counts['with_expected_proposed']}, "
          f"skipped {counts['with_expected_skipped']})")
    print(f"empty text         {sum(empty.values())} "
          f"(proposed {empty['proposed']}, skipped {empty['skipped']})")
    print(f"judging days       {len(days)}: {', '.join(days)}")


if __name__ == "__main__":
    main(sys.argv)

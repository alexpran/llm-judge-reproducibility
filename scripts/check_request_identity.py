#!/usr/bin/env python3
"""Show that scripts/judge.py builds the request scout sends in production.

Usage (with an interpreter where scout and its dependencies import):
    PYTHONDONTWRITEBYTECODE=1 SCOUT/.venv/bin/python \
        scripts/check_request_identity.py --scout SCOUT --cases corpus/cases.jsonl

For each case, the request is built twice:
  - by scout's own ScoutJudge, through its full call path, with a fake client
    whose messages.create captures its keyword arguments and raises before any
    connection could be opened;
  - by scripts/judge.py.
The two argument sets are serialised as canonical JSON and compared by sha256.

Cases: the 144 of scout's cases.json (vars as stored there) and the 533 of
corpus/cases.jsonl (vars through each side's own judge_vars).
Only counts and the names of differing fields are printed, never case content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import judge  # noqa: E402


class Captured(Exception):
    def __init__(self, kwargs: dict) -> None:
        super().__init__("captured")
        self.kwargs = kwargs


class _Messages:
    def create(self, **kwargs):
        raise Captured(kwargs)


class FakeClient:
    """No transport at all: create() raises with the arguments it was given."""

    messages = _Messages()


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(obj) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def differing_fields(a: dict, b: dict) -> list[str]:
    fields = []
    for key in sorted(set(a) | set(b)):
        if key not in a or key not in b:
            fields.append(f"{key} (present on one side only)")
        elif canonical(a[key]) != canonical(b[key]):
            fields.append(key)
    return fields


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scout", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(args.scout.resolve()))
    import scout  # noqa: E402 — scout's own module, read only
    from digline.run import Case  # noqa: E402

    production = scout.build_judge(client=FakeClient())
    prompts = judge.load_prompts()

    def scout_request(case_id: str, vars: dict) -> dict:
        try:
            production(Case(id=case_id, vars=vars))
        except Captured as captured:
            return captured.kwargs
        raise RuntimeError("ScoutJudge returned without calling the client")

    sets = []
    stored = json.loads((args.scout / "cases.json").read_text(encoding="utf-8"))
    sets.append(("scout cases.json", [
        (c["id"], c["vars"], c["vars"]) for c in stored
    ]))
    corpus = [json.loads(line) for line in
              args.cases.read_text(encoding="utf-8").splitlines()]
    fields = ("title", "subreddit", "flair", "text", "commented_titles")
    sets.append(("corpus/cases.jsonl", [
        (c["case_id"],
         scout.judge_vars(**{f: c[f] for f in fields}),
         judge.judge_vars(**{f: c[f] for f in fields}))
        for c in corpus
    ]))

    failed = False
    for name, items in sets:
        identical = 0
        diffs: dict[str, int] = {}
        for case_id, scout_vars, our_vars in items:
            theirs = scout_request(case_id, scout_vars)
            ours = judge.build_request(our_vars, prompts)
            if digest(theirs) == digest(ours):
                identical += 1
            else:
                for field in differing_fields(theirs, ours):
                    diffs[field] = diffs.get(field, 0) + 1
        print(f"{name}: {len(items)} compared, {identical} identical")
        for field, count in sorted(diffs.items()):
            print(f"  differs in {field}: {count} cases")
        failed = failed or identical != len(items)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

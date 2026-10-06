#!/usr/bin/env python3
"""The first six pilot runs (PROTOCOL.md §13) in the format of results/matrix.csv.

Usage:
    python3 scripts/pilot_to_matrix.py --out PATH/matrix.csv [DIR]

For a cross-check of analyze.py against scripts/pilot_check.py on the same
data. It is not a result and is not written under results/: --out is required
and must lie outside this repository.

DIR (default ~/scout-corpora/ci-runs-2026-09-17_21) is only read. The first six
run documents in filename order become runs 1 to 6, seeds 101 to 106. Cases
are renamed p001… in the order of their original ids; the synthetic canary is
left out. Raw verdict: `comment+tool` when `tool_refused` is non-empty,
otherwise the recorded verdict, which is the settled one. A case the pilot tool
dropped in a run (no responses) becomes five rows with error_type `api`.
Columns the pilot does not have are empty; stratum is `skipped` and label
status `deferred` for every case, day_label A, started_at the run's creation
time. MANIFEST.txt, with the sha256 of the matrix, is written next to it, as
analyze.py requires.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_matrix  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DIR = Path.home() / "scout-corpora" / "ci-runs-2026-09-17_21"
RUNS = 6
SAMPLES = 5


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dir", nargs="?", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if REPO in args.out.resolve().parents:
        sys.exit("pilot_to_matrix: --out must be outside the repository")

    files = sorted(args.dir.glob("*/scout-judge/*.json"), key=lambda p: p.name)[:RUNS]
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in files]
    if len(docs) != RUNS:
        sys.exit(f"pilot_to_matrix: {len(docs)} run documents, need {RUNS}")
    originals = sorted({r["case_id"] for doc in docs for r in doc["results"] if not r.get("canary")})
    rename = {original: f"p{n:03d}" for n, original in enumerate(originals, 1)}

    rows = []
    for run, doc in enumerate(docs, 1):
        by_case = {r["case_id"]: r for r in doc["results"] if not r.get("canary")}
        if set(by_case) != set(originals):
            sys.exit(f"pilot_to_matrix: run {run} has another set of cases")
        for original, result in by_case.items():
            responses = result.get("responses") or []
            if len(responses) not in (0, SAMPLES):
                sys.exit(f"pilot_to_matrix: run {run}: {len(responses)} samples for a case")
            for sample in range(1, SAMPLES + 1):
                row = {name: "" for name in make_matrix.COLUMNS}
                row.update(public_id=rename[original], stratum="skipped", label_status="deferred",
                           day_label="A", text_empty="false", run=str(run), seed=str(100 + run),
                           sample=str(sample), started_at=doc["created_at"], attempts="0",
                           hook_failed="false")
                if not responses:
                    row["error_type"] = "api"
                else:
                    answer = json.loads(responses[sample - 1]["output"])
                    settled = answer["verdict"]
                    row["verdict_settled"] = settled
                    row["verdict_raw"] = "comment+tool" if answer.get("tool_refused") else settled
                    row["tool_refused"] = "true" if answer.get("tool_refused") else "false"
                rows.append(row)
    rows.sort(key=lambda r: (int(r["run"]), r["public_id"], int(r["sample"])))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(make_matrix.COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    manifest = f"{make_matrix.sha256(args.out)}  {args.out.name}\n"
    (args.out.parent / "MANIFEST.txt").write_text(manifest, encoding="utf-8")
    print(f"cases {len(originals)}, rows {len(rows)}")


if __name__ == "__main__":
    main()

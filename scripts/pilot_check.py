#!/usr/bin/env python3
"""Check of N=30 and the §6 bins on the pilot (PROTOCOL.md §13). No calls.

Usage:
    python3 scripts/pilot_check.py [DIR]

DIR (default ~/scout-corpora/ci-runs-2026-09-17_21) holds the 15 digline run
documents of scout's 145-case suite, as listed in its MANIFEST.txt. They are
only read. Output is aggregates only: no case id, no thread text.

Reading of the run documents:
- one sample = one entry of a result's `responses`; its `output` is scout's
  answer after `settle_tool`, so `verdict` is the settled verdict;
- raw verdict: `comment+tool` when `tool_refused` is non-empty (settle_tool
  at the pilot's scout commits sets it only when it downgrades a
  `comment+tool` to `comment`), otherwise the settled verdict;
- a result without `responses` is a case whose five samples the tool dropped
  after an error: zero valid samples in that run;
- the synthetic canary is the result carrying the `canary` field; excluded.

Bins and modal share as in §6, computed with exact fractions. Cases with
fewer than 25 valid samples are not binned; transitions and percentages are
over the cases binned in both the 75-sample reference and the 6-run subset.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from fractions import Fraction
from itertools import combinations
from pathlib import Path

DEFAULT_DIR = Path.home() / "scout-corpora" / "ci-runs-2026-09-17_21"
RUNS = 15
SAMPLES_PER_RUN = 5
SUBSET_RUNS = 6
MIN_VALID = 25
VERDICTS = ("skip", "upvote", "comment", "comment+tool")
BINS = ("stable", "rare", "unstable", "coin")
NEAR = Fraction(5, 100)
BOUNDARIES = (Fraction(8, 10), Fraction(6, 10))
TIE = "<tie>"


def load(directory: Path) -> tuple[list[dict[str, dict[str, list[str]]]], int, int]:
    """Per run (in filename order): case_id -> {"raw": [...], "settled": [...]}."""
    files = sorted(directory.glob("*/scout-judge/*.json"), key=lambda p: p.name)
    if len(files) != RUNS:
        sys.exit(f"expected {RUNS} run documents, found {len(files)}")
    runs = []
    canary_ids = set()
    refused = 0
    for path in files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        cases: dict[str, dict[str, list[str]]] = {}
        for result in doc["results"]:
            if result.get("canary"):
                canary_ids.add(result["case_id"])
                continue
            raw, settled = [], []
            for response in result.get("responses") or []:
                answer = json.loads(response["output"])
                verdict = answer["verdict"]
                if verdict not in VERDICTS:
                    sys.exit(f"unknown verdict in {path.name}")
                if answer.get("tool_refused"):
                    if verdict != "comment":
                        sys.exit(f"tool_refused on a non-comment verdict in {path.name}")
                    raw.append("comment+tool")
                    refused += 1
                else:
                    raw.append(verdict)
                settled.append(verdict)
            if len(raw) not in (0, SAMPLES_PER_RUN):
                sys.exit(f"unexpected sample count {len(raw)} in {path.name}")
            cases[result["case_id"]] = {"raw": raw, "settled": settled}
        runs.append(cases)
    ids = set(runs[0])
    if any(set(r) != ids for r in runs):
        sys.exit("case sets differ between runs")
    return runs, len(canary_ids), refused


def bin_of(counts: Counter) -> str | None:
    n = sum(counts.values())
    if n < MIN_VALID:
        return None
    share = Fraction(max(counts.values()), n)
    if share == 1:
        return "stable"
    if share >= Fraction(8, 10):
        return "rare"
    if share >= Fraction(6, 10):
        return "unstable"
    return "coin"


def run_verdict(samples: list[str]) -> str | None:
    if not samples:
        return None
    ranked = Counter(samples).most_common()
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return TIE
    return ranked[0][0]


def summary(values: list[float], fmt: str = "{:.0f}") -> str:
    return (f"median {fmt.format(statistics.median(values))}  "
            f"[min {fmt.format(min(values))}, max {fmt.format(max(values))}]")


def analyse(runs: list[dict[str, dict[str, list[str]]]], level: str) -> dict[str, bool]:
    ids = sorted(runs[0])
    per_run = [[Counter(r[c][level]) for r in runs] for c in ids]

    print(f"\n=== {level} verdict ===")

    # 2. Reference on all available samples.
    ref = []
    near = 0
    for counters in per_run:
        total = sum(counters, Counter())
        ref.append(bin_of(total))
        share = Fraction(max(total.values()), sum(total.values()))
        if any(abs(share - b) <= NEAR for b in BOUNDARIES):
            near += 1
    ref_counts = Counter(ref)
    print("\n2. Reference (all available samples, up to 75)")
    for b in BINS:
        print(f"   {b:<9} {ref_counts[b]:>4}")
    if ref_counts[None]:
        print(f"   not binned (<{MIN_VALID} valid) {ref_counts[None]}")
    print(f"   modal share within 0.05 of 0.8 or 0.6 (inclusive): {near}")

    # 3. All 6-run subsets.
    subsets = list(combinations(range(RUNS), SUBSET_RUNS))
    cells = {(a, b): [] for a in BINS for b in BINS}
    same, one, more, below, binned = [], [], [], [], []
    nonstable_to_stable = []
    for subset in subsets:
        table = Counter()
        n_below = 0
        for c, counters in enumerate(per_run):
            sub = sum((counters[i] for i in subset), Counter())
            b30 = bin_of(sub)
            if b30 is None:
                n_below += 1
                continue
            if ref[c] is None:
                continue
            table[(ref[c], b30)] += 1
        n = sum(table.values())
        dist = Counter()
        for (a, b), k in table.items():
            dist[abs(BINS.index(a) - BINS.index(b))] += k
        for key in cells:
            cells[key].append(table[key])
        binned.append(n)
        below.append(n_below)
        same.append(100 * dist[0] / n)
        one.append(100 * dist[1] / n)
        more.append(100 * (n - dist[0] - dist[1]) / n)
        nonstable_to_stable.append(sum(table[(a, "stable")] for a in BINS[1:]))

    print(f"\n3. {len(subsets)} subsets of {SUBSET_RUNS} runs out of {RUNS}")
    print("   bin at 75 (rows) x bin at 30 (columns): median [min, max] over subsets")
    print("   " + " " * 10 + "".join(f"{b:>16}" for b in BINS))
    for a in BINS:
        row = "".join(
            f"{'%d [%d,%d]' % (statistics.median(cells[(a, b)]), min(cells[(a, b)]), max(cells[(a, b)])):>16}"
            for b in BINS)
        print(f"   {a:<10}{row}")
    print(f"   cases binned in both:            {summary(binned)}")
    print(f"   same bin (%):                    {summary(same, '{:.2f}')}")
    print(f"   moved one bin (%):               {summary(one, '{:.2f}')}")
    print(f"   moved more than one bin (%):     {summary(more, '{:.2f}')}")
    print(f"   non-stable at 75, stable at 30:  {summary(nonstable_to_stable)}"
          f"  (non-stable at 75: {len(ids) - ref_counts['stable'] - ref_counts[None]})")
    print(f"   cases under {MIN_VALID} valid samples:     {summary(below)}")

    # 4. Within and between runs, all 15 runs.
    within = between = 0
    for c in ids:
        samples = [r[c][level] for r in runs]
        if any(len(set(s)) > 1 for s in samples):
            within += 1
        verdicts = {run_verdict(s) for s in samples if s}
        if len(verdicts) > 1:
            between += 1
    print(f"\n4. Over the {RUNS} runs (runs with no samples skipped)")
    print(f"   cases with at least one non-unanimous run:     {within}")
    print(f"   cases whose run verdict is not the same in all: {between}")

    crit_a = statistics.median(same) >= 80
    crit_b = statistics.median(more) < 2
    print("\n5. Criterion (medians over subsets)")
    print(f"   (a) same bin >= 80%:          {'met' if crit_a else 'NOT met'}")
    print(f"   (b) more than one bin < 2%:   {'met' if crit_b else 'NOT met'}")
    return {"a": crit_a, "b": crit_b}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dir", nargs="?", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args()

    runs, canaries, refused = load(args.dir)
    ids = sorted(runs[0])
    print(f"1. {RUNS} runs read; canary excluded: {canaries} case (in all runs)")
    print(f"   cases: {len(ids)}")
    print(f"   raw verdict reconstructed from tool_refused in all {RUNS} runs; "
          f"samples with tool_refused set: {refused}")
    for i, r in enumerate(runs, 1):
        dropped = sum(1 for c in ids if not r[c]["raw"])
        print(f"   run {i:>2}: cases with zero samples {dropped}")
    totals = Counter(sum(len(r[c]["raw"]) for r in runs) for c in ids)
    print("   valid samples per case (samples: cases): "
          + ", ".join(f"{k}: {v}" for k, v in sorted(totals.items(), reverse=True)))

    result = {level: analyse(runs, level) for level in ("raw", "settled")}
    print("\nSummary: " + "; ".join(
        f"{level}: (a) {'met' if r['a'] else 'NOT met'}, (b) {'met' if r['b'] else 'NOT met'}"
        for level, r in result.items()))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""The analyses of PROTOCOL.md §6, §7 and §8, from the matrix alone.

Usage:
    python3 scripts/analyze.py [--matrix results/matrix.csv] [--out results]

Reads only results/matrix.csv (written by make_matrix.py), after checking its
sha256 against MANIFEST.txt in the same directory: a missing MANIFEST, or a
different sha256, stops the script. Writes results/analysis.json and
results/tables.md. Nothing else is computed. The
output has no timestamp: two executions on the same matrix give identical files.

Definitions, including the details PROTOCOL.md left open:
- valid sample: a row with no error_type;
- threshold of valid samples: 5/6 of the samples planned for the runs present,
  rounded up (25 of 30 with six runs). A case below it is not binned: where
  bins are tabulated (§7.1, §8.1, §8.4 by judging day, §8.5, §8.7) it is the
  row "below threshold"; every other analysis (§7.2, §7.3, §8.2, §8.3, §8.4 by
  pair of runs) leaves it out and reports how many were left out;
- run verdict: the modal raw verdict of the run's valid samples; any tie is
  the one value "tie"; a run with no valid sample is left out of comparisons;
- proportions (§7.1, §7.2, §8.1, §8.5 counts aside, §8.7) are over all cases of
  the group, the row below the threshold included, with exact (Clopper-Pearson)
  95% intervals. In §7.1 and §7.2 a zero count is also given as an upper
  bound: the upper end of that interval;
- overall modal verdict in a tie (§7.1 breakdowns): the row "tie";
- breakdowns by modal verdict and by label status: whole corpus and per stratum;
- §7.3: only valid samples are permuted, errors keep their place; whole corpus
  only; one-sided p = (k + 1) / (N + 1), k the permutations at or above the
  observed value. random.Random(2606); for each permutation, the cases in
  public_id order, each shuffled with random.shuffle; a case whose valid samples
  are all equal is not shuffled and draws nothing;
- §8.1 and §8.7: per stratum and whole corpus, with intervals, no breakdowns;
- §8.2: modal settled verdict against the expected one, with scout's rule
  (`comment+tool` agrees with an expected `comment`); a tied modal verdict is
  left out and counted apart;
- §8.3: thinking tokens over every call that reports them, errors included;
  always / never / some as bin counts;
- §8.4: run day = Rome date of the run's first call; for each pair of runs, the
  number of cases whose two run verdicts differ, and whether the two runs fall
  on the same day;
- §8.5: bin counts only;
- §8.7: an error is the one value "error", over every planned sample.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime
from fractions import Fraction
from itertools import combinations
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent

BINS = ("stable", "rare flips", "unstable", "coin-like")  # PROTOCOL.md §6
BELOW = "below threshold"
ERROR_TYPES = ("api", "parse", "refusal", "max_tokens")
PERMUTATIONS = 10_000
PERMUTATION_SEED = 2606
ALPHA = 0.05
ROME = ZoneInfo("Europe/Rome")
TIE = "tie"
NO_VALID = "none"
ERROR = "error"


class Stop(Exception):
    """A refusal to run, with the reason."""


# --- Statistics ----------------------------------------------------------------


def _log_pmf(k: int, n: int, p: float) -> float:
    return (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
            + k * math.log(p) + (n - k) * math.log1p(-p))


def binom_cdf(x: int, n: int, p: float) -> float:
    """P(X <= x) for X ~ Binomial(n, p), 0 < p < 1."""
    if x < 0:
        return 0.0
    if x >= n:
        return 1.0
    logs = [_log_pmf(k, n, p) for k in range(x + 1)]
    top = max(logs)
    return min(1.0, math.exp(top) * sum(math.exp(v - top) for v in logs))


def _bisect(f, target: float, increasing: bool) -> float:
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if (f(mid) < target) == increasing:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def clopper_pearson(x: int, n: int, alpha: float = ALPHA) -> tuple[float, float]:
    if n == 0:
        raise ValueError("no trials")
    lower = 0.0 if x == 0 else _bisect(lambda p: 1 - binom_cdf(x - 1, n, p), alpha / 2, True)
    upper = 1.0 if x == n else _bisect(lambda p: binom_cdf(x, n, p), alpha / 2, False)
    return lower, upper


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation of average ranks. None if either side is constant."""
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def r6(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


# --- Definitions (§6) ------------------------------------------------------------


def threshold(planned: int) -> int:
    """5/6 of the planned samples, rounded up."""
    return math.ceil(Fraction(5, 6) * planned)


def modal(values: list[str]) -> tuple[int, list[str]]:
    """Count of the most common value and the values that reach it, sorted."""
    counts = Counter(values)
    top = max(counts.values())
    return top, sorted(v for v, c in counts.items() if c == top)


def bin_of(values: list[str], min_valid: int) -> str:
    if not values or len(values) < min_valid:
        return BELOW
    share = Fraction(modal(values)[0], len(values))
    if share == 1:
        return "stable"
    if share >= Fraction(8, 10):
        return "rare flips"
    if share >= Fraction(6, 10):
        return "unstable"
    return "coin-like"


def run_verdict(values: list[str]) -> str:
    if not values:
        return NO_VALID
    _, tied = modal(values)
    return tied[0] if len(tied) == 1 else TIE


def between_unstable(per_run: list[list[str]]) -> bool:
    return len({run_verdict(v) for v in per_run if v}) > 1


def non_unanimous(values: list[str]) -> bool:
    return len(set(values)) > 1


def agrees(said: str, wanted: str) -> bool:
    """scout's rule: `comment+tool` agrees with an expected `comment`; otherwise equality."""
    return said == wanted or (said == "comment+tool" and wanted == "comment")


# --- Cases -------------------------------------------------------------------------


class Case:
    def __init__(self, rows: list[dict], runs: list[int]) -> None:
        first = rows[0]
        self.id = first["public_id"]
        self.stratum = first["stratum"]
        self.label_status = first["label_status"]
        self.expected = first["expected"] or None
        self.day_label = first["day_label"]
        self.text_empty = first["text_empty"] == "true"
        self.rows = sorted(rows, key=lambda r: (int(r["run"]), int(r["sample"])))
        self.runs = runs

    def valid(self, column: str = "verdict_raw") -> list[str]:
        return [r[column] for r in self.rows if not r["error_type"]]

    def per_run(self) -> list[list[str]]:
        return [[r["verdict_raw"] for r in self.rows if int(r["run"]) == run and not r["error_type"]]
                for run in self.runs]

    def slots(self) -> list[list[str | None]]:
        return [[None if r["error_type"] else r["verdict_raw"]
                 for r in self.rows if int(r["run"]) == run] for run in self.runs]

    def errors(self) -> dict[str, int]:
        counts = Counter(r["error_type"] for r in self.rows if r["error_type"])
        return {t: counts[t] for t in ERROR_TYPES}

    def settled(self) -> list[str]:
        return self.valid("verdict_settled")

    def pass_fail(self) -> list[str]:
        return ["pass" if agrees(v, self.expected) else "fail" for v in self.settled()]

    def with_error_value(self) -> list[str]:
        return [ERROR if r["error_type"] else r["verdict_raw"] for r in self.rows]


def check_manifest(matrix: Path) -> str:
    """The matrix's sha256, which must be the one MANIFEST.txt next to it states."""
    manifest = matrix.parent / "MANIFEST.txt"
    if not manifest.exists():
        raise Stop(f"{manifest} is missing")
    stated = [line.split("  ", 1)[0] for line in manifest.read_text(encoding="utf-8").splitlines()
              if line.endswith(f"  {matrix.name}")]
    if len(stated) != 1:
        raise Stop(f"{manifest.name} does not state one sha256 for {matrix.name}")
    actual = hashlib.sha256(matrix.read_bytes()).hexdigest()
    if actual != stated[0]:
        raise Stop(f"sha256 of {matrix.name} is {actual}, {manifest.name} says {stated[0]}")
    return actual


def load_matrix(path: Path) -> tuple[list[Case], int]:
    """The cases, and the number of samples planned per case."""
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise Stop(f"{path} has no rows")
    runs = sorted({int(r["run"]) for r in rows})
    by_case: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_case[row["public_id"]].append(row)
    planned = {len(v) for v in by_case.values()}
    if len(planned) != 1:
        raise Stop("cases have different numbers of rows")
    return [Case(by_case[c], runs) for c in sorted(by_case)], planned.pop()


def groups_of(cases: list[Case]) -> dict[str, list[Case]]:
    out = {"all": cases}
    for stratum in sorted({c.stratum for c in cases}):
        out[stratum] = [c for c in cases if c.stratum == stratum]
    return out


# --- Building blocks -----------------------------------------------------------------


def proportion(x: int, n: int, zero_bound: bool = False) -> dict:
    if n == 0:
        return {"count": x, "n": 0}
    lo, hi = clopper_pearson(x, n)
    out = {"count": x, "n": n, "proportion": r6(x / n), "ci95": [r6(lo), r6(hi)]}
    if zero_bound and x == 0:
        out["upper_bound"] = r6(hi)
    return out


def bin_counts(bins: list[str]) -> dict[str, int]:
    counts = Counter(bins)
    return {b: counts[b] for b in (*BINS, BELOW)}


def distribution(cases: list[Case], values_of, min_valid: int, zero_bound: bool) -> dict:
    """Per stratum and whole corpus: bins over all cases, with intervals."""
    out = {}
    for g, members in groups_of(cases).items():
        counts = bin_counts([bin_of(values_of(c), min_valid) for c in members])
        out[g] = {"cases": len(members),
                  "bins": {b: proportion(counts[b], len(members), zero_bound)
                           for b in (*BINS, BELOW)}}
    return out


def modal_row(values: list[str]) -> str:
    if not values:
        return NO_VALID
    _, tied = modal(values)
    return tied[0] if len(tied) == 1 else TIE


def breakdowns(cases: list[Case], min_valid: int) -> dict:
    """Counts by overall modal raw verdict and by label status, no test (§7.1)."""
    out = {}
    for scope, members in groups_of(cases).items():
        by_modal: dict[str, list[str]] = defaultdict(list)
        by_status: dict[str, list[str]] = defaultdict(list)
        for case in members:
            b = bin_of(case.valid(), min_valid)
            by_modal[modal_row(case.valid())].append(b)
            by_status[case.label_status].append(b)
        out[scope] = {"by_modal_verdict": {m: bin_counts(v) for m, v in sorted(by_modal.items())},
                      "by_label_status": {s: bin_counts(v) for s, v in sorted(by_status.items())}}
    return out


# --- §7.3 ---------------------------------------------------------------------------


def permuted_runs(slots: list[list[str | None]], rng: random.Random) -> list[list[str]]:
    """Valid samples shuffled across the runs; each run keeps its number of valid samples."""
    valid = [v for s in slots for v in s if v is not None]
    if len(set(valid)) > 1:
        rng.shuffle(valid)
    out, start = [], 0
    for s in slots:
        count = sum(v is not None for v in s)
        out.append(valid[start:start + count])
        start += count
    return out


def permutation_test(cases: list[Case], seed: int = PERMUTATION_SEED,
                     permutations: int = PERMUTATIONS) -> dict:
    slots = [c.slots() for c in cases]
    observed = sum(between_unstable([[v for v in run if v is not None] for run in s]) for s in slots)
    rng = random.Random(seed)
    reference: Counter = Counter()
    for _ in range(permutations):
        reference[sum(between_unstable(permuted_runs(s, rng)) for s in slots)] += 1
    at_least = sum(v for k, v in reference.items() if k >= observed)
    return {"cases": len(cases), "observed": observed, "permutations": permutations,
            "seed": seed, "reference": {str(k): v for k, v in sorted(reference.items())},
            "p_one_sided": r6((at_least + 1) / (permutations + 1))}


# --- The analysis ---------------------------------------------------------------------


def analyse(cases: list[Case], planned: int, permutations: int = PERMUTATIONS) -> dict:
    min_valid = threshold(planned)
    binned = [c for c in cases if bin_of(c.valid(), min_valid) != BELOW]
    below = len(cases) - len(binned)
    result: dict = {"threshold": {"planned_samples": planned, "min_valid": min_valid}}

    # §6 and §7.4: per case.
    result["cases"] = [{
        "public_id": c.id, "stratum": c.stratum, "valid": len(c.valid()),
        "modal_count": modal(c.valid())[0] if c.valid() else 0,
        "modal_share": r6(modal(c.valid())[0] / len(c.valid())) if c.valid() else None,
        "bin": bin_of(c.valid(), min_valid),
        "run_verdicts": [run_verdict(v) for v in c.per_run()],
        "non_unanimous_runs": sum(non_unanimous(v) for v in c.per_run()),
        "between_run_unstable": between_unstable(c.per_run()),
        "errors": c.errors(),
    } for c in cases]

    # §7.1
    result["7.1"] = {"distribution": distribution(cases, Case.valid, min_valid, zero_bound=True),
                     "breakdowns": breakdowns(cases, min_valid)}

    # §7.2
    s72 = {}
    for g, members in groups_of(cases).items():
        if g == "all":
            continue
        kept = [c for c in members if c in binned]
        n = len(kept)
        s72[g] = {"cases": n, "below_threshold_left_out": len(members) - n,
                  "non_unanimous": proportion(
                      sum(any(non_unanimous(v) for v in c.per_run()) for c in kept), n, True),
                  "between_run_unstable": proportion(
                      sum(between_unstable(c.per_run()) for c in kept), n, True)}
    result["7.2"] = s72

    # §7.3
    result["7.3"] = {**permutation_test(binned, permutations=permutations),
                     "below_threshold_left_out": below}

    # §8.1
    labelled = [c for c in cases if c.label_status == "labelled"]
    result["8.1"] = {
        "settled": distribution(cases, Case.settled, min_valid, zero_bound=False),
        "pass_fail": distribution(labelled, Case.pass_fail, min_valid, zero_bound=False)}

    # §8.2
    s82 = {}
    for g, members in groups_of(labelled).items():
        if g == "all":
            continue
        kept = [c for c in members if c in binned]
        tally = Counter()
        cross: dict[str, list[str]] = defaultdict(list)
        for c in kept:
            _, tied = modal(c.settled())
            if len(tied) > 1:
                tally["tied_left_out"] += 1
                continue
            outcome = "agree" if agrees(tied[0], c.expected) else "disagree"
            tally[outcome] += 1
            cross[outcome].append(bin_of(c.valid(), min_valid))
        s82[g] = {"cases": len(kept), "below_threshold_left_out": len(members) - len(kept),
                  **{k: tally[k] for k in ("agree", "disagree", "tied_left_out")},
                  "bins": {k: bin_counts(cross[k]) for k in ("agree", "disagree")}}
    result["8.2"] = s82

    # §8.3
    xs, ys = [], []
    groups: dict[str, list[str]] = {"always": [], "never": [], "some": []}
    no_tokens = 0
    for c in binned:
        tokens = [int(r["thinking_tokens"]) for r in c.rows if r["thinking_tokens"] != ""]
        if not tokens:
            no_tokens += 1
            continue
        values = c.valid()
        xs.append(sum(tokens) / len(tokens))
        ys.append(1 - modal(values)[0] / len(values))
        present = sum(t > 0 for t in tokens)
        group = "always" if present == len(tokens) else "never" if present == 0 else "some"
        groups[group].append(bin_of(values, min_valid))
    result["8.3"] = {"cases": len(xs), "below_threshold_left_out": below,
                     "no_thinking_tokens": no_tokens,
                     "spearman_rho": r6(spearman(xs, ys)) if len(xs) > 1 else None,
                     "groups": {g: {"cases": len(v), "bins": bin_counts(v)} for g, v in groups.items()}}

    # §8.4
    by_day: dict[str, list[str]] = defaultdict(list)
    for c in cases:
        by_day[c.day_label].append(bin_of(c.valid(), min_valid))
    first_call: dict[int, datetime] = {}
    for c in cases:
        for r in c.rows:
            t = datetime.fromisoformat(r["started_at"])
            run = int(r["run"])
            first_call[run] = min(first_call.get(run, t), t)
    run_day = {run: t.astimezone(ROME).date().isoformat() for run, t in sorted(first_call.items())}
    runs = cases[0].runs
    verdicts = {c.id: c.per_run() for c in binned}
    pairs = []
    for a, b in combinations(range(len(runs)), 2):
        differ = sum(1 for per_run in verdicts.values()
                     if per_run[a] and per_run[b]
                     and run_verdict(per_run[a]) != run_verdict(per_run[b]))
        pairs.append({"runs": [runs[a], runs[b]],
                      "same_day": run_day[runs[a]] == run_day[runs[b]],
                      "cases_differing": differ})
    result["8.4"] = {"by_day_label": {k: bin_counts(v) for k, v in sorted(by_day.items())},
                     "run_day": {str(k): v for k, v in run_day.items()},
                     "run_pairs": {"cases": len(binned), "below_threshold_left_out": below,
                                   "pairs": pairs}}

    # §8.5
    empty = [c for c in cases if c.text_empty]
    result["8.5"] = ({g: bin_counts([bin_of(c.valid(), min_valid) for c in m])
                      for g, m in groups_of(empty).items()} if empty else {})

    # §8.6
    s86 = {}
    for run in runs:
        rows = [r for c in cases for r in c.rows if int(r["run"]) == run]
        counts = Counter(r["error_type"] for r in rows if r["error_type"])
        s86[str(run)] = {"calls": len(rows), "errors": sum(counts.values()),
                         "rate": r6(sum(counts.values()) / len(rows)),
                         "by_type": {t: counts[t] for t in ERROR_TYPES}}
    result["8.6"] = s86

    # §8.7: every planned sample counts, so no case falls below the threshold.
    result["8.7"] = distribution(cases, Case.with_error_value, 0, zero_bound=False)
    return result


# --- Tables ---------------------------------------------------------------------------


def pct(entry: dict) -> str:
    if entry.get("n", 0) == 0:
        return str(entry["count"])
    lo, hi = entry["ci95"]
    if entry["count"] == 0:
        return f"0 / {entry['n']} (≤ {100 * hi:.1f}%)"
    return (f"{entry['count']} / {entry['n']} ({100 * entry['proportion']:.1f}%, "
            f"{100 * lo:.1f}–{100 * hi:.1f})")


def dist_table(dist: dict) -> list[str]:
    groups = list(dist)
    lines = ["| Bin | " + " | ".join(f"{g} ({dist[g]['cases']})" for g in groups) + " |",
             "|---|" + "---|" * len(groups)]
    for b in (*BINS, BELOW):
        lines.append(f"| {b} | " + " | ".join(pct(dist[g]["bins"][b]) for g in groups) + " |")
    return lines


def counts_table(rows: dict[str, dict[str, int]], first: str) -> list[str]:
    cols = (*BINS, BELOW)
    lines = [f"| {first} | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for name, counts in rows.items():
        lines.append(f"| {name} | " + " | ".join(str(counts[c]) for c in cols) + " |")
    return lines


def tables(result: dict) -> str:
    t = result["threshold"]
    out = ["# Results", "",
           f"Planned samples per case: {t['planned_samples']}; threshold of valid samples: "
           f"{t['min_valid']}. Intervals: exact 95%.", ""]
    out += ["## 7.1 Bins, raw verdict", "", *dist_table(result["7.1"]["distribution"]), ""]
    for scope, entry in result["7.1"]["breakdowns"].items():
        out += [f"By modal verdict ({scope}):", "", *counts_table(entry["by_modal_verdict"], "modal"), ""]
        out += [f"By label status ({scope}):", "", *counts_table(entry["by_label_status"], "label"), ""]
    out += ["## 7.2 Disagreement within and between runs", "",
            "| Stratum | Cases | Non-unanimous | Between-run unstable | Below threshold, left out |",
            "|---|---|---|---|---|"]
    for g, e in result["7.2"].items():
        out.append(f"| {g} | {e['cases']} | {pct(e['non_unanimous'])} | "
                   f"{pct(e['between_run_unstable'])} | {e['below_threshold_left_out']} |")
    e = result["7.3"]
    out += ["", "## 7.3 Permutation test", "",
            f"{e['cases']} cases ({e['below_threshold_left_out']} below the threshold left out). "
            f"Between-run unstable cases observed: {e['observed']}. {e['permutations']} permutations, "
            f"seed {e['seed']}. One-sided p: {e['p_one_sided']}.", "",
            "| Statistic | Permutations |", "|---|---|",
            *[f"| {k} | {v} |" for k, v in e["reference"].items()], ""]
    out += ["## 7.4 Errors by case", ""]
    with_errors = [c for c in result["cases"] if any(c["errors"].values())]
    out += [f"Cases with no error: {len(result['cases']) - len(with_errors)}.", ""]
    if with_errors:
        out += ["| Public id | Bin | Valid | " + " | ".join(ERROR_TYPES) + " |",
                "|---|---|---|" + "---|" * len(ERROR_TYPES)]
        out += [f"| {c['public_id']} | {c['bin']} | {c['valid']} | "
                + " | ".join(str(c["errors"][t]) for t in ERROR_TYPES) + " |" for c in with_errors]
        out.append("")
    out += ["## 8.1 Settled verdict", "", *dist_table(result["8.1"]["settled"]), "",
            "Pass/fail, labelled cases:", "", *dist_table(result["8.1"]["pass_fail"]), ""]
    out += ["## 8.2 Modal settled verdict against the expected verdict", "",
            "| Stratum | Cases | Agree | Disagree | Tied, left out | Below threshold, left out |",
            "|---|---|---|---|---|---|"]
    for g, e in result["8.2"].items():
        out.append(f"| {g} | {e['cases']} | {e['agree']} | {e['disagree']} | "
                   f"{e['tied_left_out']} | {e['below_threshold_left_out']} |")
    for g, e in result["8.2"].items():
        out += ["", f"Bins of the raw verdict by agreement ({g}):", "", *counts_table(e["bins"], "agreement")]
    e = result["8.3"]
    out += ["", "## 8.3 Thinking tokens", "",
            f"Spearman rho, mean thinking tokens against 1 − modal share: {e['spearman_rho']} "
            f"({e['cases']} cases; {e['below_threshold_left_out']} below the threshold and "
            f"{e['no_thinking_tokens']} with no thinking tokens reported left out).", "",
            *counts_table({k: v["bins"] for k, v in e["groups"].items()}, "thinking"), ""]
    out += ["## 8.4 Judging day and run day", "",
            *counts_table(result["8.4"]["by_day_label"], "judging day"), "",
            "Run day: " + ", ".join(f"run {k} {v}" for k, v in result["8.4"]["run_day"].items()), "",
            "| Runs | Same day | Cases with different run verdicts |", "|---|---|---|",
            *[f"| {p['runs'][0]}–{p['runs'][1]} | {'yes' if p['same_day'] else 'no'} | "
              f"{p['cases_differing']} |" for p in result["8.4"]["run_pairs"]["pairs"]], "",
            f"{result['8.4']['run_pairs']['cases']} cases; "
            f"{result['8.4']['run_pairs']['below_threshold_left_out']} below the threshold left out.", ""]
    out += ["## 8.5 Empty text", ""]
    out += counts_table(result["8.5"], "group") if result["8.5"] else ["No case with empty text."]
    out += ["", "## 8.6 Errors by run", "", "| Run | Calls | Errors | Rate | " + " | ".join(ERROR_TYPES) + " |",
            "|---|---|---|---|" + "---|" * len(ERROR_TYPES)]
    for run, v in result["8.6"].items():
        out.append(f"| {run} | {v['calls']} | {v['errors']} | {v['rate']} | "
                   + " | ".join(str(v["by_type"][t]) for t in ERROR_TYPES) + " |")
    out += ["", "## 8.7 Sensitivity: an error as its own value", "", *dist_table(result["8.7"]), ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--matrix", type=Path, default=REPO / "results" / "matrix.csv")
    parser.add_argument("--out", type=Path, default=REPO / "results")
    args = parser.parse_args(argv)
    try:
        digest = check_manifest(args.matrix)
        cases, planned = load_matrix(args.matrix)
    except Stop as exc:
        sys.exit(f"analyze: {exc}")
    result = {"matrix_sha256": digest, **analyse(cases, planned)}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "analysis.json").write_bytes(
        (json.dumps(result, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))
    (args.out / "tables.md").write_bytes((tables(result) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()

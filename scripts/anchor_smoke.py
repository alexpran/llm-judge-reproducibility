#!/usr/bin/env python3
"""Smoke check on Tamba's seven items (PROTOCOL.md §9.3). Real calls.

Usage:
    python3 scripts/anchor_smoke.py HARNESS [--dry-run]

HARNESS is the local copy of the harness: the Zenodo zip (record 20674090,
v1.1) or the directory that holds it. The zip is checked against its sha256
and read in place, never extracted. The items, the grader prompt and the grade
extraction pattern are read from src/repro_v11_extended.py inside it, as
literals (ast.literal_eval): nothing of the harness is executed, and nothing of
it is copied into this repository.

One call per item, through run.py's call loop: the same client, the response
recorder, the same fields per line. Model and thinking as in §2, no sampling
parameters, no output_config: the prompt is the grader's, sent as the single
user message, as the harness sends it. The extracted grade goes in `grade`;
scout's verdict fields stay null. A reply without a grade is a `parse` error
(`max_tokens` if cut at the cap).

Lines go to raw/anchor/anchor.jsonl with case ids item1..item7, run = 0 and
seed = null. The script refuses to overwrite an existing output file. The log
records the SDK version, the repository commit, the environment and the zip.

--dry-run builds the seven requests and prints their number and sha256, with
neither the SDK nor the network.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import judge  # noqa: E402
import run  # noqa: E402

OUT = run.REPO / "raw" / "anchor" / "anchor.jsonl"

# The v1.1 zip as downloaded from Zenodo (its md5 matches the record).
HARNESS_ZIP_SHA256 = "ea6a4f61de03896ffebed4b933920c2f2e8a32f25be5417a5cdc4aa949a57949"
SOURCE = "src/repro_v11_extended.py"
NAMES = ("ITEMS", "INSPECT_DEFAULT_INSTRUCTIONS", "AISEV_TEMPLATE", "GRADE_PATTERN")
ITEM_COUNT = 7


class Harness:
    """What the smoke check takes from the harness, held in memory only."""

    def __init__(self, items: list[dict], instructions: str, template: str,
                 pattern: str, zip_sha256: str) -> None:
        self.items = items
        self.instructions = instructions
        self.template = template
        self.pattern = pattern
        self.zip_sha256 = zip_sha256

    def prompt(self, item: dict) -> str:
        """As the harness's _prompt builds it."""
        return self.template.format(q=item["q"], s=item["s"], c=item["c"],
                                    instructions=self.instructions)

    def read(self, text: str) -> dict:
        """As the harness's _extract reads it, except that no grade is an
        error rather than a placeholder grade."""
        found = re.search(self.pattern, text or "")
        if not found:
            raise ValueError("no grade in the reply")
        return {"grade": found.group(1).upper()}


def harness_zip(path: Path) -> Path:
    if path.is_file():
        return path
    found = sorted(path.glob("*.zip"))
    if len(found) != 1:
        raise run.Stop(f"{path} holds {len(found)} zip files, expected one")
    return found[0]


def load_harness(path: Path, expected_sha256: str | None = HARNESS_ZIP_SHA256) -> Harness:
    archive = harness_zip(path)
    actual = run.sha256(archive)
    if expected_sha256 is not None and actual != expected_sha256:
        raise run.Stop(f"sha256 of {archive.name} is {actual}, expected {expected_sha256}")
    with zipfile.ZipFile(archive) as opened:
        members = [n for n in opened.namelist() if n.endswith("/" + SOURCE)]
        if len(members) != 1:
            raise run.Stop(f"{archive.name} holds {len(members)} copies of {SOURCE}")
        source = opened.read(members[0]).decode("utf-8")
    values: dict[str, list[Any]] = {name: [] for name in NAMES}
    for node in ast.parse(source).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in values):
            values[node.targets[0].id].append(ast.literal_eval(node.value))
    for name, found in values.items():
        if len(found) != 1:
            raise run.Stop(f"{SOURCE} assigns {name} {len(found)} times, expected once")
    items, instructions, template, pattern = (values[name][0] for name in NAMES)
    if (not isinstance(items, list) or len(items) != ITEM_COUNT
            or any(not isinstance(i, dict) or set(i) != {"q", "c", "s"}
                   or not all(isinstance(v, str) for v in i.values()) for i in items)):
        raise run.Stop(f"{SOURCE}: ITEMS is not {ITEM_COUNT} items with q, c, s")
    if not all(isinstance(v, str) for v in (instructions, template, pattern)):
        raise run.Stop(f"{SOURCE}: the prompt and the pattern must be strings")
    harness = Harness(items, instructions, template, pattern, actual)
    harness.prompt(items[0])  # fails here if the template does not take the four slots
    re.compile(pattern)
    return harness


def build_request(prompt: str) -> dict[str, Any]:
    """Model, max_tokens and thinking of §2; no output_config, no sampling."""
    return {
        "model": judge.MODEL,
        "max_tokens": judge.JUDGE_MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
        "thinking": judge.JUDGE_THINKING,
    }


def requests(harness: Harness) -> list[tuple[str, dict]]:
    return [(f"item{n}", build_request(harness.prompt(item)))
            for n, item in enumerate(harness.items, start=1)]


def dry_run(harness: Harness) -> tuple[int, str]:
    digest = hashlib.sha256()
    built = requests(harness)
    for _, request in built:
        digest.update(run.canonical(request).encode("utf-8") + b"\n")
    return len(built), digest.hexdigest()


def smoke(harness: Harness, client: Any, out: Path, log_path: Path,
          header: str) -> int:
    """One call per item. Returns the number of lines written."""
    hooks = run.hooks_of(client)
    if out.exists():
        raise run.Stop(f"{out} exists; the anchor smoke check is not resumed")
    out.parent.mkdir(parents=True, exist_ok=True)
    run.log(log_path, header)
    recorder = run.ResponseRecorder()
    hooks.append(recorder)
    made = 0
    try:
        with out.open("a", encoding="utf-8") as handle:
            for case_id, request in requests(harness):
                line = run.call_once(client, request, {}, recorder, read=harness.read)
                run.log_hook_failures(log_path, recorder, f"{case_id} sample 1")
                run.append_line(handle, {"case_id": case_id, "stratum": None, "run": 0,
                                         "seed": None, "sample": 1, "grade": None,
                                         **line})
                made += 1
    finally:
        hooks.remove(recorder)
    run.log(log_path, f"end anchor: {made} calls")
    return made


def main(argv: list[str] | None = None,
         make_client: Callable[[], Any] | None = None,
         out: Path = OUT, expected_sha256: str | None = HARNESS_ZIP_SHA256) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("harness", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        harness = load_harness(args.harness.expanduser(), expected_sha256)
        if args.dry_run:
            count, digest = dry_run(harness)
            print(f"requests  {count} (1 per item)")
            print(f"sha256    {digest}")
            return
        pinned = run.pinned_sdk()
        if make_client is None:
            import anthropic

            version = anthropic.__version__
            if version != pinned:
                raise run.Stop(f"anthropic {version} is installed, "
                               f"requirements.txt pins {pinned}")
            client = anthropic.Anthropic()
        else:
            client, version = make_client(), "injected"
        repo_sha, dirty = run.repo_state()
        header = (f"start anchor items={len(harness.items)} sdk=anthropic {version} "
                  f"repo={repo_sha} dirty_paths={len(dirty)} {run.environment()} "
                  f"harness_zip_sha256={harness.zip_sha256} source={SOURCE}")
        made = smoke(harness, client, out, out.with_suffix(".log"), header)
    except run.Stop as exc:
        sys.exit(f"anchor_smoke: {exc}")
    print(f"done: {made} calls -> {out}")


if __name__ == "__main__":
    main()

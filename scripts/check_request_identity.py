#!/usr/bin/env python3
"""Show that scripts/judge.py and run.py send the request scout sends in production.

Usage (with an interpreter where scout and its dependencies import):
    PYTHONDONTWRITEBYTECODE=1 SCOUT/.venv/bin/python \
        scripts/check_request_identity.py --scout SCOUT --cases corpus/cases.jsonl

Two levels, each on every case:

1. Arguments. The request is built by scout's own ScoutJudge, through its full
   call path, with a fake client whose messages.create captures its keyword
   arguments and raises; and by scripts/judge.py. The two argument sets are
   serialised as canonical JSON and compared by sha256.

2. HTTP. The SDK's transport is replaced by a function that records the request
   and answers with a fixed reply: nothing leaves on the network. The request
   is sent through
     a) production: ScoutJudge with the client scout builds itself
        (digline_anthropic's build_client, a plain anthropic.Anthropic());
     b) the experiment: scripts/judge.py and run.call_once, on a plain
        anthropic.Anthropic() with run.py's response recorder attached.
   Method, URL, every header in order and the body bytes are compared. Only the
   authentication headers and x-stainless-retry-count are left out. The API key
   is a placeholder set here, the same for both paths.

Negative controls, both expected to give 0 identical: one space added to the
system prompt (both levels), and one header added on path b (HTTP level).

Cases: the 144 of scout's cases.json (vars as stored there) and the 533 of
corpus/cases.jsonl (vars through each side's own judge_vars).
Only counts, header names and the names of differing fields are printed, never
case content or header values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import judge  # noqa: E402
import run  # noqa: E402

# Left out of the HTTP comparison: authentication, and the attempt counter the
# SDK sets per try. Nothing else.
EXCLUDED_HEADERS = {"x-api-key", "authorization", "x-stainless-retry-count"}
CONTROL_HEADER = "x-identity-check-control"
PLACEHOLDER_KEY = "identity-check-placeholder-not-a-key"

REPLY = {
    "id": "msg_identity_check", "type": "message", "role": "assistant",
    "model": judge.MODEL, "stop_reason": "end_turn", "stop_sequence": None,
    "content": [{"type": "text",
                 "text": json.dumps({"verdict": "skip", "why": "x", "angle": ""})}],
    "usage": {"input_tokens": 1, "output_tokens": 1},
}


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


# --- HTTP level ----------------------------------------------------------------


class Wire:
    """Stands in for httpx2.HTTPTransport.handle_request: records each request
    and answers with REPLY. No socket is opened."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def handle_request(self, transport: Any, request: Any) -> Any:
        import httpx2

        request.read()
        self.sent.append({
            "method": request.method,
            "url": str(request.url),
            "headers": [(k.lower(), v) for k, v in request.headers.multi_items()],
            "body": request.content,
        })
        return httpx2.Response(200, json=REPLY, request=request,
                               headers={"request-id": "req_identity_check"})

    def capture(self, send: Callable[[], Any]) -> dict:
        before = len(self.sent)
        send()
        made = self.sent[before:]
        if len(made) != 1:
            raise RuntimeError(f"expected one HTTP request, saw {len(made)}")
        return made[0]


def compared(request: dict) -> dict:
    return {**request, "headers": [(k, v) for k, v in request["headers"]
                                   if k not in EXCLUDED_HEADERS]}


def http_differences(a: dict, b: dict) -> list[str]:
    a, b = compared(a), compared(b)
    found = [part for part in ("method", "url", "body") if a[part] != b[part]]
    if a["headers"] != b["headers"]:
        names_a = [k for k, _ in a["headers"]]
        names_b = [k for k, _ in b["headers"]]
        values_a, values_b = dict(a["headers"]), dict(b["headers"])
        for name in sorted(set(names_a) | set(names_b)):
            if name not in values_a or name not in values_b:
                found.append(f"header {name} (present on one side only)")
            elif names_a.count(name) != names_b.count(name) or values_a[name] != values_b[name]:
                found.append(f"header {name}")
        if not found or (names_a != names_b and sorted(names_a) == sorted(names_b)):
            found.append("header order")
    return found


def experiment_path(anthropic: Any, **client_options: Any) -> Callable[[dict, tuple], None]:
    """run.call_once on a plain client with run.py's recorder attached."""
    client = anthropic.Anthropic(**client_options)
    recorder = run.ResponseRecorder()
    run.hooks_of(client).append(recorder)

    def send(vars: dict, prompts: tuple[str, str]) -> None:
        line = run.call_once(client, judge.build_request(vars, prompts), vars, recorder)
        if line["error_type"] is not None or line["attempt_statuses"] != [200]:
            raise RuntimeError(f"experiment path: {line['error_type']} {line['error']} "
                               f"statuses {line['attempt_statuses']}")
    return send


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scout", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(args.scout.resolve()))
    import scout  # noqa: E402 — scout's own module, read only
    from digline.run import Case  # noqa: E402

    prompts = judge.load_prompts()
    spaced = (prompts[0] + " ", prompts[1])

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

    def report(label: str, total: int, identical: int, diffs: dict[str, int],
               expected_identical: int) -> None:
        nonlocal failed
        print(f"{label}: {total} compared, {identical} identical")
        for field, count in sorted(diffs.items()):
            print(f"  differs in {field}: {count} cases")
        failed = failed or identical != expected_identical

    # Level 1: arguments.
    production_args = scout.build_judge(client=FakeClient())

    def scout_request(case_id: str, vars: dict) -> dict:
        try:
            production_args(Case(id=case_id, vars=vars))
        except Captured as captured:
            return captured.kwargs
        raise RuntimeError("ScoutJudge returned without calling the client")

    print("== arguments")
    for name, items in sets:
        identical = control = 0
        diffs: dict[str, int] = {}
        for case_id, scout_vars, our_vars in items:
            theirs = scout_request(case_id, scout_vars)
            ours = judge.build_request(our_vars, prompts)
            if digest(theirs) == digest(ours):
                identical += 1
            else:
                for field in differing_fields(theirs, ours):
                    diffs[field] = diffs.get(field, 0) + 1
            control += digest(theirs) == digest(judge.build_request(our_vars, spaced))
        report(name, len(items), identical, diffs, len(items))
        report(f"{name}, control: space in system prompt", len(items), control, {}, 0)

    # Level 2: HTTP.
    import anthropic
    import httpx2

    if anthropic.__version__ != run.pinned_sdk():
        sys.exit(f"anthropic {anthropic.__version__} is installed, "
                 f"requirements.txt pins {run.pinned_sdk()}")
    os.environ["ANTHROPIC_API_KEY"] = PLACEHOLDER_KEY
    wire = Wire()
    httpx2.HTTPTransport.handle_request = (  # type: ignore[assignment]
        lambda transport, request: wire.handle_request(transport, request))

    production = scout.build_judge()  # client built on first use, as in scout
    experiment = experiment_path(anthropic)
    with_header = experiment_path(anthropic, default_headers={CONTROL_HEADER: "1"})

    print("== HTTP (method, URL, headers except "
          f"{', '.join(sorted(EXCLUDED_HEADERS))}, body)")
    names: list[str] | None = None
    for name, items in sets:
        identical = spaced_same = header_same = 0
        diffs: dict[str, int] = {}
        spaced_diffs: dict[str, int] = {}
        header_diffs: dict[str, int] = {}
        for case_id, scout_vars, our_vars in items:
            theirs = wire.capture(lambda: production(Case(id=case_id, vars=scout_vars)))
            ours = wire.capture(lambda: experiment(our_vars, prompts))
            names = names or [k for k, _ in theirs["headers"]]
            for target, counts, sent in (
                ("main", diffs, ours),
                ("spaced", spaced_diffs, wire.capture(lambda: experiment(our_vars, spaced))),
                ("header", header_diffs, wire.capture(lambda: with_header(our_vars, prompts))),
            ):
                differences = http_differences(theirs, sent)
                if not differences:
                    if target == "main":
                        identical += 1
                    elif target == "spaced":
                        spaced_same += 1
                    else:
                        header_same += 1
                for field in differences:
                    counts[field] = counts.get(field, 0) + 1
        report(name, len(items), identical, diffs, len(items))
        report(f"{name}, control: space in system prompt", len(items), spaced_same,
               spaced_diffs, 0)
        report(f"{name}, control: header {CONTROL_HEADER} added on path b", len(items),
               header_same, header_diffs, 0)

    print("headers sent by production, in order (values not shown):")
    for header in names or []:
        print(f"  {header}{'  (excluded)' if header in EXCLUDED_HEADERS else ''}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

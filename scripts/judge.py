"""The judge under measurement: request construction and reply handling.

Copied, not imported, so that this repository depends on neither scout nor
digline. No behaviour is changed; function bodies are verbatim except where a
note below says otherwise.

From scout at commit dfd5187ac0ddaa5968c6b777a1f56f406f21203b, scout.py:
    MODEL                  line 144
    JUDGE_MAX_TOKENS       line 152
    JUDGE_THINKING         line 158
    TEXT_MAX_CHARS         line 169
    VERDICTS               line 192
    VERDICT_TOOL           line 199
    JUDGE_SCHEMA           line 274
    first_json_object      line 639
    MIN_QUOTE_CHARS        line 684
    _QUOTE_MARKS           line 692
    _flat                  line 695
    quoted_sentence        line 703
    settle_tool            line 726
    ScoutJudge._complete   line 769  -> build_request (request dict only)
    ScoutJudge.parse       line 831  -> parse (a function instead of a method)
    judge_vars             line 861

From digline 0.23.0 / digline-anthropic 0.5.3, which ScoutJudge inherits from:
    digline/targets/template.py   _SLOT, PromptTemplate.render -> render
        (scout's vars are always strings, so only the string branch of
        render_value is kept; any other type is refused)
    digline_anthropic/client.py   text_of
    digline_anthropic/pricing.py  claude-sonnet-5 list prices (read 2026-08-27),
        used only for the --max-usd estimate in run.py
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

MODEL = "claude-sonnet-5"
JUDGE_MAX_TOKENS = 2000
JUDGE_THINKING = {"type": "adaptive"}
TEXT_MAX_CHARS = 1500

VERDICTS = ("comment", "comment+tool", "upvote", "skip")
VERDICT_TOOL = "comment+tool"

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"enum": list(VERDICTS)},
        "why": {"type": "string", "minLength": 1},
        "angle": {"type": "string"},
    },
    "required": ["verdict", "why", "angle"],
    "additionalProperties": False,
}

# USD per million tokens, claude-sonnet-5 (digline_anthropic.pricing).
PRICE_PER_MTOK = {
    "input_tokens": 3.0,
    "output_tokens": 15.0,
    "cache_read_input_tokens": 0.30,
    "cache_creation_input_tokens": 3.75,
}


# --- Prompt rendering (digline) ------------------------------------------------

_SLOT = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def render(template: str, provided: Mapping[str, str]) -> str:
    missing = set(_SLOT.findall(template)) - set(provided)
    if missing:
        raise ValueError(f"vars do not provide {', '.join(sorted(missing))}")

    def value(m: re.Match[str]) -> str:
        found = provided[m.group(1)]
        if not isinstance(found, str):
            raise ValueError(f"variable {m.group(1)!r} is not a string")
        return found

    return _SLOT.sub(value, template)


def load_prompts(prompts_dir: Path = PROMPTS_DIR) -> tuple[str, str]:
    """(system template, user template), decoded as digline decodes them."""
    system = (prompts_dir / "JUDGE.md").read_bytes().decode("utf-8")
    user = (prompts_dir / "THREAD.md").read_bytes().decode("utf-8")
    return system, user


# --- Inputs (scout) ------------------------------------------------------------


def judge_vars(
    *, title: str, subreddit: str, flair: str, text: str, commented_titles: str
) -> dict[str, str]:
    return {
        "title": title,
        "subreddit": subreddit,
        "flair": flair or "(none)",
        "text": (text or "(no body — link or image post)")[:TEXT_MAX_CHARS],
        "commented_titles": commented_titles or "(none yet)",
    }


# --- The request (ScoutJudge._complete over ProviderTarget.__call__) -----------


def build_request(vars: Mapping[str, str], prompts: tuple[str, str]) -> dict[str, Any]:
    """The keyword arguments of `messages.create`, exactly as ScoutJudge sends
    them. No sampling parameters; retries are left to the SDK."""
    system_template, user_template = prompts
    prompt = render(user_template, vars)
    system = render(system_template, vars)
    request: dict[str, Any] = {
        "model": MODEL,
        "max_tokens": JUDGE_MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
        "output_config": {"format": {"type": "json_schema",
                                     "schema": JUDGE_SCHEMA}},
        "thinking": JUDGE_THINKING,
    }
    if system is not None:
        request["system"] = system
    return request


# --- Reading the reply ---------------------------------------------------------


def text_of(reply: Any) -> str:
    return "".join(
        block.text for block in reply.content if getattr(block, "type", "") == "text"
    )


def first_json_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON object in reply: {text[:120]!r}")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError(f"unterminated JSON object in reply: {text[:120]!r}")


def parse(text: str) -> dict[str, object]:
    """Raise on a reply that is not the shape JUDGE.md asked for."""
    data = json.loads(first_json_object(text))
    verdict = str(data["verdict"])
    if verdict not in VERDICTS:
        raise ValueError(f"verdict {verdict!r} is not one of {VERDICTS}")
    return {
        "verdict": verdict,
        "why": str(data["why"]),
        "angle": str(data.get("angle", "")),
    }


# --- settle_tool (scout) -------------------------------------------------------

MIN_QUOTE_CHARS = 15

_QUOTE_MARKS = "\"'‘’“”«»"


def _flat(text: str) -> str:
    text = text.translate(str.maketrans("‘’“”", "''\"\""))
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text.strip(" .,;:!?…-—")


def quoted_sentence(angle: str, *, title: str, text: str) -> str:
    post = _flat(f"{title}\n{text}")
    marks = [i for i, char in enumerate(angle) if char in _QUOTE_MARKS]
    found = ""
    for n, start in enumerate(marks):
        for end in marks[n + 1:]:
            span = angle[start + 1 : end].strip()
            flat = _flat(span)
            if len(span) > len(found) and len(flat) >= MIN_QUOTE_CHARS and flat in post:
                found = span
    return found


def settle_tool(answer: dict[str, object], vars: Mapping[str, str]) -> dict[str, object]:
    settled = {**answer, "quote": "", "tool_refused": ""}
    if answer.get("verdict") != VERDICT_TOOL:
        return settled
    quote = quoted_sentence(
        str(answer.get("angle", "")), title=vars.get("title", ""),
        text=vars.get("text", ""),
    )
    if quote:
        settled["quote"] = quote
    else:
        settled["verdict"] = "comment"
        settled["tool_refused"] = (
            f"{VERDICT_TOOL} refused: the angle quotes no sentence of the post "
            f"(verbatim, at least {MIN_QUOTE_CHARS} characters) — degraded to comment"
        )
    return settled

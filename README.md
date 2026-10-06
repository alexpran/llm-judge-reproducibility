# llm-judge-reproducibility

An experiment measuring run-to-run disagreement of one LLM judge on a real corpus.
The judge is the one in production in `scout`, which classifies Reddit threads; the same 533 cases are sent to it repeatedly with an unchanged request.
The question is how disagreement is distributed across cases: how many are stable, how many flip rarely, how many behave like a coin.

## Status

- `PROTOCOL.md` is a **draft, not yet frozen**. Items marked `TBD` are still open.
- **No call has been made on the corpus.** Calls made before the protocol are listed in `PROTOCOL.md` §12.
- There are no results.

## The corpus is not in this repository

The cases are real Reddit threads together with the author's own labels and the record of which threads the author commented on, so they are not published.
`corpus/MANIFEST.txt` records the sha256 of the frozen source file and the case counts; nothing else under `corpus/` is tracked.
Raw per-call logs (`raw/`) contain thread text and are not tracked either.

## Response headers

All response headers of each call are kept in the raw files (`raw/`, not tracked). Only some of them enter the published matrix.

- Published: `request-id`, `cf-ray`, `traceresponse`, `date`.
- Not published, because they identify the account or its service level: `anthropic-organization-id`, `anthropic-workspace-id`, and all `anthropic-ratelimit-*` headers.
- Constant across calls, not in the matrix: `server`, `connection`, `content-type`, `content-encoding`, `transfer-encoding`, `vary`, `cf-cache-status`, `content-security-policy`, `strict-transport-security`, `x-robots-tag`.

## How this works

- Changes to the protocol go through an issue or a pull request.
- When the protocol is frozen, the freezing commit is tagged.
- The first call on the corpus is made only after that tag. From then on, any departure from the protocol is recorded in `DEVIATIONS.md`.

## Layout

- `PROTOCOL.md`: the protocol
- `DEVIATIONS.md`: departures from the frozen protocol
- `prompts/`: the judge's system prompt and user template, copied from `scout` (see `prompts/SOURCE.txt`)
- `corpus/MANIFEST.txt`: hash and counts of the corpus
- `scripts/`: case export, run script, request identity check
- `tests/`: offline tests for the run script (no network)
- `results/`: empty for now

## Environment

Python 3.14, the version of scout's production environment. Dependencies: `pip install -r requirements.txt`.

## License

Code is licensed under Apache-2.0 (see `LICENSE`). The text of the protocol (`PROTOCOL.md`) is licensed under CC BY 4.0.

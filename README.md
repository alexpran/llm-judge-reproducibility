# llm-judge-reproducibility

An experiment measuring run-to-run disagreement of one LLM judge on a real corpus.
The judge is the one in production in `scout`, which classifies Reddit threads; the same 533 cases are sent to it repeatedly with an unchanged request.
The question is how disagreement is distributed across cases: how many are stable, how many flip rarely, how many behave like a coin.

## Status

- The protocol is frozen at tag `protocol-v1` (2026-10-08). The runs start on the first working day after the freeze.
- **No call has been made on the corpus.** Calls made before the protocol are listed in `PROTOCOL.md` §12.
- There are no results.

## The corpus is not in this repository

The cases are real Reddit threads together with the author's own labels and the record of which threads the author commented on, so they are not published.
`corpus/MANIFEST.txt` records the sha256 of the frozen source file and the case counts; nothing else under `corpus/` is tracked.
Raw per-call logs (`raw/`) contain thread text and are not tracked either.

## Response headers

All response headers of each call are kept in the raw files (`raw/`, not tracked). Only some of them enter the published matrix.

- Published: `request-id`, `traceresponse`.
- Not published, because they identify the account or its rate limits: `anthropic-organization-id`, `anthropic-workspace-id`, and all `anthropic-ratelimit-*` headers.
- Not published, because it shows the network location of the client: `cf-ray`.
- Not in the matrix, because it is redundant with the call's start time: `date`.
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
- `scripts/`:
  - `export_cases.py`: case export from the frozen state file
  - `judge.py`, `run.py`: request building and the run script
  - `check_request_identity.py`, `smoke_test.py`, `anchor_smoke.py`: instrument checks (§9)
  - `pilot_check.py`: check of the sample size and bins on the pilot (§13)
  - `make_matrix.py`: raw run files to `results/matrix.csv`, with public ids
  - `analyze.py`: the analyses of §6–§8, from the matrix alone
  - `pilot_to_matrix.py`: first six pilot runs in the matrix format, for a cross-check of `analyze.py` against `pilot_check.py`
- `tests/`: offline tests for the run, anchor smoke check, matrix and analysis scripts (no network)
- `results/`: matrix, analysis and their MANIFEST once produced; not tracked until they are published

## Environment

Python 3.14, the version of scout's production environment. Dependencies: `pip install -r requirements.txt`.

## License

Code is licensed under Apache-2.0 (see `LICENSE`). The text of the protocol (`PROTOCOL.md`) is licensed under CC BY 4.0.

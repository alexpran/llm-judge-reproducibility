# Runs

Six runs of 533 cases × 5 samples (2665 calls each). Start and end times are from each run's log (`raw/run-NN.log`, not tracked); call counts, errors and attempts are from the raw files (`raw/run-NN.jsonl`, not tracked).

| Run | Seed | Start (UTC) | End (UTC) | Calls | Errors by type | Attempts per call | Estimated cost (USD) | sha256 of raw file |
|---|---|---|---|---|---|---|---|---|
| 1 | 101 | 2026-10-09 06:48:56 | 2026-10-09 08:49:16 | 2665 | none | 1: 2665 | 27.2742 | `600e0b173d0b33edd3ae8814b22b746c18d642ea4a01b441e7a97a3ebd64c705` |
| 2 | 102 | 2026-10-09 12:41:56 | 2026-10-09 14:45:59 | 2665 | none | 1: 2665 | 27.1479 | `197f6da8cdeba6887388350fa6debbd881f653f10e4e73ec635c54d4fb159ad6` |
| 3 | 103 | 2026-10-12 06:50:00 | 2026-10-12 08:52:21 | 2665 | none | 1: 2665 | 27.2398 | `a48231aa98b718a195cc32bfcf1d3d6267afda90533994e6589e6ba36e2b1632` |
| 4 | 104 | 2026-10-12 12:49:53 | 2026-10-12 14:59:47 | 2665 | none | 1: 2665 | 27.2679 | `12127c26a0577d158fae527a79952a840a367ff55990304ef2f90dfef1534f9c` |
| 5 | 105 | 2026-10-13 06:52:06 | 2026-10-13 08:57:48 | 2665 | none | 1: 2665 | 27.1276 | `efd09e2798133f93f53a171bd0567ca14dfc3a438dd42fd90e85cf1cc2da58c9` |
| 6 | 106 | 2026-10-13 12:45:12 | 2026-10-13 14:48:41 | 2665 | refusal: 1 | 1: 2665 | 27.3296 | `4d005f7cfc1051bd2b4287cf17dc31b3a67dde91da43e4f955100096f7feafe3` |

Total: 15990 calls, 1 error (a refusal in run 6, not retried).

## Environment

The same for all six runs, as recorded in each run's log:

- SDK: anthropic 1.4.0
- Python: CPython 3.14.5
- System: Darwin 27.0.0, arm64
- Repository commit: `14ef1f2f01350396460b38341d95f99fe368e495` (tag `protocol-v1`)

## Notes

No verdict was looked at before the sixth run was closed.

The analysis was run twice with identical output on 2026-10-13. Regenerated on 2026-10-14 with the post hoc section; §7 and §8 verified unchanged against the committed files.

Costs are estimates computed from the token counts with a price list read in August 2026; they are not billed amounts.

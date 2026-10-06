# Run-to-run disagreement of an LLM judge on a real corpus: protocol

**Version:** v0 (draft, not yet committed)
**Author:** Alessandro Prandini
**Status:** no call has been made on the corpus described here. Items marked `TBD` must be filled before the commit that freezes this document. After that commit, any change goes in `DEVIATIONS.md` with a date and a reason.

## 1. Question and scope

Tamba (arXiv:2606.26185) shows on seven adversarial items that an LLM judge can return different verdicts for identical input, and leaves the base rate on a representative corpus as future work (§5.4).

This experiment measures, for one LLM judge running in production, **how run-to-run disagreement is distributed across real cases**: how many cases are perfectly stable, how many flip rarely, how many behave like a coin.

What this is not:

- It is not a safety evaluation corpus. The judge classifies Reddit threads. It is a neighbour of the §5.4 question, not that question.
- It is not a replication of the paper. Model, task, prompt and protocol all differ.
- It measures one judge, one prompt, one model. It is a base rate for this system, not for LLM judges in general.

## 2. System under measurement

`scout` reads Reddit feeds every morning and, for each thread, asks an LLM whether the thread is worth a comment. The LLM call is the judge.

| Item | Value |
|---|---|
| Model | `claude-sonnet-5` (canonical snapshot ID, not an alias) |
| Thinking | `{"type": "adaptive"}` |
| `max_tokens` | 2000 |
| Output | JSON schema via `output_config` |
| System prompt | `JUDGE.md`, sha256 `c9c8d0a0a81e45c793ae99debf4ba403793bd8b137277194f10681513ecd118e` |
| User template | `THREAD.md`, sha256 `ffdce2b2f9e527bc83c81e6dfb328a3bbfe0666687e7597dc8d91f7d4dc591e0` |
| Source of prompts | scout at commit `dfd5187ac0ddaa5968c6b777a1f56f406f21203b`, copied to `prompts/` |
| Sampling parameters | none sent (`temperature`, `top_p`, `top_k`, `seed` absent) |
| Verdict vocabulary | `comment`, `comment+tool`, `upvote`, `skip` |
| Calls | one thread per call, no batching |

Notes:

- Temperature cannot be pinned in this configuration. A single probe call with `temperature=0` returned HTTP 400: "temperature may only be set to 1 when thinking is enabled or in adaptive mode" (see §12). There is therefore no temperature-controlled arm.
- The provider documents that serving infrastructure may change while weights stay fixed. The snapshot fixes the weights only.
- After the model answers, a deterministic step (`settle_tool`) downgrades `comment+tool` to `comment` when the proposed angle does not quote the post.

## 3. Corpus

**Source.** A frozen copy of scout's state file, taken on 2026-10-06 10:10:50 CEST.
sha256 `d76b72b9b2b8e9ec0ad55deef4faab1ad8dda285a8f5188166f05015ad4de567`. Last judgement in the copy: 2026-10-05T06:39:34Z.

**Inclusion rule.** Every thread judged by scout from 2026-09-18 to 2026-10-05 (Rome time), excluding `duplicate` records (crosspost copies never sent to the judge). The rule does not look at the verdict or at the human label.

**Why this window.** From 18 September the judge used the same model, the same vocabulary and the same committed prompt as today, and every judged thread was reviewed by hand.

| | Total | Proposed by the judge | Skipped by the judge |
|---|---|---|---|
| Cases | 533 | 49 | 484 |
| With an expected verdict from a human label | 211 | 43 | 168 |

- **Strata.** "Proposed" means the original verdict was `comment`, `comment+tool` or `upvote`. "Skipped" means `skip`. Both strata are included in full.
- **Labels.** Labels were typed by the author at review time. 322 cases carry the label `deferred`, which has no expected verdict. Deferral is not random and its reasons are not recorded.
- **Input per case.** `title`, `subreddit`, `flair`, `text`, `commented_titles`, exactly as stored at the original judgement. `text` is truncated at 1500 characters. `flair` is empty for all cases. Cases with empty `text`: `TBD` (count from the export).
- **Judging days.** The 533 cases come from ten days: 18/09, 22–25/09, 29/09–2/10, 5/10.
- **Export.** A deterministic script reads only the frozen copy and writes the case file. sha256 of the case file: `TBD`.

Known limits of the corpus:

1. The prompt in force at each original judgement is not recorded in the state file. Git shows the committed `JUDGE.md` unchanged since 22 September, but an uncommitted edit during a morning run cannot be excluded. This affects only the assignment to strata, not the measurement.
2. These cases have never been through the author's regression suite. The older 145-case suite is a different, selected population (see §13).
3. The corpus is not published (§14).

## 4. Design

- **Cases:** all 533.
- **Runs:** 6. A run is one pass over all cases.
- **Samples:** 5 consecutive calls per case within a run. 30 calls per case in total.
- **Planned calls:** 15,990.
- **Order:** serial, one call at a time. The order of cases is shuffled in each run with a seed fixed here: `TBD` (six seeds).
- **Calendar:** at most two runs per calendar day, on at least three different days. Planned dates: `TBD`.
- **Request:** identical to production. Before the first run, the assembled request for a set of cases is hashed and compared with the one built by scout's own `ScoutJudge`. They must match byte for byte (§9.1).

"Within a run" therefore means five calls seconds apart. "Between runs" means the same case hours or days apart, with weights fixed.

## 5. What is recorded for each call

One JSONL line per call: case id, stratum, run index, sample index, start timestamp (UTC), latency, request id, model returned by the API, `stop_reason`, raw response text, parsed raw verdict, verdict after `settle_tool`, token usage including thinking tokens, cost, and the error if any.

Samples already obtained are never discarded because a later call on the same case fails.

## 6. Definitions

**Verdict levels.**

1. *Raw verdict* (primary): the value returned by the model, before `settle_tool`. Four values.
2. *Settled verdict*: after `settle_tool`.
3. *Pass/fail*: whether the settled verdict agrees with the expected verdict. Defined only for the 211 labelled cases. `comment+tool` counts as agreement with a `commented` label, as in production.

**Errors.** An API error after the SDK's default retries, a response that fails the schema, or a refusal is recorded as an error. It is never a verdict and it is not redrawn.

**Per-case stability.** Modal share = frequency of the most common raw verdict among the valid samples of a case, divided by the number of valid samples.

| Bin | Modal share | With 30 valid samples |
|---|---|---|
| Stable | 1 | 30 of 30 |
| Rare flips | ≥ 0.8 and < 1 | 24 to 29 |
| Unstable | ≥ 0.6 and < 0.8 | 18 to 23 |
| Coin-like | < 0.6 | 17 or fewer |

Cases with fewer than 25 valid samples are reported in a separate row and not binned.

**Within-run disagreement.** A (case, run) pair is non-unanimous if its valid samples are not all equal.

**Between-run disagreement.** The run verdict of a case is the modal raw verdict of its samples in that run. A tie is its own value. A case is between-run unstable if its six run verdicts are not all equal.

## 7. Primary outcomes

1. The distribution of cases over the four bins, for each stratum and for the whole corpus, with exact 95% binomial intervals on each proportion. Because both strata are included in full, the whole-corpus distribution is the distribution over the flow the judge actually saw in the window.
2. The number of cases with at least one non-unanimous run, and the number of between-run unstable cases, per stratum.
3. Whether between-run variation exceeds what within-run variation predicts. Test statistic: number of between-run unstable cases. Reference distribution: 10,000 permutations of each case's 30 samples across its six runs, seed `TBD`. Reported as the observed value against the permutation distribution.

Where a count is zero, the result is reported as an upper bound, not as zero.

## 8. Secondary analyses (declared, exploratory)

1. The same distribution on the settled verdict, and on pass/fail for the 211 labelled cases.
2. Discrimination next to reproducibility: agreement of each case's overall modal verdict with the expected verdict, per stratum, and whether unstable cases concentrate among the disagreements.
3. Thinking tokens against disagreement: rank correlation between a case's mean thinking tokens and 1 − modal share. Hypothesis stated in advance: longer reasoning gives more points where a near-tie can diverge, so disagreement rises with thinking length.
4. Concentration by original judging day, and by run day.
5. Cases with empty `text`, reported separately.
6. Error rate by run.

No other analysis will be reported as planned.

## 9. Instrument checks

**9.1 Request identity.** On `TBD` cases from the old 145-case set, the request built by the experiment script equals the one built by `ScoutJudge`, compared by hash.

**9.2 Smoke test.** About 20 calls on cases from the old 145-case set, to confirm that every field in §5 is written and that the API reports thinking tokens for this model. These calls are not data and touch no case of the corpus.

**9.3 Anchor on Tamba's items (`TBD`: to be settled before the commit).** Run Tamba's Zenodo harness (record 20674090, v1.1) unmodified in an environment with `anthropic<1`, and on the same day send the same seven items through the call-and-record loop used here. Purpose: check the instrument, not compare rates. The items are CC-BY-NC-ND and are not redistributed.

## 10. Stopping rule and budget

- There is no stopping rule based on results. All planned calls are made.
- Budget cap: 250 USD. Estimate from earlier runs on a different population: about 150 USD and about 15.5 hours of serial calls.
- A run is the unit. If the remaining budget cannot cover the next run at the observed cost per call, the experiment stops there and the analysis uses the completed runs. This is reported.
- An interrupted run is resumed from the point of interruption with the same seed, and the interruption is logged with timestamps.

## 11. Deviations

Anything that departs from this document is written in `DEVIATIONS.md`, with date, reason, and whether results had already been seen.

## 12. Calls made before this protocol

| Date (UTC) | What | Calls reaching the API |
|---|---|---|
| 2026-10-06 08:13 | Probe: `temperature=0` with adaptive thinking on `claude-sonnet-5`. HTTP 400. Request `req_011CfkeaXnRr7xwxDgxiDwnK` | 1 |
| 2026-10-06 | Tamba's harness run as published, with a placeholder key | 0 |
| `TBD` | Smoke test (§9.2) | `TBD` |

No call has been made on any of the 533 cases.

## 13. Pilot data already seen

Fifteen earlier runs exist on a different population: the 145-case regression suite (144 threads judged before 13 September and selected by label, plus one synthetic canary), 17–21 September, three runs per day, five samples per case, same prompt hashes, model and vocabulary as in §2. Only aggregates were looked at:

- across the three runs of one day, pass/fail changes on 1 to 6 cases, the majority verdict on 8 to 12, the set of five verdicts on 25 to 30;
- within a single run, 19 to 27 cases have non-unanimous samples.

Limits of the pilot: retrospective; selected population rich in proposed threads; the tool used to run it drops all samples of a case when one call fails, so errors are invisible; raw verdict reconstructed, not recorded.

Use made of it: choosing 30 samples per case and the bin boundaries in §6. `TBD`: confirm on the pilot that these choices separate the bins, in aggregate only, before the commit.

## 14. What is published

- This protocol and its git history.
- The experiment script and the export script.
- The full matrix of results: one row per call with anonymised case id, stratum, run, sample, timestamp, raw and settled verdict, error flag, thinking tokens.
- The sha256 of the frozen state file and of the case file.

The corpus itself is not published. It is real threads together with the author's own labels and the record of what the author commented on. That is also why it is a useful corpus: it was accumulated by use, not built.

## 15. Interest

The author maintains digline, an open source regression gate for LLM applications that measures a noise floor of this kind. The experiment script does not use digline. The pilot runs in §13 were produced with it.

## 16. What will not be claimed

- A base rate for LLM judges in general, or for safety evaluations.
- Any comparison of rates with Tamba's seven items.
- Any statement about the cause of disagreement beyond what §7.3 and §8.3 can support.

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
| SDK | anthropic 1.4.0 (pinned in requirements.txt), same version as production |
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

All 533 cases come from the feed; none was added by hand.

**Why this window.** From 18 September the judge used the same model, the same vocabulary and the same committed prompt as today, and every judged thread was reviewed by hand.

| | Total | Proposed by the judge | Skipped by the judge |
|---|---|---|---|
| Cases | 533 | 49 | 484 |
| With an expected verdict from a human label | 211 | 43 | 168 |

- **Strata.** "Proposed" means the original verdict was `comment`, `comment+tool` or `upvote`. "Skipped" means `skip`. Both strata are included in full.
- **Labels.** Labels were typed by the author at review time. 322 cases carry the label `deferred`, which has no expected verdict. Deferral is not random and its reasons are not recorded.
- **Input per case.** `title`, `subreddit`, `flair`, `text`, `commented_titles`, exactly as stored at the original judgement. `text` is truncated at 1500 characters. `flair` is empty for all cases. Cases with empty `text`: 17 (3 proposed, 14 skipped).
- **Judging days.** The 533 cases come from ten days: 18/09, 22–25/09, 29/09–2/10, 5/10.
- **Export.** A deterministic script reads only the frozen copy and writes the case file. sha256 of the case file: `e8e09fc9eaf93c6fabe49c37a4ca3a8cb31d8a39f71ca975ceda4f724c270645`.

Known limits of the corpus:

1. The prompt in force at each original judgement is not recorded in the state file. Git shows the committed `JUDGE.md` unchanged since 22 September, but an uncommitted edit during a morning run cannot be excluded. This affects only the assignment to strata, not the measurement.
2. These cases have never been through the author's regression suite. The older 145-case suite is a different, selected population (see §13).
3. The corpus is not published (§14).

## 4. Design

- **Cases:** all 533.
- **Runs:** 6. A run is one pass over all cases.
- **Samples:** 5 consecutive calls per case within a run. 30 calls per case in total.
- **Planned calls:** 15,990.
- **Order:** serial, one call at a time. The order of cases is shuffled in each run with a fixed seed: 101, 102, 103, 104, 105, 106 for runs 1 to 6.
- **Calendar:** two runs per day, starting at about 09:00 and 15:00 Rome time, on three consecutive working days beginning with the first working day after the freeze. If the first run of a day is still going at 15:00, the second starts when it ends. Actual start and end times are in each run's log.
- **Request:** identical to production. Before the first run, the assembled request for a set of cases is hashed and compared with the one built by scout's own `ScoutJudge`. They must match byte for byte (§9.1).
- **Environment:** the client sends its operating system, architecture and runtime version in request headers. All runs are made from the machine and the Python environment that scout's daily run uses, recorded in each run's log.

"Within a run" therefore means five calls seconds apart. "Between runs" means the same case hours or days apart, with weights fixed.

## 5. What is recorded for each call

One JSONL line per call: `case_id`, `stratum`, `run` (run index), `seed` (the run's shuffle seed), `sample` (sample index), `started_at` (start timestamp, UTC), `latency_ms`, `request_id`, `response_headers` (all headers of the last HTTP response of the call, null if no response arrived), `attempts` (number of HTTP responses received for the call, retries included), `attempt_statuses` (their status codes, in order), `hook_failed` (true if reading a response failed during the call, in which case `attempts` and `attempt_statuses` can miss that response), `model` (as returned by the API), `stop_reason`, `raw_text` (raw response text), `verdict_raw` (parsed verdict, before `settle_tool`), `verdict_settled` (after `settle_tool`), `why`, `angle`, `tool_refused`, `usage` (the full usage object returned by the API), `thinking_tokens`, `cost_usd` (estimated from the token counts and list prices, not billed), `error_type` (null, `api`, `parse`, `refusal` or `max_tokens`, see §6) and `error` (the detail). Each run's log records the SDK version and the commit of this repository.

Samples already obtained are never discarded because a later call on the same case fails.

`usage` includes the serving metadata returned by the API (`service_tier`, `inference_geo`); any variation across calls is reported.

All response headers are stored in the raw file. The published matrix includes the request id and the serving-side identifiers among them, listed by name in the README; headers that identify the account are not published. On the checks of 2026-10-06 the API returned 28 response headers. None identifies the serving model or replica: the only per-request identifiers are `request-id`, `cf-ray` and `traceresponse`.

## 6. Definitions

**Verdict levels.**

1. *Raw verdict* (primary): the value returned by the model, before `settle_tool`. Four values.
2. *Settled verdict*: after `settle_tool`.
3. *Pass/fail*: whether the settled verdict agrees with the expected verdict. Defined only for the 211 labelled cases. `comment+tool` counts as agreement with a `commented` label, as in production.

**Errors.** An error is one of: an API failure after the SDK's default retries (`api`); a response rejected by scout's own parser, which is more permissive than the JSON schema and is kept as in production (`parse`); a refusal (`refusal`); a response cut at `max_tokens` before a verdict (`max_tokens`). An error is never a verdict and is not redrawn.

**Per-case stability.** Modal share = frequency of the most common raw verdict among the valid samples of a case, divided by the number of valid samples.

| Bin | Modal share | With 30 valid samples |
|---|---|---|
| Stable | 1 | 30 of 30 |
| Rare flips | ≥ 0.8 and < 1 | 24 to 29 |
| Unstable | ≥ 0.6 and < 0.8 | 18 to 23 |
| Coin-like | < 0.6 | 17 or fewer |

**Valid-sample threshold.** With six runs a case needs at least 25 valid samples out of 30; with fewer completed runs the threshold is five sixths of the planned samples, rounded up. Cases below the threshold appear as a row 'below threshold' wherever bins are tabulated, and are left out and counted apart in every other analysis.

**Within-run disagreement.** A (case, run) pair is non-unanimous if its valid samples are not all equal.

**Between-run disagreement.** The run verdict of a case is the modal raw verdict of its samples in that run. A tie is a single value, whatever the tied verdicts. A run with no valid sample for a case is left out of the comparison for that case. A case is between-run unstable if its six run verdicts are not all equal.

**Overall modal verdict.** The most common raw verdict among all valid samples of a case. A case whose overall modal verdict is tied is reported in a row 'tie'. A case with no valid sample at all is reported in a row 'none'.

## 7. Primary outcomes

1. The distribution of cases over the four bins, for each stratum and for the whole corpus, with exact 95% binomial intervals on each proportion. Because both strata are included in full, the whole-corpus distribution is the distribution over the flow the judge actually saw in the window. The same distribution is also reported by modal verdict of the case (`skip`, `upvote`, `comment`, `comment+tool`), so that cases stable on `skip` and cases stable on a proposed verdict appear separately, and by label status (labelled, deferred). These breakdowns are descriptive counts: some cells are small and no test is run on them. Proportions are computed over all cases of the group, the 'below threshold' row included. The breakdowns by modal verdict and by label status are given for the whole corpus and for each stratum.
2. The number of cases with at least one non-unanimous run, and the number of between-run unstable cases, per stratum.
3. Whether between-run variation exceeds what within-run variation predicts. Test statistic: number of between-run unstable cases. Reference distribution: 10,000 permutations of each case's samples across its runs (all 30 when the case has no error), seed 2606. Reported as the observed value against the permutation distribution. Only valid samples are permuted; errors stay in their run. The test is made on the whole corpus only. A one-sided p-value, (k+1)/(N+1), is reported with no significance threshold.
4. For each case, the number of errors by type is reported next to its bin.

Where a count is zero, the upper limit of the two-sided exact 95% interval is reported next to it, wherever an interval is given. The stable bin is itself an upper bound: on the pilot, about one in eight cases that flip over 75 samples shows no flip in 30.

## 8. Secondary analyses (declared, exploratory)

1. The same distribution on the settled verdict, and on pass/fail for the 211 labelled cases. Per stratum and overall, with intervals, without further breakdowns.
2. Discrimination next to reproducibility: agreement of each case's overall modal verdict with the expected verdict, per stratum, and whether unstable cases concentrate among the disagreements. Computed on the settled verdict with the production rule of §6. Cases whose overall modal verdict is tied are left out and counted apart.
3. Thinking tokens against disagreement: rank correlation between a case's mean thinking tokens and 1 − modal share. Hypothesis stated in advance: longer reasoning gives more points where a near-tie can diverge, so disagreement rises with thinking length. With adaptive thinking some calls report zero thinking tokens. Disagreement is also compared between cases where thinking is always present, never present, or present in only some of the 30 calls. Thinking tokens are taken from every call that reports them, errors included. Rank correlation is Spearman with average ranks. The three thinking groups are compared by their counts in the bins. A case in which no call reports thinking tokens is left out and counted apart.
4. Concentration by original judging day: counts in the bins for each day label. By run day: for each of the 15 pairs of runs, the number of cases whose run verdict differs, marked as same day or different days. The day of a run is the Rome date of its first call.
5. Cases with empty `text`, reported separately. Counts in the bins only.
6. Error rate by run.
7. Sensitivity to errors: the bin distribution recomputed with an error counted as its own value over all 30 samples, including the cases below the valid-sample threshold. An error is a single value, whatever its type. Per stratum and overall, with intervals.
8. Serving metadata: the distinct values of `model`, `service_tier` and `inference_geo` with the number of calls for each, and the distribution of `attempts`, for the whole corpus and per run.

No other analysis will be reported as planned.

## 9. Instrument checks

**9.1 Request identity.** The request built by the experiment script equals the one built by scout's `ScoutJudge`, compared by hash of the canonical JSON of the arguments, on all 144 cases of the old set and on all 533 cases of the corpus: 677 of 677 identical. A negative control (one space added to the system prompt) gave 0 of 677. No request was sent. The comparison was repeated at the HTTP level (method, URL, headers except authentication and retry count, body): 677 of 677 identical. A second control (one header added on the experiment side) gave 0 of 677.

**9.2 Smoke test.** About 20 calls on cases from the old 145-case set, to confirm that every field in §5 is written and that the API reports thinking tokens for this model. These calls are not data and touch no case of the corpus. Done on 2026-10-06: 20 calls, 20 succeeded, all fields written, request ids present. The API reports thinking tokens in `usage.output_tokens_details.thinking_tokens`; in 2 of 20 calls the value was 0. Repeated on 2026-10-06 after the response-header change: 20 calls, 20 succeeded, one HTTP response per call.

**9.3 Smoke check on Tamba's seven items.** The seven items of the Zenodo record 20674090 (v1.1) are sent once each through the call-and-record loop used here, with the grader prompt and the grade extraction of that harness and the same model, thinking setting and `max_tokens` as §2, with no sampling parameters. The only purpose is to confirm that every field in §5 is written for a second prompt and parser. No rate is computed and nothing is compared with the paper. The items are used with the author's agreement (issue #1) and are not redistributed. Done on 2026-10-06: 7 calls, 7 succeeded, every field written.

## 10. Stopping rule and budget

- There is no stopping rule based on results. All planned calls are made.
- Budget cap: 350 USD. Estimates: about 150 USD and 15.5 hours of serial calls from the pilot runs, about 216 USD and 30 hours from the smoke test (20 calls). Both come from a different population.
- A run is the unit. If the remaining budget cannot cover the next run at the observed cost per call, the experiment stops there and the analysis uses the completed runs. This is reported.
- An interrupted run is resumed from the point of interruption with the same seed, and the interruption is logged with timestamps.
- With fewer than six completed runs, the matrix is built only with an explicit option and only from complete runs 1 to k. In that case 'six runs', '15 pairs' and '30 samples' in §6 to §8 read as k runs, k(k−1)/2 pairs and 5k samples.

## 11. Deviations

Anything that departs from this document is written in `DEVIATIONS.md`, with date, reason, and whether results had already been seen.

## 12. Calls made before this protocol

| Date (UTC) | What | Calls reaching the API |
|---|---|---|
| 2026-10-06 08:13 | Probe: `temperature=0` with adaptive thinking on `claude-sonnet-5`. HTTP 400. Request `req_011CfkeaXnRr7xwxDgxiDwnK` | 1 |
| 2026-10-06 12:28–12:30 | Smoke test (§9.2): 10 cases from the old set × 2 calls | 20 |
| 2026-10-06 14:20–14:23 | Smoke test repeated (§9.2): 10 cases from the old set × 2 calls | 20 |
| 2026-10-06 14:23 | Smoke check on Tamba's seven items (§9.3) | 7 |

No call has been made on any of the 533 cases.

## 13. Pilot data already seen

Fifteen earlier runs exist on a different population: the 145-case regression suite (144 threads judged before 13 September and selected by label, plus one synthetic canary), 17–21 September, three runs per day, five samples per case, same prompt hashes, model and vocabulary as in §2. Only aggregates were looked at:

- across the three runs of one day, pass/fail changes on 1 to 6 cases, the majority verdict on 8 to 12, the set of five verdicts on 25 to 30;
- within a single run, 19 to 27 cases have non-unanimous samples;
- over all available samples per case (up to 75; 144 cases, canary excluded), on the raw verdict: 104 cases stable, 22 with rare flips, 11 unstable, 7 coin-like; 40 cases have at least one non-unanimous run and 20 have run verdicts that are not all equal.

Limits of the pilot: retrospective; selected population rich in proposed threads; the tool used to run it drops all samples of a case when one call fails, so errors are invisible; raw verdict reconstructed, not recorded; samples were lost in blocks of five, so 30 cases have 70 or 65 samples instead of 75.

Use made of it: choosing 30 samples per case and the bin boundaries in §6. Check made before the freeze, with a criterion fixed in advance: over all 5005 subsets of 6 runs out of 15, at least 80% of cases must stay in the same bin with 30 samples as with 75, and fewer than 2% may move by more than one bin. Result on the raw verdict: 92.4% in the same bin (minimum 86.1%), 0.0% moving by more than one bin (maximum 0.7%); the settled verdict gives 91.7% and 0.0%. Of the 40 cases that are not stable over 75 samples, a median of 5 appear stable with 30 (range 2 to 10). The 30 samples are a subset of the 75, so this agreement is somewhat optimistic. No alternative boundaries were tried. The check is in `scripts/pilot_check.py`.

## 14. What is published

- This protocol and its git history.
- The export, run, matrix and analysis scripts, with their tests.
- The results matrix, `results/matrix.csv`: one row per call, no free text. Columns: public_id, stratum, label_status, expected, day_label, text_empty, run, seed, sample, started_at, latency_ms, model, stop_reason, verdict_raw, verdict_settled, tool_refused, error_type, attempts, attempt_statuses, hook_failed, output_tokens, thinking_tokens, service_tier, inference_geo, request_id, traceresponse.
- `results/analysis.json` and `results/tables.md`, produced by `scripts/analyze.py` from the matrix alone.
- The sha256 of the frozen state file, of the case file, of the six raw files and of the matrix.

Left out of the matrix on purpose: the response text and every other free-text field; the input token count and the cost, because they are a fingerprint of the thread's length; the `cf-ray` header, which shows the network location of the client; the headers that identify the account or its rate limits. Case identifiers are replaced by public ids in random order and judging days by letters in random order; the correspondence stays with the author.

The corpus itself is not published. It is real threads together with the author's own labels and the record of what the author commented on. That is also why it is a useful corpus: it was accumulated by use, not built.

## 15. Interest

The author maintains digline, an open source regression gate for LLM applications that measures a noise floor of this kind. The experiment script does not depend on digline. It contains a small amount of code copied from digline and digline-anthropic (prompt rendering and extraction of the response text), marked in the source, so that the request is identical to production. The pilot runs in §13 were produced with digline.

## 16. What will not be claimed

- A base rate for LLM judges in general, or for safety evaluations.
- Any comparison of rates with Tamba's seven items.
- Any statement about the cause of disagreement beyond what §7.3 and §8.3 can support.
- That the recorded `model` value identifies what served a request. It is the requested name as returned by the API, not proof of the serving model.

## 17. Contributions

- **Alessandro Prandini:** corpus, design, scripts, first draft of this protocol.
- **Hiroki Tamba:** review of the protocol before the freeze; the breakdown of bins by modal verdict and the per-case error counts (#4); the caveat on the `model` field, the recording of serving-side identifiers and the labelled/deferred breakdown (#5); the reduction of the anchor to a smoke check (#1).

The question comes from §5.4 of Tamba's paper (arXiv:2606.26185).

# Results

Planned samples per case: 30; threshold of valid samples: 25. Intervals: exact 95%.

## 7.1 Bins, raw verdict

| Bin | all (533) | proposed (49) | skipped (484) |
|---|---|---|---|
| stable | 434 / 533 (81.4%, 77.9–84.6) | 8 / 49 (16.3%, 7.3–29.7) | 426 / 484 (88.0%, 84.8–90.8) |
| rare flips | 50 / 533 (9.4%, 7.0–12.2) | 14 / 49 (28.6%, 16.6–43.3) | 36 / 484 (7.4%, 5.3–10.1) |
| unstable | 30 / 533 (5.6%, 3.8–7.9) | 16 / 49 (32.7%, 19.9–47.5) | 14 / 484 (2.9%, 1.6–4.8) |
| coin-like | 19 / 533 (3.6%, 2.2–5.5) | 11 / 49 (22.4%, 11.8–36.6) | 8 / 484 (1.7%, 0.7–3.2) |
| below threshold | 0 / 533 (≤ 0.7%) | 0 / 49 (≤ 7.3%) | 0 / 484 (≤ 0.8%) |

By modal verdict (all):

| modal | stable | rare flips | unstable | coin-like | below threshold |
|---|---|---|---|---|---|
| comment | 3 | 13 | 10 | 9 | 0 |
| comment+tool | 1 | 0 | 1 | 2 | 0 |
| skip | 429 | 35 | 16 | 4 | 0 |
| tie | 0 | 0 | 0 | 2 | 0 |
| upvote | 1 | 2 | 3 | 2 | 0 |

By label status (all):

| label | stable | rare flips | unstable | coin-like | below threshold |
|---|---|---|---|---|---|
| deferred | 275 | 26 | 13 | 8 | 0 |
| labelled | 159 | 24 | 17 | 11 | 0 |

By modal verdict (proposed):

| modal | stable | rare flips | unstable | coin-like | below threshold |
|---|---|---|---|---|---|
| comment | 3 | 11 | 9 | 6 | 0 |
| comment+tool | 1 | 0 | 1 | 1 | 0 |
| skip | 3 | 3 | 3 | 2 | 0 |
| tie | 0 | 0 | 0 | 1 | 0 |
| upvote | 1 | 0 | 3 | 1 | 0 |

By label status (proposed):

| label | stable | rare flips | unstable | coin-like | below threshold |
|---|---|---|---|---|---|
| deferred | 1 | 2 | 2 | 1 | 0 |
| labelled | 7 | 12 | 14 | 10 | 0 |

By modal verdict (skipped):

| modal | stable | rare flips | unstable | coin-like | below threshold |
|---|---|---|---|---|---|
| comment | 0 | 2 | 1 | 3 | 0 |
| comment+tool | 0 | 0 | 0 | 1 | 0 |
| skip | 426 | 32 | 13 | 2 | 0 |
| tie | 0 | 0 | 0 | 1 | 0 |
| upvote | 0 | 2 | 0 | 1 | 0 |

By label status (skipped):

| label | stable | rare flips | unstable | coin-like | below threshold |
|---|---|---|---|---|---|
| deferred | 274 | 24 | 11 | 7 | 0 |
| labelled | 152 | 12 | 3 | 1 | 0 |

## 7.2 Disagreement within and between runs

| Stratum | Cases | Non-unanimous | Between-run unstable | Below threshold, left out |
|---|---|---|---|---|
| proposed | 49 | 41 / 49 (83.7%, 70.3–92.7) | 25 / 49 (51.0%, 36.3–65.6) | 0 |
| skipped | 484 | 58 / 484 (12.0%, 9.2–15.2) | 22 / 484 (4.5%, 2.9–6.8) | 0 |

## 7.3 Permutation test

533 cases (0 below the threshold left out). Between-run unstable cases observed: 47. 10000 permutations, seed 2606. One-sided p: 0.220378.

| Statistic | Permutations |
|---|---|
| 37 | 6 |
| 38 | 21 |
| 39 | 62 |
| 40 | 196 |
| 41 | 441 |
| 42 | 866 |
| 43 | 1305 |
| 44 | 1704 |
| 45 | 1667 |
| 46 | 1529 |
| 47 | 1076 |
| 48 | 613 |
| 49 | 308 |
| 50 | 134 |
| 51 | 44 |
| 52 | 23 |
| 53 | 4 |
| 55 | 1 |

## 7.4 Errors by case

Cases with no error: 532.

| Public id | Bin | Valid | api | parse | refusal | max_tokens |
|---|---|---|---|---|---|---|
| p409 | unstable | 29 | 0 | 0 | 1 | 0 |

## 8.1 Settled verdict

| Bin | all (533) | proposed (49) | skipped (484) |
|---|---|---|---|
| stable | 434 / 533 (81.4%, 77.9–84.6) | 8 / 49 (16.3%, 7.3–29.7) | 426 / 484 (88.0%, 84.8–90.8) |
| rare flips | 50 / 533 (9.4%, 7.0–12.2) | 14 / 49 (28.6%, 16.6–43.3) | 36 / 484 (7.4%, 5.3–10.1) |
| unstable | 31 / 533 (5.8%, 4.0–8.2) | 17 / 49 (34.7%, 21.7–49.6) | 14 / 484 (2.9%, 1.6–4.8) |
| coin-like | 18 / 533 (3.4%, 2.0–5.3) | 10 / 49 (20.4%, 10.2–34.3) | 8 / 484 (1.7%, 0.7–3.2) |
| below threshold | 0 / 533 (≤ 0.7%) | 0 / 49 (≤ 7.3%) | 0 / 484 (≤ 0.8%) |

Pass/fail, labelled cases:

| Bin | all (211) | proposed (43) | skipped (168) |
|---|---|---|---|
| stable | 167 / 211 (79.1%, 73.0–84.4) | 15 / 43 (34.9%, 21.0–50.9) | 152 / 168 (90.5%, 85.0–94.5) |
| rare flips | 25 / 211 (11.8%, 7.8–17.0) | 12 / 43 (27.9%, 15.3–43.7) | 13 / 168 (7.7%, 4.2–12.9) |
| unstable | 16 / 211 (7.6%, 4.4–12.0) | 13 / 43 (30.2%, 17.2–46.1) | 3 / 168 (1.8%, 0.4–5.1) |
| coin-like | 3 / 211 (1.4%, 0.3–4.1) | 3 / 43 (7.0%, 1.5–19.1) | 0 / 168 (≤ 2.2%) |
| below threshold | 0 / 211 (≤ 1.7%) | 0 / 43 (≤ 8.2%) | 0 / 168 (≤ 2.2%) |

## 8.2 Modal settled verdict against the expected verdict

| Stratum | Cases | Agree | Disagree | Tied, left out | Below threshold, left out |
|---|---|---|---|---|---|
| proposed | 43 | 23 | 19 | 1 | 0 |
| skipped | 168 | 167 | 1 | 0 | 0 |

Bins of the raw verdict by agreement (proposed):

| agreement | stable | rare flips | unstable | coin-like | below threshold |
|---|---|---|---|---|---|
| agree | 2 | 9 | 8 | 4 | 0 |
| disagree | 5 | 3 | 6 | 5 | 0 |

Bins of the raw verdict by agreement (skipped):

| agreement | stable | rare flips | unstable | coin-like | below threshold |
|---|---|---|---|---|---|
| agree | 152 | 12 | 3 | 0 | 0 |
| disagree | 0 | 0 | 0 | 1 | 0 |

## 8.3 Thinking tokens

Spearman rho, mean thinking tokens against 1 − modal share: 0.68856 (533 cases; 0 below the threshold and 0 with no thinking tokens reported left out).

| thinking | stable | rare flips | unstable | coin-like | below threshold |
|---|---|---|---|---|---|
| always | 15 | 14 | 13 | 10 | 0 |
| never | 308 | 1 | 1 | 0 | 0 |
| some | 111 | 35 | 16 | 9 | 0 |

## 8.4 Judging day and run day

| judging day | stable | rare flips | unstable | coin-like | below threshold |
|---|---|---|---|---|---|
| A | 71 | 4 | 4 | 3 | 0 |
| B | 32 | 6 | 4 | 5 | 0 |
| C | 30 | 5 | 3 | 1 | 0 |
| D | 51 | 6 | 6 | 2 | 0 |
| E | 24 | 2 | 2 | 1 | 0 |
| F | 36 | 7 | 1 | 2 | 0 |
| G | 35 | 1 | 2 | 1 | 0 |
| H | 32 | 3 | 1 | 1 | 0 |
| I | 62 | 7 | 3 | 2 | 0 |
| J | 61 | 9 | 4 | 1 | 0 |

Run day: run 1 2026-10-09, run 2 2026-10-09, run 3 2026-10-12, run 4 2026-10-12, run 5 2026-10-13, run 6 2026-10-13

| Runs | Same day | Cases with different run verdicts |
|---|---|---|
| 1–2 | yes | 19 |
| 1–3 | no | 25 |
| 1–4 | no | 24 |
| 1–5 | no | 24 |
| 1–6 | no | 19 |
| 2–3 | no | 24 |
| 2–4 | no | 23 |
| 2–5 | no | 29 |
| 2–6 | no | 16 |
| 3–4 | yes | 24 |
| 3–5 | no | 23 |
| 3–6 | no | 21 |
| 4–5 | no | 31 |
| 4–6 | no | 22 |
| 5–6 | yes | 26 |

533 cases; 0 below the threshold left out.

## 8.5 Empty text

| group | stable | rare flips | unstable | coin-like | below threshold |
|---|---|---|---|---|---|
| all | 13 | 3 | 0 | 1 | 0 |
| proposed | 0 | 2 | 0 | 1 | 0 |
| skipped | 13 | 1 | 0 | 0 | 0 |

## 8.6 Errors by run

| Run | Calls | Errors | Rate | api | parse | refusal | max_tokens |
|---|---|---|---|---|---|---|---|
| 1 | 2665 | 0 | 0.0 | 0 | 0 | 0 | 0 |
| 2 | 2665 | 0 | 0.0 | 0 | 0 | 0 | 0 |
| 3 | 2665 | 0 | 0.0 | 0 | 0 | 0 | 0 |
| 4 | 2665 | 0 | 0.0 | 0 | 0 | 0 | 0 |
| 5 | 2665 | 0 | 0.0 | 0 | 0 | 0 | 0 |
| 6 | 2665 | 1 | 0.000375 | 0 | 0 | 1 | 0 |

## 8.7 Sensitivity: an error as its own value

| Bin | all (533) | proposed (49) | skipped (484) |
|---|---|---|---|
| stable | 434 / 533 (81.4%, 77.9–84.6) | 8 / 49 (16.3%, 7.3–29.7) | 426 / 484 (88.0%, 84.8–90.8) |
| rare flips | 50 / 533 (9.4%, 7.0–12.2) | 14 / 49 (28.6%, 16.6–43.3) | 36 / 484 (7.4%, 5.3–10.1) |
| unstable | 30 / 533 (5.6%, 3.8–7.9) | 16 / 49 (32.7%, 19.9–47.5) | 14 / 484 (2.9%, 1.6–4.8) |
| coin-like | 19 / 533 (3.6%, 2.2–5.5) | 11 / 49 (22.4%, 11.8–36.6) | 8 / 484 (1.7%, 0.7–3.2) |
| below threshold | 0 / 533 (≤ 0.7%) | 0 / 49 (≤ 7.3%) | 0 / 484 (≤ 0.8%) |

## 8.8 Serving metadata

`model`:

| Calls | claude-sonnet-5 |
|---|---|
| all (15990) | 15990 |
| run 1 (2665) | 2665 |
| run 2 (2665) | 2665 |
| run 3 (2665) | 2665 |
| run 4 (2665) | 2665 |
| run 5 (2665) | 2665 |
| run 6 (2665) | 2665 |

`service_tier`:

| Calls | standard |
|---|---|
| all (15990) | 15990 |
| run 1 (2665) | 2665 |
| run 2 (2665) | 2665 |
| run 3 (2665) | 2665 |
| run 4 (2665) | 2665 |
| run 5 (2665) | 2665 |
| run 6 (2665) | 2665 |

`inference_geo`:

| Calls | global |
|---|---|
| all (15990) | 15990 |
| run 1 (2665) | 2665 |
| run 2 (2665) | 2665 |
| run 3 (2665) | 2665 |
| run 4 (2665) | 2665 |
| run 5 (2665) | 2665 |
| run 6 (2665) | 2665 |

`attempts`:

| Calls | 0 | 1 | 2 | 3+ |
|---|---|---|---|---|
| all (15990) | 0 | 15990 | 0 | 0 |
| run 1 (2665) | 0 | 2665 | 0 | 0 |
| run 2 (2665) | 0 | 2665 | 0 | 0 |
| run 3 (2665) | 0 | 2665 | 0 | 0 |
| run 4 (2665) | 0 | 2665 | 0 | 0 |
| run 5 (2665) | 0 | 2665 | 0 | 0 |
| run 6 (2665) | 0 | 2665 | 0 | 0 |

## Post hoc

Added on 2026-10-14 at the co-author's request, after the results were seen. Not part of the frozen protocol.

### 8.3 by stratum

Spearman rho, mean thinking tokens against 1 − modal share, with the exclusions of §8.3.

| Stratum | Cases | Spearman rho | Below threshold, left out | No thinking tokens, left out |
|---|---|---|---|---|
| proposed | 49 | 0.496777 | 0 | 0 |
| skipped | 484 | 0.603298 | 0 | 0 |


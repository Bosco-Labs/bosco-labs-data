# Counterparty-check benchmark 2: report of draw 81d6e2e8

A vendor benchmark: Bosco Labs designed it, ran it and sells one of the two things compared. Protocol: `docs/benchmark2/PROTOCOL.md`. This report is written by the frozen script `tools/bench2_analyze.py`.

Model claude-sonnet-5-5. 102 companies drawn, 102 analysed (A: 30, B: 30, C: 30, S: 12); 0 excluded (listed at the end).

Run files: checked against prereg.json.

Excluded after the runs (changed register facts, hand-check disagreement): 0 of 90 companies in groups A, B and C; the protocol's limit is 10%.

## Headline

**On these companies the model reading counterparty-check reached the right decision more often than the model with web search.**

Share of runs with the right decision, mean of the three group means (A healthy, B in a procedure, C gone):

| | Web search | counterparty-check API | API minus Web |
|---|---|---|---|
| both replicates | 72.8% | 100.0% | +27.2 points |
| replicate 1 alone | 67.8% | 100.0% | +32.2 points |
| replicate 2 alone | 77.8% | 100.0% | +22.2 points |

- 95% interval of the difference, resampling companies within groups 10,000 times: +19.4 to +35.0 points.
- Mean plus or minus 2.0 standard errors (3.98 points): +19.3 to +35.2 points.
- Always answering "all clear" scores 33.3%.
- Verdict rule: product ahead.

| Group mean | Web | API |
|---|---|---|
| A (30 companies) | 71.7% | 100.0% |
| B (30 companies) | 78.3% | 100.0% |
| C (30 companies) | 68.3% | 100.0% |

## False all-clear: a problem company answered active and not insolvent

| Arm | Runs on B and C | False all-clear | 95% interval (Wilson, runs) |
|---|---|---|---|
| Web | 120 | 6/120 (5%) | 2.3% to 10.5% |
| API | 120 | 0/120 (0%) | 0.0% to 3.1% |
| Memory | 60 | 0/60 (0%) | 0.0% to 6.0% |
| Rule | 120 | 0/120 (0%) | 0.0% to 3.1% |

## What each arm answered, per group (runs)

| Arm | Group | Cleared | Flagged | No verdict | Failed run |
|---|---|---|---|---|---|
| Web | A | 43 | 0 | 17 | 0 |
| Web | B | 2 | 47 | 11 | 0 |
| Web | C | 4 | 41 | 15 | 0 |
| Web | S | 8 | 7 | 9 | 0 |
| API | A | 60 | 0 | 0 | 0 |
| API | B | 0 | 60 | 0 | 0 |
| API | C | 0 | 60 | 0 | 0 |
| API | S | 0 | 24 | 0 | 0 |
| Memory | A | 1 | 0 | 29 | 0 |
| Memory | B | 0 | 0 | 30 | 0 |
| Memory | C | 0 | 0 | 30 | 0 |
| Memory | S | 2 | 1 | 9 | 0 |
| Rule | A | 60 | 0 | 0 | 0 |
| Rule | B | 0 | 60 | 0 | 0 |
| Rule | C | 0 | 60 | 0 | 0 |
| Rule | S | 0 | 22 | 2 | 0 |

Cleared is right for group A and the expensive mistake for B, C and S; flagged is the reverse.

## Run-to-run noise: companies whose two runs disagree

- Web: 21/90 (23%), 95% interval 15.8% to 33.1%.
- API: 0/90 (0%), 95% interval 0.0% to 4.1%.
- Rule: 0/90 (0%), 95% interval 0.0% to 4.1%.

## Exact match per field (the first benchmark's measure)

| Arm | status | insolvent | sanctioned | all scored fields |
|---|---|---|---|---|
| Web | 140/180 (78%) | 93/104 (89%) | 100/180 (56%) | 95/180 (53%) |
| API | 180/180 (100%) | 101/104 (97%) | 180/180 (100%) | 177/180 (98%) |
| Memory | 1/90 (1%) | 1/52 (2%) | 9/90 (10%) | 1/90 (1%) |

Insolvent is scored only where the register says whether a winding-up is solvent. The Rule arm gives decisions, not field values, so it has no row here.

## Group S (sanctioned), counts only

| Arm | Listing caught | Listing missed | No verdict | Failed run | False sanction flags on A, B, C |
|---|---|---|---|---|---|
| Web | 7 | 8 | 9 | 0 | 0/180 |
| API | 24 | 0 | 0 | 0 | 0/180 |
| Memory | 1 | 2 | 9 | 0 | 0/90 |
| Rule | 22 | 0 | 2 | 0 | 0/180 |

## Control arms

- Memory (no tools, one run): 1.1% (A 3.3%, B 0.0%, C 0.0%).
- Rule (the API's verdicts, no model): 100.0% (A 100.0%, B 100.0%, C 100.0%).

## Cost and time

| Arm | Runs | Attempts | $ total | $ per run | of which API fee | Median s | Searches | Fetches | Tokens in / out |
|---|---|---|---|---|---|---|---|---|---|
| Web | 204 | 209 | $11.35 | $0.056 | $0.00 | 18.0 | 263 | 685 | 10,180,888 / 236,434 |
| API | 204 | 204 | $13.44 | $0.066 | $10.20 | 5.0 | 0 | 0 | 1,197,132 / 84,827 |
| Memory | 102 | 102 | $0.47 | $0.005 | $0.00 | 3.3 | 0 | 0 | 72,435 / 33,017 |

## Per country (too small for intervals)

| Arm | EE | GB | IE | LV |
|---|---|---|---|---|
| Web | 25/28 (89%) | 47/52 (90%) | 15/50 (30%) | 44/50 (88%) |
| API | 28/28 (100%) | 52/52 (100%) | 50/50 (100%) | 50/50 (100%) |
| Memory | 0/14 (0%) | 1/26 (4%) | 0/25 (0%) | 0/25 (0%) |
| Rule | 28/28 (100%) | 52/52 (100%) | 50/50 (100%) | 50/50 (100%) |

## Checks named in advance

| Check | Web | API | API minus Web | plus or minus 2 SE |
|---|---|---|---|---|
| first replicate only | 67.8% | 100.0% | +32.2 | +22.3 to +42.2 |
| without failed runs | 72.8% | 100.0% | +27.2 | +19.3 to +35.2 |
| without runs that had a tool error | 97.9% | 100.0% | +2.1 | -2.1 to +6.2 |
| uk and latvia only | 88.5% | 100.0% | +11.5 | +5.5 to +17.4 |
| group a without sanctions | 77.8% | 100.0% | +22.2 | +14.5 to +29.9 |
| all drawn companies no exclusions | 72.8% | 100.0% | +27.2 | +19.3 to +35.2 |

Group A without sanctions: group A is scored on register status and insolvency only. The web arm gets no by-number page for the sanctions lists (they are searched by name), so this check shows how much of the headline is the sanctions answer.

## Failed runs and retries

- Web: 0 runs without an answer, 5 retries; invalid attempts: {'tool_error_web_fetch_too_many_requests': 5}; tool errors: {'web_fetch: invalid_tool_input': 221, 'web_fetch: max_uses_exceeded': 4, 'web_fetch: url_not_accessible': 65, 'web_search: invalid_tool_input': 133, 'web_fetch: url_not_allowed': 46, 'web_fetch: too_many_requests': 5, 'web_search: max_uses_exceeded': 1, 'web_fetch: url_not_in_prior_context': 3}; product calls paid in an attempt the model API then stopped: 0.
- API: 0 runs without an answer, 0 retries; invalid attempts: none; tool errors: none; product calls paid in an attempt the model API then stopped: 0.
- Memory: 0 runs without an answer, 0 retries; invalid attempts: none; tool errors: none; product calls paid in an attempt the model API then stopped: 0.

Passed over at the draw because the name is on a sanctions list without a number match (these would be the false-alarm cases of a name screen): none.

## Every company

Truth as status / insolvent (None = the register does not say, not scored).

| Company | Group | Truth | Web r1 | Web r2 | API r1 | API r2 | Memory | Rule r1 | Rule r2 | Excluded |
|---|---|---|---|---|---|---|---|---|---|---|
| ee-10607192 | A | active / False | cleared | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| ee-10637336 | A | active / False | no verdict | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| ee-11200274 | A | active / False | cleared | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| ee-12126769 | B | winding_up / True | caught | caught | caught | caught | no verdict | caught | caught |  |
| ee-12179866 | B | winding_up / None | caught | caught | caught | caught | no verdict | caught | caught |  |
| ee-12922526 | B | winding_up / None | caught | caught | caught | caught | no verdict | caught | caught |  |
| ee-14815786 | A | active / False | cleared | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| ee-16319577 | B | winding_up / None | caught | caught | caught | caught | no verdict | caught | caught |  |
| ee-16500012 | A | active / False | cleared | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| ee-16585190 | B | winding_up / None | caught | caught | caught | caught | no verdict | caught | caught |  |
| ee-16614425 | B | winding_up / None | caught | caught | caught | caught | no verdict | caught | caught |  |
| ee-17190507 | B | winding_up / None | caught | caught | caught | caught | no verdict | caught | caught |  |
| ee-17474630 | A | active / False | no verdict | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| ee-17482813 | A | active / False | no verdict | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| gb-04659822 | A | active / False | cleared | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| gb-04660597 | B | winding_up / True | caught | caught | caught | caught | no verdict | caught | caught |  |
| gb-04661158 | B | winding_up / True | caught | caught | caught | caught | no verdict | caught | caught |  |
| gb-04661382 | B | winding_up / False | caught | no verdict | caught | caught | no verdict | caught | caught |  |
| gb-04953500 | B | winding_up / True | caught | caught | caught | caught | no verdict | caught | caught |  |
| gb-05543042 | A | active / False | cleared | cleared | cleared | cleared | cleared | cleared | cleared |  |
| gb-05543635 | B | winding_up / True | caught | caught | caught | caught | no verdict | caught | caught |  |
| gb-05543797 | B | winding_up / True | caught | no verdict | caught | caught | no verdict | caught | caught |  |
| gb-05742647 | S | winding_up / True | no verdict | caught | caught | caught | no verdict | no verdict | no verdict |  |
| gb-06601634 | S | active / False | caught | false all clear | caught | caught | no verdict | caught | caught |  |
| gb-06850415 | S | dissolved / False | false all clear | false all clear | caught | caught | no verdict | caught | caught |  |
| gb-07784342 | S | None / None | no verdict | no verdict | caught | caught | false all clear | caught | caught |  |
| gb-08203930 | A | active / False | cleared | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| gb-08204145 | B | winding_up / True | caught | caught | caught | caught | no verdict | caught | caught |  |
| gb-08204570 | A | active / False | cleared | no verdict | cleared | cleared | no verdict | cleared | cleared |  |
| gb-08204583 | B | winding_up / False | no verdict | caught | caught | caught | no verdict | caught | caught |  |
| gb-08204810 | A | active / False | cleared | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| gb-08205205 | C | dissolved / False | caught | caught | caught | caught | no verdict | caught | caught |  |
| gb-08205271 | A | active / False | cleared | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| gb-08220547 | S | None / None | no verdict | false all clear | caught | caught | no verdict | caught | caught |  |
| gb-11032231 | S | None / None | false all clear | caught | caught | caught | no verdict | caught | caught |  |
| gb-12122640 | S | active / False | no verdict | false all clear | caught | caught | false all clear | caught | caught |  |
| gb-12146985 | S | None / None | caught | no verdict | caught | caught | no verdict | caught | caught |  |
| gb-13885242 | S | None / None | caught | caught | caught | caught | caught | caught | caught |  |
| gb-14575184 | S | active / False | caught | no verdict | caught | caught | no verdict | caught | caught |  |
| gb-15154831 | C | dissolved / False | caught | caught | caught | caught | no verdict | caught | caught |  |
| gb-15154964 | C | dissolved / False | caught | caught | caught | caught | no verdict | caught | caught |  |
| gb-15155250 | C | dissolved / False | caught | caught | caught | caught | no verdict | caught | caught |  |
| gb-15155306 | C | dissolved / False | caught | caught | caught | caught | no verdict | caught | caught |  |
| gb-15155432 | C | dissolved / False | caught | caught | caught | caught | no verdict | caught | caught |  |
| gb-15155649 | A | active / False | cleared | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| gb-15155897 | A | active / False | no verdict | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| gb-15156194 | C | dissolved / False | caught | caught | caught | caught | no verdict | caught | caught |  |
| gb-15156247 | C | dissolved / False | caught | caught | caught | caught | no verdict | caught | caught |  |
| gb-15157300 | C | dissolved / False | caught | caught | caught | caught | no verdict | caught | caught |  |
| gb-16187338 | S | dissolved / False | no verdict | no verdict | caught | caught | no verdict | caught | caught |  |
| gb-SC783525 | C | dissolved / False | caught | caught | caught | caught | no verdict | caught | caught |  |
| ie-180480 | C | dissolved / None | no verdict | no verdict | caught | caught | no verdict | caught | caught |  |
| ie-194320 | B | winding_up / None | no verdict | no verdict | caught | caught | no verdict | caught | caught |  |
| ie-23737 | B | winding_up / None | caught | caught | caught | caught | no verdict | caught | caught |  |
| ie-239427 | A | active / False | no verdict | no verdict | cleared | cleared | no verdict | cleared | cleared |  |
| ie-267069 | C | dissolved / None | false all clear | no verdict | caught | caught | no verdict | caught | caught |  |
| ie-287076 | C | dissolved / None | no verdict | no verdict | caught | caught | no verdict | caught | caught |  |
| ie-432639 | C | dissolved / None | no verdict | no verdict | caught | caught | no verdict | caught | caught |  |
| ie-485469 | C | dissolved / None | no verdict | no verdict | caught | caught | no verdict | caught | caught |  |
| ie-502301 | B | winding_up / None | no verdict | no verdict | caught | caught | no verdict | caught | caught |  |
| ie-522912 | B | winding_up / None | caught | no verdict | caught | caught | no verdict | caught | caught |  |
| ie-539411 | C | dissolved / None | caught | caught | caught | caught | no verdict | caught | caught |  |
| ie-547488 | C | dissolved / None | no verdict | no verdict | caught | caught | no verdict | caught | caught |  |
| ie-557917 | B | winding_up / None | no verdict | caught | caught | caught | no verdict | caught | caught |  |
| ie-604946 | A | active / False | cleared | no verdict | cleared | cleared | no verdict | cleared | cleared |  |
| ie-612754 | A | active / False | no verdict | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| ie-625396 | A | active / False | no verdict | no verdict | cleared | cleared | no verdict | cleared | cleared |  |
| ie-644763 | C | dissolved / None | false all clear | false all clear | caught | caught | no verdict | caught | caught |  |
| ie-653830 | C | dissolved / None | no verdict | false all clear | caught | caught | no verdict | caught | caught |  |
| ie-659654 | B | winding_up / None | caught | no verdict | caught | caught | no verdict | caught | caught |  |
| ie-661545 | S | active / False | false all clear | false all clear | caught | caught | no verdict | caught | caught |  |
| ie-666964 | B | winding_up / None | caught | caught | caught | caught | no verdict | caught | caught |  |
| ie-671756 | A | active / False | no verdict | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| ie-708943 | B | winding_up / None | caught | caught | caught | caught | no verdict | caught | caught |  |
| ie-727769 | C | dissolved / None | no verdict | caught | caught | caught | no verdict | caught | caught |  |
| ie-728836 | A | active / False | no verdict | no verdict | cleared | cleared | no verdict | cleared | cleared |  |
| ie-748723 | A | active / False | no verdict | no verdict | cleared | cleared | no verdict | cleared | cleared |  |
| lv-40003984050 | B | winding_up / None | caught | caught | caught | caught | no verdict | caught | caught |  |
| lv-40103326477 | C | dissolved / True | caught | caught | caught | caught | no verdict | caught | caught |  |
| lv-40103387645 | B | winding_up / None | false all clear | caught | caught | caught | no verdict | caught | caught |  |
| lv-40103410180 | B | winding_up / None | false all clear | caught | caught | caught | no verdict | caught | caught |  |
| lv-40103495681 | A | active / False | cleared | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| lv-40103852949 | B | winding_up / None | caught | caught | caught | caught | no verdict | caught | caught |  |
| lv-40203031749 | C | dissolved / None | caught | caught | caught | caught | no verdict | caught | caught |  |
| lv-40203058739 | B | winding_up / True | caught | caught | caught | caught | no verdict | caught | caught |  |
| lv-40203101321 | A | active / False | cleared | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| lv-40203200721 | A | active / False | cleared | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| lv-40203227800 | C | dissolved / None | caught | caught | caught | caught | no verdict | caught | caught |  |
| lv-40203248338 | C | dissolved / None | caught | caught | caught | caught | no verdict | caught | caught |  |
| lv-40203248696 | A | active / False | cleared | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| lv-40203299048 | B | winding_up / True | caught | caught | caught | caught | no verdict | caught | caught |  |
| lv-40203300116 | C | dissolved / None | caught | caught | caught | caught | no verdict | caught | caught |  |
| lv-40203343897 | C | dissolved / None | caught | caught | caught | caught | no verdict | caught | caught |  |
| lv-40203387586 | C | dissolved / None | caught | caught | caught | caught | no verdict | caught | caught |  |
| lv-40203418068 | A | active / False | cleared | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| lv-40203520218 | A | active / False | cleared | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| lv-40203533354 | C | dissolved / None | no verdict | caught | caught | caught | no verdict | caught | caught |  |
| lv-40203558095 | C | dissolved / None | caught | caught | caught | caught | no verdict | caught | caught |  |
| lv-41203027988 | C | dissolved / None | no verdict | caught | caught | caught | no verdict | caught | caught |  |
| lv-42103108035 | A | active / False | cleared | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| lv-45403031910 | A | active / False | no verdict | cleared | cleared | cleared | no verdict | cleared | cleared |  |
| lv-50003914591 | B | winding_up / None | no verdict | caught | caught | caught | no verdict | caught | caught |  |

## Limits

Four of nine registers; the vendor ran it; the answer key and the product read the same registers; one model at one effort level; the right registration number was always given; ambiguous companies were skipped. Groups are not pooled into one accuracy figure: problem companies are two thirds of this set and a few percent of real suppliers. Companies whose name is on a sanctions list without a number match were skipped, which removes the cases where a name screen raises a false alarm. The full list is in the protocol, section 10.

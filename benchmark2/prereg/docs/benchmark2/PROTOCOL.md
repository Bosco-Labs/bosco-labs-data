# Counterparty-check benchmark 2: checking a company nobody has heard of

This is a vendor benchmark. Bosco Labs designed it, runs it and sells one of the two things it compares. The rules below exist so that a reader does not have to take the result on trust. Every number fixed at the freeze (beacon round, group size, prices) is in `data/benchmark2/prereg.json`.

## 1. The question

A buyer is about to pay a supplier it has never heard of. It has the supplier's legal name, country and registration number. It asks three things:

1. Is the company on the register and alive?
2. Is it in liquidation or an insolvency procedure?
3. Is the company itself on the UK, EU or OFAC SDN sanctions list?

We compare two ways to answer with the same model:

- **Web:** the model with web search and web fetch.
- **API:** one call to counterparty-check, then the model answers from the result.

## 2. What was wrong with the first benchmark

- 25 companies, hand-picked by the vendor after the product was built; 13 were famous and healthy, and the model answered most of those from memory.
- The first run went to web search, 23 to 17. Four product bugs were then fixed on the same 25 companies and the second run was 20 to 19. That was not a fresh test.
- Web search moved from 23 to 19 between two days with nothing changed, so the noise was as large as the gap.
- Some web-arm failures were harness faults (a run not resumed after a `tool_use` stop, tool errors scored as wrong answers).
- Only the API arm was told it may answer "unknown".

## 3. The companies

**Drawn at random from official registers, not chosen.**

| Group | Who | Countries | Size |
|---|---|---|---|
| A, healthy | on the register, normal status, no procedure | UK, Ireland, Latvia, Estonia | 30 |
| B, in a procedure | on the register, in liquidation or an insolvency procedure now | UK, Ireland, Latvia, Estonia | 30 |
| C, gone | dissolved or struck off in the 24 months before the freeze | UK, Ireland, Latvia | 30 |
| S, sanctioned | every listed organisation whose listed registration number and name match a register entry in those countries, at most 12 | any of the four | 0 to 12 |

- Private limited companies only (UK `ltd`, Irish private company limited by shares, Latvian SIA, Estonian OÜ). Sole traders and one-person businesses are excluded by legal form.
- No size filter. A random register entry is almost always small and unknown; the memory arm (section 5) measures whether that is true.
- Each group is split equally across its countries; a remainder goes to countries in hash order.
- Group size is 30. If the pilot shows that 30 does not fit the budget, it is 25 or 20 by the rule in section 9, fixed before the freeze.
- Group S is a complete list of a few better-known entities, not a random sample. It is reported on its own and never enters the headline.

**Left out, and why.** counterparty-check reads nine registers; this benchmark covers four. For Poland, the Czech Republic, Norway, Finland and France the repository knows how to look up one company but not how to list all of them, and for Poland and the Czech Republic guessing numbers is against the registers' terms. Rather than pick companies by hand there, those countries are left out. The result says nothing about them. Estonia is included only if the register's open-data licence has been confirmed before the freeze; Estonia's open data omits deleted companies, so it has no group C.

**Official lists used for the draw**

- UK: Companies House advanced search, every `ltd` incorporated on dates chosen by hash between 2000-01-01 and 2025-10-31.
- Ireland: the CRO "Company Records" open data, full snapshot.
- Latvia: the Enterprise Register open data (register, liquidations, insolvency proceedings), full snapshot.
- Estonia: the e-Business Register basic-data file.
- Sanctions: the UK Sanctions List, OFAC SDN and EU consolidated list files.

**Seed.** `seed = sha256(bundle hash + ":" + randomness of drand round R)`. The bundle hash covers this protocol, the scripts and all settings. R is a round of the public drand "quicknet" beacon at a time written in the frozen file, at least 24 hours after the bundle is public. There is no fallback source: if the round cannot be fetched, the draw waits.

**Draw.** Every eligible company gets `key = sha256(seed | country | registration number)`. Within each country and group the smallest keys are taken. For the UK, dates are ranked by hash and listed in that order (at least 8, at most 60) until every UK cell holds five times its quota; then the pool is ranked the same way. One draw only.

**Skips.** A company is passed over only for a reason on a fixed list: legal form not allowed; raw status not in the mapping table; ambiguous register facts (for example a strike-off proposal, or a past insolvency case on an active company); its name appears on a sanctions list without a number match; used in the pilot. Every skip is logged with its reason, and the 200 smallest keys per cell are published so a reader can see nothing else was passed over.

## 4. The answer key

- Read by the sampler straight from the registers and the three list files. It shares no code with the product and never calls the Bosco Labs API.
- A table from raw register values to answers is frozen before the seed exists. A raw value not in the table means the company is skipped, never judged by hand.
- Read twice: at the draw, and after the last run. A company whose facts changed in between is excluded and listed. The second read stores the values it found (status, insolvency, sanctions, group) and the hashes of the raw responses; the analysis recomputes "changed" from those values and warns when the stored flag disagrees.
- A person opens the official page for 12 rows chosen by hash (4 per group) and for every group S row. A row that disagrees is excluded and listed; the table is not edited. More than 3 disagreements out of 12 aborts the study. The hash of the filled-in hand-check file is written into every run file, and the analysis refuses a hand-check file that differs from it.
- **Limit on exclusions after the runs.** If more than 10% of the drawn A, B and C companies are excluded after the runs (changed facts plus hand-check disagreements), the verdict is "no difference shown" whatever the intervals say. The check "all drawn companies, no exclusions" is always printed.
- Stored per company: official URL, fetch time, hash of the raw response, and a cut-down copy (name, number, legal form, status, dates, case types). Never stored: officers, addresses, insolvency practitioners.

**Stated openly:** the truth comes from the same registers the product reads. The benchmark measures whether each arm retrieves the official record, not whether the record is right.

## 5. The arms

| Arm | What it has | Role |
|---|---|---|
| Web | web search and web fetch: 6 searches, 6 fetches, 10,000 tokens per page | compared |
| API | one counterparty-check call with `{query: registration number, country}` | compared |
| Memory | no tools | control: does the model know these companies? |
| Rule | the API's pass / fail verdicts turned into answers by a fixed table, no model | control: does the model's reading help or hurt? |

- Same model and settings in every model arm, same question, same answer format, and the same rule: "if your sources do not establish a field, answer unknown or null; do not guess". One sentence of the system prompt differs, saying what the arm has.
- The question gives the legal name, country, registration number, the name of the official register and the public by-number links we know for that register. This makes the web arm stronger than an agent that has to find the register itself. We chose the stronger comparator on purpose.
- For the sanctions lists there is no by-number page: the question gives each list's public publication or search page, which is searched by name, and the downloadable list files are far larger than web fetch's 10,000-token limit per page. So in group A, where the right decision includes "not sanctioned", the web arm has to establish a negative that its tools make hard to establish, while the API arm receives a ready sanctions verdict. That is the job the product is sold for, but it is a structural advantage, not only a difference in retrieval. The named check "group A without sanctions" (section 7) scores group A on register status and insolvency alone, so a reader can see how much of the headline rests on the sanctions answer.
- The web arm cannot open boscolabs.dev, huggingface.co or github.com (our own output and the old answer key).
- The API arm sees the full result without the officers section. Nothing is cut. An error or "unverified" from the API is the product's answer and is scored.
- A run that stops early is resumed (`pause_turn` and `tool_use`, up to 10 times). An attempt that still fails (network or server error, timeout, token limit, refusal, no readable answer) is retried from scratch, at most 3 attempts, by the same rule in every arm. A run that fails 3 times is shown as "failed run" and counts as not correct. Every attempt's cost counts.
- A web search or web fetch that the search service itself could not serve (error code `unavailable` or `too_many_requests`) is a fault of the service, like a network error: the attempt is invalid and retried by the same rule. Other tool errors (a page that does not open, a blocked address, a limit used up, a malformed query) are what web search is like, are kept and scored, and are counted in the report; the named check "without runs that had a tool error" leaves those runs out.
- No model fallback: a refusal is recorded, not hidden by a second model.

## 6. The runs

- Two full replicates of Web and API on two different days, at least 20 hours apart. Memory runs once. Rule reuses the API arm's responses.
- Company order and arm order are shuffled by the seed. The arms for one company run back to back.
- Every attempt is appended to a journal at once, with the search queries, pages fetched and cited, tool errors, stop reasons, request ids, token counts and the API's response. A restart continues; it never overwrites. A product call that was paid for in an attempt the model API then stopped (a key or credit fault on our side) is written as its own line and counted in the spend and the cost table.
- Each run file starts with the hashes of the frozen scripts, the bundle, the set and the hand check, and each sitting ends with a line that counts the attempt lines before it. After each replicate the runner prints that count and the journal's hash, which are posted with a timestamp at once. The analysis refuses run files whose hashes do not match the pre-registration, an attempt-number gap, or an end line whose count does not match.
- A run that is neither answered nor failed three times, and that the spend cap did not drop, is unfinished. While any run is unfinished the analysis prints no headline; the same run command finishes it. Dropping it would remove a run that might have counted as a failed run.
- The spend cap is checked before each company. If it would be passed, the rest of that replicate is dropped in the seeded order, which is random with respect to outcome. The cap is not raised during the study.
- No change to counterparty-check is deployed between the freeze and the last run. A product bug found during the runs is published as found and not fixed for this study.

## 7. The measure, fixed before the draw

**A run reaches the right decision when:**

- healthy company (A): it answers active, not insolvent and not sanctioned;
- problem company (B, C): it answers winding up or dissolved, or insolvent.

"Unknown", no answer and a failed run are not the right decision in either group, and are shown in their own columns.

**Headline.** Per company and arm: the share of its runs with the right decision. Per arm: the mean of the three group means (A, B, C, equal weight). The comparison is the paired difference, API minus Web, in percentage points. Always answering "all clear" scores 33; that baseline is printed next to the arms.

**Interval.** 95%, by resampling companies within groups 10,000 times (seeded). A second interval, mean plus or minus 2.0 standard errors, is printed beside it so a reader can check it in a spreadsheet. A group with fewer than two companies has no standard error: the interval is printed as n/a and no verdict other than "no difference shown" is possible.

**Verdict.**

- **Product ahead:** both intervals lie above zero and each replicate on its own shows the product ahead.
- **Web search ahead:** the mirror image.
- **No difference shown:** anything else. Reported as "this study shows no difference; it cannot separate gaps smaller than about N points", never as "equally good".

The sentence for each case is in the frozen file. For a loss: "On these companies the model with web search reached the right decision more often than the model reading counterparty-check."

**Always printed under the headline, with no win claimed**

- False all-clear rate: a problem company answered active and not insolvent. This is the expensive mistake.
- The full table per arm and group: cleared, flagged, no verdict, failed run.
- Each replicate's result side by side, and the share of companies whose two runs disagree.
- Each field's exact match, including the old "all three fields right".
- Group S: missed listings and false sanction flags, as counts.
- Memory and Rule arms. Cost in dollars and tokens, and seconds per run.
- Per country (too small for intervals).
- The full per-company table.

**Checks named in advance:** first replicate only; without runs that failed in either arm; without runs that had a tool error; UK and Latvia only; group A without sanctions (group A right on "active and not insolvent" alone); all drawn companies with no exclusions after the runs.

Groups are never pooled into one "accuracy in real life": problem companies are two thirds of this set and a few percent of real suppliers.

## 8. Pre-registration and how to verify it

1. **Probe and pilot.** The listing routes are checked with fixed test queries. A pilot of 6 companies, drawn with a fixed pilot seed, checks the plumbing and measures cost. Product and harness fixes are allowed here and only here. Pilot data and every change after it are published.
2. **Freeze.** This protocol, the scripts, the mapping tables, the prompts and settings, the group size and the beacon round are committed. The hashed settings also hold the freeze time (which sets the reference date of group C's 24-month window) and the pilot's mean cost per run; verify checks that the freeze came at least 24 hours before the round, that the reference date is the freeze date, and that the group size follows from the pilot means. The bundle and its hash are made public (public repository and a web-archive capture) before the round.
3. **Draw**, within 48 hours after the round. The set file, with truth and fetch times, is committed before any arm runs. Its hash is published at once; the list itself stays private until the runs end so that no arm can find it online.
4. **Replicate 1** within 24 hours of the draw, **replicate 2** within 72 hours of replicate 1, then the second truth read and the report, written by the frozen analysis script. Every run file carries the freeze commit, the set commit and the set hash.
5. **Publication within 7 days of the last run, whichever way it comes out:** the set, the skip log, per-run answers, sources, costs, the report, the pilot and any aborted attempt. If nothing has appeared 14 days after the beacon round, assume the result was unfavourable.

An abort is allowed only for a harness fault and is documented. A second attempt needs a new freeze and a new round, and the first attempt's data stays public.

**A reader can check:** the bundle hash and its public timestamp predate the round; the round's randomness is public and the seed recomputes; the set matches its early hash; the skip log and runner-up keys; the truth links; the scores, recomputed from the published runs with the published script.

**A reader cannot check:** that the vendor did not try the product on the set between the draw and the runs, or deploy a change; that no earlier freeze or draw was made and thrown away before the published one (the scripts refuse a second draw on the same files, but files can be deleted); and that no whole run was deleted from the journal before the counts were posted (an attempt-number gap or a count mismatch is detected, a deleted last run of a sitting before the post is not). The public timestamps of the bundle, the set hash and the per-replicate counts narrow this; only an outside party running the study would remove it.

## 9. Cost and time

Estimates until the pilot measures them. The stored runs show $0.063 per web run at the old, lower settings.

| Item | Estimate |
|---|---|
| Web arm, about $0.15 a run, 204 runs | $31 |
| API arm, $0.05 fee plus about $0.02 model, 204 runs | $14 |
| Memory arm, 102 runs | $1 |
| Retries, about 10% | $4.50 |
| Pilot | $2 |
| **Total** | **about $52** |

- Hard cap: $55 for the main runs, $3 for the pilot.
- Group size rule: the largest of 30, 25, 20 whose projected cost, from the pilot, is at most $50. If 20 does not fit, the study is not run on this budget.
- Expected precision at 30 per group: about plus or minus 11 points on the difference; a true gap of 17 points is found about 85 times in 100; a gap under about 10 points will read as "no difference shown". These are estimates from the noise in the old runs, not measurements.
- Time: about an hour for the probe, pilot and freeze; about two hours for the draw, the hand check and replicate 1; about an hour and a half for replicate 2 and the report. Three sittings over three days, because of the 24-hour gap and the two run days.

## 10. Limits

- Four of nine registers.
- The vendor runs it.
- Truth and product share their sources.
- One model, one effort level, one set of tool limits. A different model or a purpose-built agent could score differently.
- The correct registration number is always given. Name-only lookups, wrong numbers, owners, officers, VAT and bank details are not tested.
- Ambiguous companies are skipped, so the set is easier than real life.
- A company whose name is on a sanctions list without a number match is skipped from groups A, B and C. Those are exactly the companies on which a sanctions screen by name raises a false alarm, so this skip can only help the arm that screens by name (the API arm), and it makes "not sanctioned" true for every headline company. The report prints how many companies this skip removed per cell.
- Insolvency as a separate fact is unscored where the register does not say whether a liquidation is solvent (Ireland, Estonia, parts of Latvia).
- Per-country and group S figures are small and descriptive only.
- A company name can contain a surname. Names are published as the register shows them; nothing else about persons is stored or published.
- Registers change daily, so a later rerun will not reproduce every label.

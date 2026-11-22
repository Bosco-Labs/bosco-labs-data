# Changes after the pilot

The protocol (section 8, step 1) allows product and harness fixes during the probe and the
pilot, and only then. Every change made after the pilot's first run is listed here, with the
commit, before the freeze. This file is part of the public export.

| Date | Commit | What changed | Why (pilot run or probe that showed it) |
|---|---|---|---|

Nothing is changed after the freeze. A product bug found during the main runs is listed below,
as found, and is not fixed for this study.

## Before the pilot: changes after an outside review of the kit

Made before any pilot run, so before anything was measured. Listed because they change the rules.

- A web search or fetch the search service could not serve (`unavailable`,
  `too_many_requests`) now makes the attempt invalid and is retried like a network error;
  other tool errors are kept and a new named check leaves those runs out (protocol section 5).
- The protocol no longer says the sanctions links are by-number pages; it says the web arm must
  prove a negative sanctions answer by name search, and a new named check scores group A
  without sanctions (sections 5 and 7).
- Unfinished runs (not answered, not failed three times, not dropped by the cap) now block the
  headline instead of silently leaving it (section 6).
- Exclusions after the runs: the hand check's hash is written into every run file and checked
  by the analysis; truth2 "changed" is recomputed from the stored values; above 10% of A, B and
  C excluded the verdict is "no difference shown"; a new named check uses all drawn companies
  (sections 4 and 7).
- The freeze time, the draw's reference date and the pilot's cost figures are now in the hashed
  settings, and verify checks they agree (section 8).
- The analysis checks the run files against the pre-registration (script, set and hand-check
  hashes, attempt numbering, per-sitting attempt counts) and refuses on a difference; the
  runner prints a count and journal hash to publish after each replicate (sections 6 and 8).
- A product call paid for in an attempt the model API then stopped is journaled and counted.
- A group with one company has no standard error (n/a) instead of zero (section 7).
- The name-collision skip is named as a limit that can only help the API arm, and its count per
  cell is printed (section 10).
- Harness only: UTF-8 output on any console, the Companies House key checked before any
  download, one-line network errors, the projected cost printed and a typed `yes` asked for
  before a real run spends money, and a set-up step in the runbook.

## Found during the main runs

None so far.

## 2026-11-19 (probe, before the pilot)

- truth_map.json: 8 raw statuses the probe found, mapped like their neighbours. Ireland: "deleted as per se tr",
  "deleted cb conversion", "deleted cb merger", "deleted per se merge" -> skip status_not_mapped (cross-border and
  SE deletions, like "dissolved postmerger"). Latvia: "insolvency:out_of_court_legal_protection" -> skip ambiguous
  (like "insolvency:legal_protection"); "liquidation:non_reregistration", "liquidation:reform_of_associations",
  "liquidation:reform_of_political_parties" -> skip status_not_mapped.
- truth_map.json: LV liquidation_end_fields ["date_to"] -> [] : the probe's lv_liquidation columns have no end-date
  column, so every listed liquidation counts as current (the same behaviour as before, now stated).
- config.json: prices sourced from https://platform.claude.com/docs/en/about-claude/pricing on 2026-11-19 (Sonnet 5.5
  $2 / $10, cache hits $0.10, 5-minute cache writes 1.25x, web search $10 per 1,000). Estonia's licence: CC BY 4.0
  (register site's "License information" link), checked 2026-11-19, so Estonia is included.
- Probe: all four registers, the three sanctions lists (UK 1,685 / OFAC SDN 10,115 / EU 1,779 organisations) and the
  drand beacon answered; drand chain, genesis and period match config.json.

## After the freeze: deploys that do not touch counterparty-check

The protocol forbids deploying a change to counterparty-check between the freeze and the last
run. The API is one service, so a deploy for another tool also restarts the service that answers
the API arm. Each such deploy is listed here; for each, the frozen files (counterparty_check.py,
company_check.py, sanctions_screening.py, actors/) are unchanged against the frozen commit and
every other tool's prices and price texts are byte-for-byte the same (tested before the merge).

| Date (UTC) | Commit | What changed | Effect on the API arm |
|---|---|---|---|
| 2026-11-20, before the draw | the wallet-screening price merge | wallet-screening price: $0.002 per address for the first 10 per call, then $0.0005; its own x402 minimum $0.002 | none: counterparty-check code, price and texts unchanged |
| 2026-11-20 | feat/x402-listings | x402 listing texts for 4 non-benchmark tools (vat-iban-check, identifier-resolver, sec-filings-feed, eu-rates-inflation): Bazaar name, tags, lead; prices unchanged | none: counterparty-check unchanged |
| 2026-11-20 | feat/wallet-price-v2 | wallet-screening price (second owner decision, replaces the $0.002 tier): $0.01 per call for up to 5 addresses, $0.002 each to 10, then $0.0005; x402 minimum back to the standard $0.005 | none: counterparty-check code, price and texts unchanged |
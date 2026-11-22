# Counterparty-check benchmark 2: public files of draw 81d6e2e8

A vendor benchmark by Bosco Labs. The protocol, the scripts and the frozen settings are in
`../prereg/` of the public repository Bosco-Labs/bosco-labs-data (`docs/benchmark2/PROTOCOL.md`,
`tools/bench2_*.py`, `data/benchmark2/`). Results page:
https://boscolabs.dev/blog/benchmark2-results.html Seed: `81d6e2e8f5fc793775c4618975bae90fadb0290c7e39b7c105682789a8bc7546`.

## Files

- `CHANGES.md`
- `README.md`
- `audit.json`
- `pilot_runs_public.jsonl`
- `pilot_set.json`
- `prereg.json`
- `report.json`
- `report.md`
- `runs_public.jsonl`
- `set.json`
- `set_skips.json`
- `truth2.json`

`runs_public.jsonl` is the run journal without the model's full text, the search queries and the
API's full response; each line carries a hash of what was left out. Company names are published
as the registers show them. Nothing else about persons is stored or published: no officers, no
addresses, no insolvency practitioners.

## Recompute the report

From the root of Bosco-Labs/bosco-labs-data, with Python 3.12:

    cd benchmark2/prereg
    python tools/bench2_prereg.py verify
    python tools/bench2_analyze.py --dry-run --journal ../results/runs_public.jsonl --set ../results/set.json --audit ../results/audit.json --truth2 ../results/truth2.json

The first checks every frozen file against the bundle hash; the second recomputes `report.md`
from the published runs and needs only Python and the files named above.

The line count and SHA-256 published after each replicate are of the full run journal, which
holds the model's text and is not published; `runs_public.jsonl` has the same attempt lines
without it, so the counts can be checked here but the journal hash cannot.

## Sources and attribution

- Contains public sector information licensed under the Open Government Licence v3.0 (Companies House; UK Sanctions List, FCDO).
- Contains Irish Public Sector Data licensed under a Creative Commons Attribution 4.0 International (CC BY 4.0) licence (Companies Registration Office, Company Records).
- Enterprise Register of Latvia (Uzņēmumu reģistrs) open data, CC0 1.0.
- e-Business Register (RIK) open data, CC BY 4.0 (only when Estonia is part of the set).
- OFAC SDN List: US Treasury, a US government work; no endorsement by OFAC implied.
- EU data: European Commission, Consolidated list of persons, groups and entities subject to EU financial sanctions; reformatted for matching, names as published. Only the Official Journal of the EU is authentic.
- Randomness: the drand quicknet beacon (League of Entropy).

The answer key was read from these official sources by `tools/bench2_sample.py`; it is a copy
of public register facts on the fetch dates given in `set.json` and `truth2.json`, not legal
advice, and registers change daily.

# bosco-vendor-check: vendor onboarding check on official registers

A small reference agent from Bosco Labs. Give it a supplier (a name or a registration number)
and it returns a KYB checklist built from official sources: register status, LEI, insolvency,
recent accounts, sanctions on the company and its officers, VAT number (VIES) and IBAN. Each
check is `pass`, `fail`, `review` or `unverified`, with the source it came from.

Python 3.10+, standard library only, MIT licence. It calls the
[Bosco Labs API](https://boscolabs.dev/api.html) (`counterparty-check`, $0.05 per company).

## Try it in under 2 minutes, no key

```bash
# offline: three companies' recorded API responses that ship with the package
uvx bosco-vendor-check --demo        # or: pip install bosco-vendor-check && vendor-check --demo

# live, free: the planner plus LEI (GLEIF) and SEC lookups; prints what the full check costs
uvx bosco-vendor-check "Novo Nordisk A/S" --country DK
```

Without a key nothing is charged. You get the matching LEI records (status, registration number,
GLEIF link), SEC registrants for `--country US`, and the price of the paid check.

## The full check, with a key

Get a key at <https://boscolabs.dev/api.html> (a new key comes with $5 of free credit, no card), then:

```bash
export BOSCO_API_KEY=...        # Windows PowerShell: $env:BOSCO_API_KEY = "..."
python -m vendor_check "Novo Nordisk A/S" --country DK --vat DK24256790 --iban DK5000400440116243
python -m vendor_check 24256790 --country DK --out novo.json      # by registration number
python -m vendor_check --csv vendors.example.csv --out results.csv --yes
```

- One company checked = $0.05. A name that fits several companies returns the candidates for free;
  run again with the LEI or registration number of the right one.
- A CSV run with a key prints its maximum cost and stops unless you add `--yes`.
- CSV input columns: `name` (required), `country`, `vat_number`, `iban`.
- `--out` writes `.json` (the full API rows) or `.csv` (one line per check: vendor, check,
  status, detail, source_url).

Example output (abridged):

```
== Novo Nordisk A/S (DK)
   NOVO NORDISK A/S | Erhvervsstyrelsen (CVR) 24256790 | LEI 549300DAQ1CVT6CXN342
   [PASS      ] register_status: Register status: active.
                https://api.gleif.org/api/v1/lei-records/549300DAQ1CVT6CXN342
   [UNVERIFIED] sanctions_people: No officer or owner names known (...)
   [PASS      ] iban: DK5000400440116243: structure and check digits valid. (...)
   needs attention: none; unverified (not checked, not 'safe'): ['sanctions_people', ...]
```

## Use it from your own code or agent

```python
from vendor_check import check_vendor

result = check_vendor("Tesco PLC", country="GB")  # uses BOSCO_API_KEY if set
if result["mode"] == "paid" and result["row"]:
    for check in result["row"]["checks"]:
        print(check["check"], check["status"], check["source_url"])
else:
    print(result["lei_candidates"], result["plan"]["total_max_usd"])
```

`examples/claude_tool_use.py` gives `check_vendor` to Claude as a tool (Anthropic Python SDK,
`pip install anthropic`, model `claude-opus-5-5`) and lets it answer "Can we onboard X?" with the
source links of the checks.

## Paying per call without an account (x402)

An agent with a wallet can skip the key: `POST https://api.boscolabs.dev/v1/counterparty-check`
without one answers `402 Payment Required` (x402 v2) with the price, and the agent pays per call
in USDC on Base. This project does not do that itself. See
<https://boscolabs.dev/api.html#x402> and the
[x402 example agent](https://github.com/Bosco-Labs/bosco-labs-data/tree/main/examples/x402-agent).

## Limits: read before you rely on it

- **A screening aid, not a compliance, credit or legal verdict.** Review every `fail` and
  `review` against its linked source before you act.
- **`unverified` means not checked, never "safe".** A source that is not covered, not answering
  or not given (no VAT number, no IBAN) shows up as `unverified`.
- **Coverage differs per country**, as the API states it: officers and owners are screened for
  UK, Polish, Norwegian and French companies only; insolvency covers UK, PL, FR, DE, NL, NO, FI
  and EE, and is `unverified` elsewhere. VAT numbers are EU only (VIES). The IBAN check is
  structural (length, check digits, bank code, country); no bank is contacted, so it does not
  prove who holds the account. Current details: <https://boscolabs.dev/counterparty-check.html>.
- Without a key, the free lookups find companies that have an LEI or file with the SEC; most
  small companies have neither, and that says nothing about them.
- The free lookups are rate limited (30 calls a minute per IP).
- **The demo data is old by design.** `vendor_check/demo_fixture.json` holds free API responses
  for Novo Nordisk A/S, Tesco PLC and Apple Inc. recorded on 2026-11-08. The paid checklist
  shown for Novo Nordisk is the API's documented example response, labelled
  "example response shape, not live data"; it is not a live check.

## Data and licences

The checks come from official registers and lists (GLEIF, national company registers, The
Gazette, KRS, OFAC, UN, UK and EU sanctions lists, VIES and others), each named with its licence
in `GET https://api.boscolabs.dev/v1/tools/counterparty-check`. No endorsement by any publisher
is implied.

## Tests

```bash
pip install pytest && pytest      # offline: demo fixture and a stubbed API, no network
```

## Contact

Bosco Labs, <https://boscolabs.dev>, support@boscolabs.dev. MIT licence, see `LICENSE`.

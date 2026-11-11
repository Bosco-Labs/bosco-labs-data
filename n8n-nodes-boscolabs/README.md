# n8n-nodes-boscolabs

An [n8n](https://n8n.io) community node for [Bosco Labs](https://boscolabs.dev): company checks
from official records (company registers, sanctions lists, the EU VIES service), with the
source URL on every result so a workflow can show where an answer comes from.

Use it to check a customer's VAT number before invoicing, screen a supplier for insolvency and
sanctions, pull a company's filed accounts, or get a weekly list of new UK companies.

## Installation

Follow the [community nodes installation guide](https://docs.n8n.io/integrations/community-nodes/installation/)
and install the package `n8n-nodes-boscolabs`. On a self-hosted instance: **Settings >
Community Nodes > Install**, then enter the package name.

## Credentials

Paid operations need a Bosco Labs API key (prepaid credits, no subscription).

1. Get a key at <https://boscolabs.dev/api.html#key>. New keys come with $5 free credit, once
   per verified e-mail, no card.
2. In n8n, create a **Bosco Labs API** credential and paste the key (it starts with `bl_live_`).
3. n8n tests the credential by reading your balance (`GET /v1/me`). That costs nothing.

The key is sent as `Authorization: Bearer <key>` to `https://api.boscolabs.dev` and nowhere
else. **Question > Plan** runs without a credential.

## Operations

| Resource | Operation | What comes back | Price |
| --- | --- | --- | --- |
| Company | Check Counterparty | A KYB checklist for one company: register status, LEI, insolvency, recent accounts, sanctions on the company and its officers, VAT and IBAN when given. Each check is `pass`, `fail`, `review` or `unverified`, with its source. | $0.05 per company checked. A name that fits several companies returns the candidates, free. |
| Company | Get Report | Identity, LEI, officers and owners, key financial figures per year and SEC filings for one company. Optional sections: UK charges, officer appointments, insolvency notices. | $0.03 per report |
| Company | Get Accounts | Filed annual accounts of UK, Danish and Norwegian companies by registration number: revenue, profit, assets, equity and more, one row per company and fiscal year. | $0.04 per company-year |
| Company | Get New UK Companies | Companies incorporated in the UK on a day or in a date range, filtered by SIC code, location and type. No director data. | $0.002 per company |
| VAT and IBAN | Check | Valid or not for EU VAT numbers (live from VIES, with the registered name and a name match) and IBANs (structure, check digits, bank code). | $0.002 per number with a definite answer. Malformed and unverified numbers are free. |
| Sanctions List | Screen | Per name or crypto wallet address: match or no match, the listed entries, aliases, programs and source links, from the OFAC SDN and non-SDN lists, the US Consolidated Screening List, and the UK, EU and UN lists. | $0.01 per name or address |
| Question | Plan | The Bosco Labs calls that answer a question in plain words, with their input and maximum price. It does not run them. | Free, no key |

Prices are charged from the credits of your key, per result. **Empty and failed calls are
free**: a call that returns no rows, is refused or runs into a source that does not answer
costs nothing. The current prices are also at <https://api.boscolabs.dev/v1/tools?compact=true>.

### Output

- **One n8n item per result row**, so the next node can branch on a field such as
  `{{ $json.summary.fail }}`. A call without results returns no items; the node then shows
  the API's explanation as a hint.
- **Simplify** (on by default) keeps at most 10 fields per row, always with the source link
  where the row has one. For a counterparty check that is `query`, `status`, `company`,
  `checks`, `summary`, `candidates`, `sanctions_hits`, `message`, `warnings` and `source_url`.
  Turn it off for every field.
- **Options > Return Full Response** returns one item with the whole API answer: `rows`,
  `count`, `warnings`, `message`, `charged_usd` and `balance_usd`.
- The node runs once per input item. Fields that take a list accept values separated by
  commas, or an array from an expression. Sanctions **Names** take one name per line, because a
  company name can contain a comma.

### Use as an AI agent tool

The node can be connected to an AI Agent node as a tool. **Question > Plan** is a cheap first
step for an agent: it returns the exact calls and what they cost before anything is spent.

## Example: screen a new supplier

1. Add a **Bosco Labs** node, resource **Company**, operation **Check Counterparty**.
2. Set **Company** to `{{ $json.supplier }}` (a registration number or LEI avoids name
   mix-ups) and, under Additional Fields, **Country** to `GB`.
3. Add an **If** node on `{{ $json.status }}` equals `checked`, then a second **If** node:
   `{{ $json.summary.fail }}` is greater than 0 **or** `{{ $json.summary.review }}` is greater
   than 0. Send the true branch to your alert.

A shortened answer for `Carillion plc`, country `GB` (recorded from the live API on
2026-11-10):

```json
{
  "query": "Carillion plc",
  "status": "checked",
  "company": {
    "legal_name": "CARILLION PLC",
    "country": "GB",
    "registration_number": "03782379",
    "register": "Companies House",
    "status": "liquidation",
    "lei": "6SNZTEXLR1M5211YYB89",
    "lei_status": "LAPSED"
  },
  "checks": [
    {
      "check": "register_status",
      "status": "fail",
      "detail": "Register status: liquidation.",
      "source_url": "https://find-and-update.company-information.service.gov.uk/company/03782379"
    }
  ],
  "summary": {
    "pass": 2,
    "fail": 2,
    "review": 2,
    "unverified": 1,
    "needs_attention": ["register_status", "lei_status", "insolvency", "accounts_recent"],
    "unverified_checks": ["vat_number"]
  },
  "source_url": "https://find-and-update.company-information.service.gov.uk/company/03782379"
}
```

Three ready-made workflows are in [`templates/`](templates): validate a customer's VAT number
and company before invoicing, screen a new supplier, and a weekly list of new UK companies by
SIC code. Import one with **Workflows > Import from File**.

## Coverage: what is and is not checked

A counterparty check reads what official open sources publish. That differs by country:

| Country | Register status from | Officers screened against sanctions lists | Insolvency from |
| --- | --- | --- | --- |
| United Kingdom | Companies House | directors and owners (PSCs) | Companies House and The Gazette |
| Poland | KRS | board (names the register shows in full) | KRS |
| Norway | Brønnøysund | CEO and board | register status |
| France | Sirene | directors (RNE) | BODACC |
| Finland, Estonia | national register | not available | register status |
| Ireland | Companies Registration Office open data | not read | CRO status (receiverships are not in the open data) |
| Czech Republic | ARES | not read | ARES status |
| Latvia | Enterprise Register open data | not read | the register's open data |
| Germany | GLEIF (companies with an LEI) | not available | insolvenzbekanntmachungen.de |
| Netherlands | GLEIF (companies with an LEI) | not available | Centraal Insolventieregister |
| Denmark, United States, other countries | GLEIF, SEC | not available | not checked (`unverified`) |

- Sanctions on the company itself, the LEI, VAT (EU member states and Northern Ireland, via
  VIES) and IBAN checks work for every country.
- `unverified` always means **not checked** (no source for that country, a source that did not
  answer, no VAT number known). It never means "safe". There is no overall verdict or risk
  score.
- **Get Accounts** covers the United Kingdom, Denmark and Norway. UK accounts filed only on
  paper or as PDF are skipped.
- **Get New UK Companies** covers the United Kingdom only and returns at most 200 companies per
  call.
- Sanctions screening covers official sanctions and export-control lists only. It has no PEP or
  adverse-media lists. A name match alone does not confirm identity.
- An IBAN check does not contact a bank, so it does not prove who holds the account.

These checks are a screening aid, not a compliance, credit or legal determination. Review every
`fail` and `review` before acting.

## Compatibility

Built with `@n8n/node-cli` 0.56 against `n8n-workflow` 2.47 (n8n 2.x). The package has no
runtime dependencies.

## Resources

- Bosco Labs API docs: <https://boscolabs.dev/api.html>
- Tool catalogue with input schemas: <https://api.boscolabs.dev/v1/tools>
- [n8n community nodes documentation](https://docs.n8n.io/integrations/community-nodes/)
- Support: support@boscolabs.dev

## Development

```bash
npm install
npm run lint    # the n8n community node linter
npm test        # build, then offline tests with mocked HTTP (no live API calls)
```

## License

[MIT](LICENSE)

# Workflow templates

Three importable n8n workflows that use the **Bosco Labs** node (`n8n-nodes-boscolabs`) and
core n8n nodes only (Manual Trigger, Schedule Trigger, If, Edit Fields, Sticky Note). Import
one with **Workflows > Import from File**, add a **Bosco Labs API** credential
([get a key](https://boscolabs.dev/api.html#key)) and pick it in each Bosco Labs node. Each
workflow has a sticky note with the setup steps, the cost and what the result does not cover.

The titles and descriptions below are written for the n8n template library.

## Validate a new customer's VAT number and company before invoicing

File: `validate-vat-and-company-before-invoicing.json`

Checks a new customer's EU VAT number live in VIES, with the company name you expect, and
stops there when the number is not confirmed. For a valid number it runs a counterparty check
on the company (register status, insolvency, sanctions, and whether the VAT number belongs to
that company) and ends in one of three outcomes: OK to invoice, review before invoicing, or
do not invoice yet. Costs $0.002 for the VAT check plus $0.05 for the company check.

## Screen a new supplier: register status, insolvency and sanctions, alert on fail or review

File: `screen-new-supplier.json`

Runs one counterparty check on a supplier from official registers and the OFAC, UN, UK, EU and
US export lists, then builds an alert text with every failed or review check and its source
link. A supplier name that fits several companies goes to a separate branch with the candidates
to pick from, at no cost. Costs $0.05 per supplier checked; checks without a source for the
supplier's country are reported as unverified, not as passed.

## Weekly list of newly registered UK companies by SIC code

File: `weekly-new-uk-companies-by-sic-code.json`

Every Monday at 08:00 it lists the companies incorporated in the UK in the last 7 days for the
SIC codes you choose, from the Companies House register: number, name, incorporation date, SIC
codes, registered office and a link to the register page. Costs $0.002 per company, at most
$0.40 per run (200 companies per call); for busier sectors, narrow the location or run it daily.

## Notes

- The sample values are public companies (Novo Nordisk A/S, Carillion plc). Replace the
  **New Customer** / **New Supplier** node with your own trigger.
- The alert and list steps end in an Edit Fields node so the templates need no other
  credentials. Connect Slack, e-mail, a spreadsheet or a CRM after them.
- These checks are a screening aid, not a compliance, credit or legal determination.

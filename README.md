# Bosco Labs data APIs

Official-source data for AI agents, with a source link on every row. 27 tools over SEC EDGAR
(filings, insider trades, 13F and N-PORT holdings, financials), company registers (UK, DK, NO,
FR, FI, EE, US) and annual accounts, sanctions lists (OFAC, UK, EU, US export lists), EU and
UK/Dutch law, Dutch case law, US federal rules (eCFR, Federal Register), openFDA drug safety,
product recalls, CVEs, tariffs (US HTS, UK), clinical trials, EU tenders, US federal and DoD
contract awards, ECB rates and more.

- Site and docs: https://boscolabs.dev
- For AI agents and LLMs: [`llms.txt`](llms.txt) and [`llms-full.txt`](llms-full.txt)

## Ways to use it

| Channel | How | Pay |
|---|---|---|
| HTTP API | `POST https://api.boscolabs.dev/v1/<tool>`, catalogue at [`/v1/tools`](https://api.boscolabs.dev/v1/tools), [OpenAPI](https://api.boscolabs.dev/openapi.json) | prepaid credits ([api.html](https://boscolabs.dev/api.html)) |
| x402 | the same endpoints without a key: the `402` names the price; `upto` settles only what is delivered | USDC on Base, per call, no account |
| Remote MCP | `https://api.boscolabs.dev/mcp` (key) | credits |
| Free MCP | `https://api.boscolabs.dev/mcp/free`: LEI lookup and SEC ticker/name to CIK, no key | free |
| A2A | [`/.well-known/agent-card.json`](https://api.boscolabs.dev/.well-known/agent-card.json) | credits or x402 |
| Apify Actors | [apify.com/bosco_labs](https://apify.com/bosco_labs), also through Apify's MCP server | pay per event on Apify |
| stdio MCP | `uvx bosco-labs-data-mcp` (runs the Actors with your `APIFY_TOKEN`), see [`mcp/`](mcp/) | Apify |

Empty or failed answers cost nothing, and every paid answer says what it cost. The x402 routes
are listed in the Coinbase x402 Bazaar; an example agent is in
[`examples/x402-agent/`](examples/x402-agent/).

## This repository

The site is plain static HTML, generated from the Actors' schema files and READMEs and checked
(title and meta description length, Store links, JSON-LD) before every update. The MCP server's
release steps are in [`mcp/PUBLISHING.md`](mcp/PUBLISHING.md).

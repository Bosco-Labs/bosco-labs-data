<!-- mcp-name: io.github.Bosco-Labs/bosco-labs-data -->

# Bosco Labs data: MCP server

One MCP server that gives AI agents official-source data: free company lookups (LEI, SEC),
plus SEC insider trades and filings, US House members' stock trades, Pentagon contract awards,
EU public tenders and the financials of European companies. The paid tools call the
[Bosco Labs API](https://boscolabs.dev/api.html) with your Bosco Labs key; a new key comes with
**$5.00 of free credit, no card** (https://boscolabs.dev/api.html#key). Every tool returns a
short JSON list with a source link on every row.

## Free tools (no token)

These two tools call the open official APIs directly: no key, no cost.

| Tool | Data (source) | Example question |
|---|---|---|
| `get_lei_record` | LEI, legal name, status, jurisdiction, registration number and ultimate parent of any legal entity (GLEIF, CC0 open data) | "What is Heineken N.V.'s LEI and is it active?" |
| `find_sec_company` | CIK, official name, tickers, exchanges, SIC industry and state of incorporation of SEC-registered companies (SEC EDGAR) | "What is Alphabet's CIK and on which exchange does it trade?" |

```bash
claude mcp add bosco-labs-data -- uvx bosco-labs-data-mcp   # no key needed for these
# ask: "Look up the LEI of ASML" -> get_lei_record {"query": "ASML"}
```

Each result has a `next_steps` list: the paid call that gives the full picture (filings,
insider trades or financials), with its `tool` and `arguments` on the remote MCP server
(`https://api.boscolabs.dev/mcp`) and the HTTP API, and `stdio_tool` / `stdio_arguments` for
this package.

## Paid tools

| Tool | Data (source) | Price per row | Example question |
|---|---|---|---|
| `get_eu_annual_reports` | Audited financials of EU/UK listed companies (ESEF reports, filings.xbrl.org) | $0.05 (on Apify + $0.01 per call) | "Compare ASML's and Heineken's latest revenue and operating margin." |
| `get_company_accounts` | Accounts of UK, Danish and Norwegian companies, incl. private (Companies House, Erhvervsstyrelsen, Brønnøysund) | $0.04 | "What were the revenue and equity of Danish company CVR 24256790 in recent years?" |
| `search_sec_insider_trades` | Form 4 insider purchases and sales since 2006, cluster buys and sells (SEC EDGAR) | $0.0018 | "Have NVIDIA insiders bought or sold shares in the last month?" |
| `search_sec_filings` | Any EDGAR filing since 1994: 8-K items, 10-K, 10-Q, earnings release times (SEC EDGAR) | $0.001 | "When did Apple last release earnings, and was it after the close?" |
| `search_us_house_stock_trades` | STOCK Act trades of House members since 2014 (Clerk of the House) | $0.0018 | "What stocks did Nancy Pelosi trade this year?" |
| `search_eu_tenders` | EU/EEA public tenders and contract awards (TED) | $0.002 | "Find open IT-services tenders in Germany and the Netherlands from this week." |
| `search_dod_contract_awards` | DoD (or any federal agency) contract awards since FY2008, with winner tickers (USAspending.gov) | $0.005 | "Which Pentagon contracts did Kratos win this year?" |

Every tool has a `max_results` parameter with a small default (3 to 25 rows) and a hard
maximum, so one call costs cents. `search_dod_contract_awards` can take a minute or more.

Two other Bosco Labs Apify Actors are not tools here because they work on your own Apify datasets or
Google credentials: [Dedup & Merge Datasets](https://apify.com/Bosco_labs/dataset-dedup) and
[Google Sheets Export](https://apify.com/Bosco_labs/sheets-export). Use them on Apify directly.

## Changes in 0.4.0

All tools were renamed to one verb_noun scheme, the scheme the Bosco Labs remote MCP server
(https://api.boscolabs.dev/mcp) uses too. Inputs and outputs did not change. Scripts or configs that call a tool by its old name
must use the new one; the old names no longer exist.

| Before 0.4.0 | From 0.4.0 |
|---|---|
| `lei_lookup` | `get_lei_record` |
| `sec_company_lookup` | `find_sec_company` |
| `eu_annual_report_financials` | `get_eu_annual_reports` |
| `european_company_accounts` | `get_company_accounts` |
| `sec_insider_trades` | `search_sec_insider_trades` |
| `sec_filings` | `search_sec_filings` |
| `us_house_stock_trades` | `search_us_house_stock_trades` |
| `eu_public_tenders` | `search_eu_tenders` |
| `dod_contract_awards` | `search_dod_contract_awards` |

## Pricing

The free tools cost nothing. For the paid tools you pay per row returned, at the prices above,
from the prepaid credits of your Bosco Labs key ($5.00 free to start, no card). Already on
Apify? Set `APIFY_TOKEN` instead of `BOSCO_API_KEY`: the same tools then run as
[Bosco Labs Apify Actors](https://apify.com/Bosco_labs), billed to your Apify account. If both
are set, `BOSCO_API_KEY` is used. The server itself is free; it only calls the Bosco Labs API
(or Apify) for the paid tools, and GLEIF and the SEC for the free tools.

## Install

1. For the paid tools, get a Bosco Labs key ($5.00 free credit, no card):
   https://boscolabs.dev/api.html#key (skip this for the free tools only).
2. Install [uv](https://docs.astral.sh/uv/).
3. Add the server to your client (below); the command is `uvx bosco-labs-data-mcp`.

### Claude Desktop

`claude_desktop_config.json` (Settings -> Developer -> Edit Config):

```json
{
  "mcpServers": {
    "bosco-labs-data": {
      "command": "uvx",
      "args": ["bosco-labs-data-mcp"],
      "env": { "BOSCO_API_KEY": "bl_live_..." }
    }
  }
}
```

### Cursor

`~/.cursor/mcp.json` (or `.cursor/mcp.json` in a project): the same `mcpServers` block as
above.

### Claude Code

```bash
claude mcp add bosco-labs-data -e BOSCO_API_KEY=bl_live_... -- uvx bosco-labs-data-mcp
```

Without a key, leave out the `env` block (or `-e BOSCO_API_KEY=...`): the free tools work and
the paid tools reply where to get a key. Apify users: `APIFY_TOKEN=apify_api_...` instead
(https://console.apify.com/settings/integrations).

## Alternatives: hosted MCP servers

Without installing anything, the same key works on the Bosco Labs remote MCP server
`https://api.boscolabs.dev/mcp` (more tools: company registers, sanctions screening, EU law and
more). Apify users can use the same Actors through Apify's own MCP server
(OAuth or your token; each Actor becomes a tool with its full input):

```
https://mcp.apify.com?tools=Bosco_labs/esef-annual-reports,Bosco_labs/company-accounts,Bosco_labs/sec-insider-trades,Bosco_labs/sec-filings-feed,Bosco_labs/us-house-trades,Bosco_labs/eu-tenders,Bosco_labs/dod-contract-awards
```

This server is the lighter option: typed parameters, small defaults and compact results.

## Development

```bash
uv run --with pytest pytest -q    # from this folder; the APIs are mocked, plus a stdio smoke test
```

Source and releases: https://github.com/Bosco-Labs/bosco-labs-data (folder `mcp/`). Releases are
published to PyPI and the official MCP Registry by the `publish-mcp.yml` GitHub Actions
workflow; see
[PUBLISHING.md](https://github.com/Bosco-Labs/bosco-labs-data/blob/main/mcp/PUBLISHING.md).

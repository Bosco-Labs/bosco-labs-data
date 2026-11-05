<!-- mcp-name: io.github.PB7-debug/bosco-labs-data -->

# Bosco Labs data: MCP server

One MCP server that gives AI agents official-source data: SEC insider trades and filings,
US House members' stock trades, Pentagon contract awards, EU public tenders and the financials
of European companies. Each tool runs one of the
[Bosco Labs Apify Actors](https://apify.com/Bosco_labs) with **your own** Apify token and
returns a short JSON list with a source link on every row.

## Tools

| Tool | Data (source) | Price per row | Example question |
|---|---|---|---|
| `eu_annual_report_financials` | Audited financials of EU/UK listed companies (ESEF reports, filings.xbrl.org) | $0.05 + $0.01 per call | "Compare ASML's and Heineken's latest revenue and operating margin." |
| `european_company_accounts` | Accounts of UK, Danish and Norwegian companies, incl. private (Companies House, Erhvervsstyrelsen, Brønnøysund) | $0.04 | "What were the revenue and equity of Danish company CVR 24256790 in recent years?" |
| `sec_insider_trades` | Form 4 insider purchases and sales since 2006, cluster buys and sells (SEC EDGAR) | $0.0018 | "Have NVIDIA insiders bought or sold shares in the last month?" |
| `sec_filings` | Any EDGAR filing since 1994: 8-K items, 10-K, 10-Q, earnings release times (SEC EDGAR) | $0.001 | "When did Apple last release earnings, and was it after the close?" |
| `us_house_stock_trades` | STOCK Act trades of House members since 2014 (Clerk of the House) | $0.0018 | "What stocks did Nancy Pelosi trade this year?" |
| `eu_public_tenders` | EU/EEA public tenders and contract awards (TED) | $0.002 | "Find open IT-services tenders in Germany and the Netherlands from this week." |
| `dod_contract_awards` | DoD (or any federal agency) contract awards since FY2008, with winner tickers (USAspending.gov) | $0.005 | "Which Pentagon contracts did Kratos win this year?" |

Every tool has a `max_results` parameter with a small default (3 to 25 rows) and a hard
maximum, so one call costs cents. `dod_contract_awards` can take a minute or more.

Two other Bosco Labs Actors are not tools here because they work on your own Apify datasets or
Google credentials: [Dedup & Merge Datasets](https://apify.com/Bosco_labs/dataset-dedup) and
[Google Sheets Export](https://apify.com/Bosco_labs/sheets-export). Use them on Apify directly.

## Pricing

You pay Apify per row returned, with your own token, at the prices above (the free Apify plan
includes monthly credit). The server itself is free and sends nothing anywhere else.

## Install

1. Get an Apify API token: https://console.apify.com/settings/integrations
2. Install [uv](https://docs.astral.sh/uv/).
3. Add the server to your client (below). Once the package is on PyPI the command is
   `uvx bosco-labs-data-mcp`. Until then, run it from this folder:
   `uvx --from /path/to/bosco-labs-data/mcp bosco-labs-data-mcp`.

### Claude Desktop

`claude_desktop_config.json` (Settings -> Developer -> Edit Config):

```json
{
  "mcpServers": {
    "bosco-labs-data": {
      "command": "uvx",
      "args": ["bosco-labs-data-mcp"],
      "env": { "APIFY_TOKEN": "apify_api_..." }
    }
  }
}
```

### Cursor

`~/.cursor/mcp.json` (or `.cursor/mcp.json` in a project): the same `mcpServers` block as
above.

### Claude Code

```bash
claude mcp add bosco-labs-data -e APIFY_TOKEN=apify_api_... -- uvx bosco-labs-data-mcp
```

## Alternative: Apify's hosted MCP server

Without installing anything, you can use the same Actors through Apify's own MCP server
(OAuth or your token; each Actor becomes a tool with its full input):

```
https://mcp.apify.com?tools=Bosco_labs/esef-annual-reports,Bosco_labs/company-accounts,Bosco_labs/sec-insider-trades,Bosco_labs/sec-filings-feed,Bosco_labs/us-house-trades,Bosco_labs/eu-tenders,Bosco_labs/dod-contract-awards
```

This server is the lighter option: typed parameters, small defaults and compact results.

## Development

```bash
uv run --with pytest pytest -q    # from this folder; Apify is mocked, plus a stdio smoke test
```

Source and releases: https://github.com/PB7-debug/bosco-labs-data (folder `mcp/`). Releases are
published to PyPI and the official MCP Registry by the `publish-mcp.yml` GitHub Actions
workflow; see
[PUBLISHING.md](https://github.com/PB7-debug/bosco-labs-data/blob/main/mcp/PUBLISHING.md).

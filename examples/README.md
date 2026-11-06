# Bosco Labs recipes for AI-agent frameworks

Copy-paste examples that call Bosco Labs data Actors on Apify from popular agent frameworks.
Every call is billed per result to your own Apify account; get a token at https://console.apify.com/settings/integrations

| Recipe | Framework | Actor |
|---|---|---|
| [langchain_insider_trades.py](langchain_insider_trades.py) | LangChain / LangGraph agent with `ApifyActorsTool` | `bosco_labs/sec-insider-trades` |
| [llamaindex_sec_filings.py](llamaindex_sec_filings.py) | LlamaIndex `ApifyActor` reader + query engine | `bosco_labs/sec-filings-feed` |
| [crewai_congress_trades.py](crewai_congress_trades.py) | CrewAI agent with `crewai_tools.ApifyActorsTool` | `bosco_labs/us-house-trades` |
| [claude_mcp_sec.py](claude_mcp_sec.py) | Claude Messages API + Apify's hosted MCP server | `sec-insider-trades` + `sec-filings-feed` |
| [httpx_company_accounts.py](httpx_company_accounts.py) | Plain HTTP (`httpx`), no framework | `bosco_labs/company-accounts` |
| [n8n_insider_cluster_buys.json](n8n_insider_cluster_buys.json) | n8n workflow (HTTP Request node), import and run | `bosco_labs/sec-insider-trades` |

All tokens come from environment variables; never paste a token into code. Each file names the
docs it was written against in its header. Questions: support@boscolabs.dev

Pay-per-event pricing used below: SEC Insider Trades $0.0018 per transaction row and $0.02 per
cluster signal; SEC Filings Feed $0.001 per filing; Congress Stock Trades $0.0018 per trade;
Company Financials $0.04 per company-year. Your LLM provider bills its tokens separately.

---

## 1. LangChain / LangGraph: insider trades

**Answers:** "Did any Tesla insiders buy shares in the last 90 days?" The agent decides the
Actor input (for example `{"tickers": ["TSLA"], "transactionCodes": ["P"]}`) and cites each Form 4.

```bash
pip install langchain langgraph langchain-apify langchain-anthropic
export APIFY_TOKEN=...  ANTHROPIC_API_KEY=...
python langchain_insider_trades.py
```

`ApifyActorsTool` builds the tool's input schema from the Actor's published schema, so the agent
sees every filter (`tickers`, `transactionCodes`, `minValueUsd`, `clusterBuysOnly`, ...). Swap
`"anthropic:claude-opus-5-5"` for any `init_chat_model` provider string.

**Rows the tool returns** (from the Actor README):

```json
{"record_type": "transaction", "issuer_name": "CHESAPEAKE ENERGY CORP", "ticker": "CHK",
 "insider_name": "DUNHAM ARCHIE W", "insider_roles": ["director"], "transaction_date": "2015-03-27",
 "transaction_code": "P", "shares": 1000000, "price": 13.98, "value_usd": 13980000.0,
 "in_cluster": true, "filing_url": "https://www.sec.gov/Archives/edgar/data/895126/..."}
```

**Cost per run:** rows x $0.0018 plus $0.02 per cluster signal. The system prompt caps
`maxResults` at 50, so at most $0.09 in rows plus any cluster signals.

## 2. LlamaIndex: SEC filings as Documents

**Answers:** "Does Nvidia release earnings before the open or after the close?" Loads Nvidia's
last 8 earnings releases (8-K Item 2.02) as LlamaIndex `Document`s, one per filing, with the
filing link as metadata, then queries them.

```bash
pip install llama-index-core llama-index-readers-apify llama-index-llms-anthropic
export APIFY_TOKEN=...  ANTHROPIC_API_KEY=...
python llamaindex_sec_filings.py
```

**Rows the reader maps** (from the Actor README):

```json
{"form": "8-K", "company_name": "Apple Inc.", "ticker": "AAPL", "filing_date": "2026-11-02",
 "accepted_at": "2026-11-02T16:30:23-05:00", "market_timing": "after_close", "items": ["2.02", "9.01"],
 "primary_document_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019326000024/aapl-20261102.htm"}
```

**Cost per run:** 8 filings x $0.001 = $0.008.

## 3. CrewAI: congressional stock trades

**Answers:** "Which House members traded NVDA in the last year?" A single-agent crew calls the
Actor and returns a table with a link to each Periodic Transaction Report PDF.

```bash
pip install "crewai[tools,anthropic]" langchain-apify
export APIFY_API_TOKEN=...  ANTHROPIC_API_KEY=...
python crewai_congress_trades.py
```

CrewAI's `ApifyActorsTool` reads `APIFY_API_TOKEN` (not `APIFY_TOKEN`).

**Rows the tool returns** (from the Actor README):

```json
{"member_name": "Nancy Pelosi", "state_district": "CA11", "filing_date": "2025-10-24",
 "transaction_date": "2025-10-22", "owner": "SP", "ticker": "AAPL", "transaction_type": "sale",
 "amount_text": "$100,001 - $250,000",
 "pdf_url": "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2025/20033337.pdf"}
```

**Cost per run:** at most 25 trades x $0.0018 = $0.045.

## 4. Claude via MCP: no framework, two Actors as tools

**Answers:** "When did Nvidia publish its last earnings release, and did any Nvidia insiders sell
in the 30 days after it?" Claude chains two Actors loaded from Apify's hosted MCP server:

```text
https://mcp.apify.com?tools=bosco_labs/sec-insider-trades,bosco_labs/sec-filings-feed
```

```bash
pip install anthropic
export APIFY_TOKEN=...  ANTHROPIC_API_KEY=...
python claude_mcp_sec.py
```

Anthropic connects to the MCP server for you (the MCP connector, beta header
`mcp-client-2025-11-20`); your Apify token goes in `authorization_token`. The same server URL
works in Claude Desktop, Cursor or any MCP client with the header
`Authorization: Bearer <APIFY_TOKEN>`. The request also opts into server-side refusal fallbacks
(`fallbacks="default"`); remove both that line and its beta header if you don't want them.

**Cost per run:** a few filings at $0.001 each, plus up to 50 insider rows at $0.0018 ($0.09)
and $0.02 per cluster signal.

## 5. Plain HTTP: one POST, rows back

**Answers:** "What were Equinor's revenue, net income and equity in its latest filed accounts?"
No SDK: `run-sync-get-dataset-items` runs the Actor and returns its rows in one call.

```bash
pip install httpx
export APIFY_TOKEN=...
python httpx_company_accounts.py
```

The same call with curl:

```bash
curl -X POST "https://api.apify.com/v2/actors/bosco_labs~company-accounts/run-sync-get-dataset-items?maxTotalChargeUsd=0.5" \
  -H "Authorization: Bearer $APIFY_TOKEN" -H "Content-Type: application/json" \
  -d '{"countries": ["NO"], "orgNumbers": ["923609016"], "maxResults": 1}'
```

**Output excerpt** (from the Actor README):

```json
{"company_name": "EQUINOR ASA", "lei": "OW6OFBNCKXC4US5C7523", "period_end": "2025-12-31",
 "currency": "USD", "revenue": 61999000000, "net_income": 5731000000, "total_equity": 39182000000}
```

**Cost per run:** 1 company-year x $0.04 = $0.04. `maxTotalChargeUsd` caps any run you send this
way. Runs longer than 300 seconds return HTTP 408; use the async run endpoint for those.

## 6. n8n: insider cluster buys

**Answers:** "Where are several insiders of the same company buying their own stock right now?"
Open-market buys by 2 or more directors or officers of one company within 30 days, worth
$100,000 or more together, from the last 30 days of filings.

1. In n8n: Workflows, Import from File, choose `n8n_insider_cluster_buys.json`.
2. Open the HTTP Request node and create a **Header Auth** credential: name `Authorization`,
   value `Bearer <your Apify token>`.
3. Execute the workflow. Each row arrives as one n8n item; connect Slack, Sheets or email after
   it, or swap the manual trigger for a Schedule Trigger and add `"onlyNewSinceLastRun": true`
   to the JSON body so each run returns only new trades.

Built on n8n's core HTTP Request node, so no community node is needed. Apify also publishes an
n8n community node (`@apify/n8n-nodes-apify`, operation "Run an Actor and get dataset") if you
prefer it.

**Cost per run:** up to 50 rows x $0.0018 plus $0.02 per cluster signal; the
`maxTotalChargeUsd=1` query parameter caps it at $1.

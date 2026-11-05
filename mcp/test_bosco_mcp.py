import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bosco_mcp  # noqa: E402
from bosco_mcp import ToolError  # noqa: E402

LEI = "724500Y6DUVHQD6OXN27"
ESEF_ROW = {
    "record_type": "summary",
    "lei": LEI,
    "company_name": "ASML Holding N.V.",
    "country": "NL",
    "period_end": "2025-12-31",
    "currency": "EUR",
    "revenue": 32667300000,
    "net_income": 10213000000,
    "gross_profit": None,
    "revenue_growth": 0.0256,
    "sources": {"revenue": {"concept": "ifrs-full:Revenue"}},
    "prior_year": {"period_end": "2024-12-31", "revenue": 28262900000, "sources": {}},
    "viewer_url": "https://filings.xbrl.org/x/ixbrlviewer.html",
}


def call(tool: str, **args):
    res = asyncio.run(bosco_mcp.mcp.call_tool(tool, args))
    return res.structured_content["result"]


@pytest.fixture
def apify(monkeypatch):
    """Mock the Apify API; `apify.rows` is returned, `apify.seen` collects the requests."""

    class State:
        seen: list[httpx.Request] = []
        rows: list[dict] = [ESEF_ROW]
        response = None

    def handler(req: httpx.Request) -> httpx.Response:
        State.seen.append(req)
        return State.response(req) if State.response else httpx.Response(201, json=State.rows)

    State.seen = []
    real = httpx.AsyncClient
    mock = httpx.MockTransport(handler)
    monkeypatch.setattr(bosco_mcp.httpx, "AsyncClient", lambda **kw: real(transport=mock, **kw))
    monkeypatch.setenv("APIFY_TOKEN", "user_token")
    return State


CASES = [
    (
        "eu_annual_report_financials",
        {"lei": LEI.lower(), "max_results": 1},
        "esef-annual-reports",
        {"leis": [LEI], "countries": [], "maxFilings": 1, "includeRawFacts": False},
    ),
    (
        "eu_annual_report_financials",
        {"company": "heineken", "countries": ["nl"]},
        "esef-annual-reports",
        {"companyName": "heineken", "countries": ["NL"], "maxFilings": 3, "includeRawFacts": False},
    ),
    (
        "european_company_accounts",
        {"uk_company_numbers": ["3117531", "sc123456"], "no_org_numbers": ["923609016"]},
        "company-accounts",
        {
            "countries": ["GB", "NO"],
            "companyNumbers": ["03117531", "SC123456"],
            "orgNumbers": ["923609016"],
            "enrichLei": True,
            "maxResults": 3,
        },
    ),
    (
        "sec_insider_trades",
        {"tickers": ["aapl"], "date_from": "2026-01-01", "cluster": "buys", "max_results": 5},
        "sec-insider-trades",
        {
            "tickers": ["AAPL"],
            "minValueUsd": 0,
            "dateFrom": "2026-01-01",
            "lookbackDays": 30,
            "clusterBuysOnly": True,
            "clusterSellsOnly": False,
            "includeClusterSignals": False,
            "maxResults": 5,
        },
    ),
    (
        "sec_filings",
        {"ciks": ["320193"], "form_types": ["8-k"], "item_codes_8k": ["5.02"]},
        "sec-filings-feed",
        {
            "ciks": ["320193"],
            "formTypes": ["8-K"],
            "itemCodes": ["5.02"],
            "earningsReleasesOnly": False,
            "lookbackDays": 30,
            "maxResults": 25,
        },
    ),
    (
        "us_house_stock_trades",
        {"members": ["Pelosi"], "years": [2024], "transaction_types": ["purchase"]},
        "us-house-trades",
        {
            "members": ["Pelosi"],
            "transactionTypes": ["purchase"],
            "years": ["2024"],
            "maxResults": 25,
        },
    ),
    (
        "eu_public_tenders",
        {"keywords": " cloud ", "countries": ["de"], "cpv_codes": ["72"], "min_value_eur": 10},
        "eu-tenders",
        {
            "keywords": "cloud",
            "countries": ["DE"],
            "cpvCodes": ["72"],
            "minValueEur": 10,
            "maxResults": 25,
        },
    ),
    (
        "dod_contract_awards",
        {"tickers": ["ktos"], "date_to": "2026-06-30", "psc_codes": ["r425"]},
        "dod-contract-awards",
        {
            "tickers": ["KTOS"],
            "dateTo": "2026-06-30",
            "minAmountUsd": 7500000,
            "pscCodes": ["R425"],
            "maxResults": 10,
        },
    ),
]


@pytest.mark.parametrize("tool,args,actor,payload", CASES)
def test_tool_runs_its_actor_with_the_user_token(apify, tool, args, actor, payload):
    call(tool, **args)
    (req,) = apify.seen
    assert req.method == "POST"
    assert req.url.path == f"/v2/acts/Bosco_labs~{actor}/run-sync-get-dataset-items"
    assert req.headers["Authorization"] == "Bearer user_token"
    assert "user_token" not in str(req.url)
    assert json.loads(req.content) == payload


@pytest.mark.parametrize(
    "tool,args",
    [
        ("eu_annual_report_financials", {}),
        ("eu_annual_report_financials", {"company": "asml", "lei": LEI}),
        ("eu_annual_report_financials", {"lei": "123"}),
        ("eu_annual_report_financials", {"company": "asml", "countries": ["Netherlands"]}),
        ("eu_annual_report_financials", {"company": "asml", "max_results": 11}),
        ("european_company_accounts", {}),
        ("european_company_accounts", {"dk_cvr_numbers": ["123"]}),
        ("sec_insider_trades", {"tickers": ["NOT A TICKER"]}),
        ("sec_insider_trades", {"transaction_codes": ["Q"]}),
        ("sec_insider_trades", {"date_from": "2026-02-01", "date_to": "2026-01-01"}),
        ("sec_insider_trades", {"max_results": 101}),
        ("sec_filings", {"item_codes_8k": ["5"]}),
        ("sec_filings", {"date_from": "yesterday"}),
        ("us_house_stock_trades", {"years": [2010]}),
        ("us_house_stock_trades", {"tickers": ["AAPL"] * 26}),
        ("eu_public_tenders", {"notice_types": ["tender"]}),
        ("eu_public_tenders", {"cpv_codes": ["IT"]}),
        ("dod_contract_awards", {"max_results": 51}),
        ("dod_contract_awards", {"min_amount_usd": -1}),
    ],
)
def test_rejects_bad_input_without_calling_apify(apify, tool, args):
    with pytest.raises(ToolError):
        call(tool, **args)
    assert apify.seen == []


def test_missing_token(apify, monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN")
    with pytest.raises(ToolError, match="APIFY_TOKEN"):
        call("sec_filings", tickers=["AAPL"])
    assert apify.seen == []


@pytest.mark.parametrize(
    "status,match",
    [
        (401, "rejected the APIFY_TOKEN"),
        (402, "out of\\s+credit"),
        (403, "out of\\s+credit"),
        (408, "timed out"),
        (500, "HTTP 500: boom"),
    ],
)
def test_maps_apify_errors(apify, status, match):
    apify.response = lambda req: httpx.Response(
        status, json={"error": {"type": "x", "message": "boom"}}
    )
    with pytest.raises(ToolError, match=match):
        call("sec_filings", tickers=["AAPL"])


def test_maps_client_timeout(apify):
    def timeout(req):
        raise httpx.ReadTimeout("slow", request=req)

    apify.response = timeout
    with pytest.raises(ToolError, match="timed out"):
        call("dod_contract_awards")


def test_trims_esef_rows(apify):
    (rep,) = call("eu_annual_report_financials", lei=LEI)
    assert rep["revenue"] == 32667300000 and rep["revenue_growth"] == 0.0256
    assert "sources" not in rep and "gross_profit" not in rep and "record_type" not in rep
    assert rep["prior_year"] == {"period_end": "2024-12-31", "revenue": 28262900000}
    assert rep["viewer_url"].endswith("ixbrlviewer.html")


def test_trims_long_text_unknown_fields_and_extra_rows(apify):
    row = {"notice_id": "1", "description": "x" * 1000, "raw": {"big": 1}, "ted_url": "u"}
    apify.rows = [row] * 5
    out = call("eu_public_tenders", max_results=2)
    assert len(out) == 2
    assert out[0] == {"notice_id": "1", "description": "x" * 300 + "...", "ted_url": "u"}


def test_all_tools_registered_with_descriptions():
    tools = asyncio.run(bosco_mcp.mcp.list_tools())
    assert sorted(t.name for t in tools) == sorted(
        [
            "eu_annual_report_financials",
            "european_company_accounts",
            "sec_insider_trades",
            "sec_filings",
            "us_house_stock_trades",
            "eu_public_tenders",
            "dod_contract_awards",
        ]
    )
    for t in tools:
        assert len(t.description) > 200 and "$" in t.description, t.name
        assert t.input_schema["properties"]["max_results"]["maximum"] <= 100


def test_stdio_smoke():
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(HERE / "bosco_mcp.py")],
            env={**os.environ, "APIFY_TOKEN": ""},
        )
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            tools = (await s.list_tools()).tools
            res = await s.call_tool("sec_filings", {"tickers": ["AAPL"]})
            return tools, res

    tools, res = asyncio.run(run())
    assert len(tools) == 7
    assert res.is_error and "APIFY_TOKEN" in res.content[0].text

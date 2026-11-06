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
            "lei_lookup",
            "sec_company_lookup",
        ]
    )
    for t in tools:
        free = t.name in ("lei_lookup", "sec_company_lookup")
        assert len(t.description) > 200, t.name
        assert (
            t.description.startswith("Free, no API token needed.") if free else "$" in t.description
        )
        assert t.annotations.read_only_hint and t.annotations.open_world_hint, t.name
        assert t.title, t.name
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
    assert len(tools) == 9  # starts without a token; paid tools then explain the missing token
    assert res.is_error and "APIFY_TOKEN" in res.content[0].text


# --- Free tools (GLEIF, SEC): no token, open APIs mocked ------------------------------------

SUB_LEI = "2549008YU9EOMHFUA249"
SEC_TICKERS = {
    "fields": ["cik", "name", "ticker", "exchange"],
    "data": [
        [1652044, "Alphabet Inc.", "GOOGL", "Nasdaq"],
        [1652044, "Alphabet Inc.", "GOOG", "Nasdaq"],
        [320193, "Apple Inc.", "AAPL", "Nasdaq"],
        [948708, "SMITH MICRO SOFTWARE, INC.", "SMSI", "Nasdaq"],
        [789019, "MICROSOFT CORP", "MSFT", "Nasdaq"],
        [1067983, "BERKSHIRE HATHAWAY INC", "BRK-B", "NYSE"],
    ],
}


def lei_rec(lei, name, country="NL", reg_as="17085815", parent=False):
    link = f"https://api.gleif.org/api/v1/lei-records/{lei}/ultimate-parent"
    return {
        "type": "lei-records",
        "id": lei,
        "attributes": {
            "lei": lei,
            "entity": {
                "legalName": {"name": name},
                "legalAddress": {"country": country, "city": "Veldhoven"},
                "headquartersAddress": {"country": country},
                "registeredAs": reg_as,
                "jurisdiction": country,
                "status": "ACTIVE",
                "otherNames": [{"name": "x" * 5000}],  # dropped: the output stays small
            },
            "registration": {"status": "ISSUED"},
        },
        "relationships": {
            "ultimate-parent": {
                "links": {"lei-record": link} if parent else {"reporting-exception": "u"}
            }
        },
    }


def submissions(cik):
    rows = [r for r in SEC_TICKERS["data"] if r[0] == cik]
    return {
        "cik": f"{cik:010d}",
        "name": rows[0][1] if rows else "NO TICKER FILER",
        "tickers": [r[2] for r in rows],
        "exchanges": [r[3] for r in rows],
        "sic": "3571",
        "sicDescription": "Electronic Computers",
        "stateOfIncorporation": "CA",
        "fiscalYearEnd": "0926",
        "filings": {"recent": {"form": ["10-K"] * 1000}},  # dropped
    }


def open_api(req: httpx.Request) -> httpx.Response:
    path, q = req.url.path, req.url.params
    if req.url.host == "api.gleif.org":
        if path == f"/api/v1/lei-records/{SUB_LEI}/ultimate-parent":
            return httpx.Response(200, json={"data": lei_rec(LEI, "ASML Holding N.V.")})
        if path == f"/api/v1/lei-records/{SUB_LEI}":
            rec = lei_rec(SUB_LEI, "ASML Sub Ltd", "GB", "03117531", parent=True)
            return httpx.Response(200, json={"data": rec})
        if path == f"/api/v1/lei-records/{LEI}":
            return httpx.Response(200, json={"data": lei_rec(LEI, "ASML Holding N.V.")})
        if path == "/api/v1/autocompletions":
            ids = [] if q["q"] == "zzz" else [LEI, LEI, SUB_LEI]
            data = [{"relationships": {"lei-records": {"data": {"id": i}}}} for i in ids]
            return httpx.Response(200, json={"data": data})
        if path == "/api/v1/lei-records":  # filter[lei]; GLEIF does not keep the order
            ids = q["filter[lei]"].split(",")
            return httpx.Response(200, json={"data": [lei_rec(i, i) for i in ids[::-1]]})
    if req.url.host == "www.sec.gov" and path == "/files/company_tickers_exchange.json":
        return httpx.Response(200, json=SEC_TICKERS)
    if req.url.host == "data.sec.gov" and path.startswith("/submissions/CIK"):
        cik = int(path.removeprefix("/submissions/CIK").removesuffix(".json"))
        return httpx.Response(404) if cik == 999 else httpx.Response(200, json=submissions(cik))
    return httpx.Response(404)


@pytest.fixture
def web(monkeypatch):
    """Mock GLEIF and SEC; `web.seen` collects requests, `web.fail` = statuses to answer first."""

    class State:
        seen: list[httpx.Request] = []
        fail: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        State.seen.append(req)
        return httpx.Response(State.fail.pop(0)) if State.fail else open_api(req)

    State.seen, State.fail = [], []
    real = httpx.AsyncClient
    mock = httpx.MockTransport(handler)
    monkeypatch.setattr(bosco_mcp.httpx, "AsyncClient", lambda **kw: real(transport=mock, **kw))
    monkeypatch.setattr(bosco_mcp, "RETRY_DELAY", 0)
    monkeypatch.setattr(bosco_mcp, "_sec_tickers", {"rows": None, "at": 0.0})
    monkeypatch.delenv("APIFY_TOKEN", raising=False)  # free tools must work without it
    return State


def test_lei_lookup_by_lei(web):
    (row,) = call("lei_lookup", query=LEI.lower())
    assert row == {
        "lei": LEI,
        "legal_name": "ASML Holding N.V.",
        "entity_status": "ACTIVE",
        "registration_status": "ISSUED",
        "jurisdiction": "NL",
        "legal_address_country": "NL",
        "legal_address_city": "Veldhoven",
        "headquarters_country": "NL",
        "registered_as": "17085815",
        "source_url": f"https://search.gleif.org/#/record/{LEI}",
        "next_step": "Audited financials if it is an EU/UK listed company: Bosco Labs "
        "esef-annual-reports (paid; MCP tool eu_annual_report_financials in bosco-labs-data-mcp, "
        f"or apify.com/bosco_labs/esef-annual-reports) with lei='{LEI}'.",
    }
    assert len(web.seen) == 1  # no parent request when no parent is reported


def test_lei_lookup_parent_and_uk_next_step(web):
    (row,) = call("lei_lookup", query=SUB_LEI)
    assert row["ultimate_parent"] == {"lei": LEI, "legal_name": "ASML Holding N.V."}
    step = row["next_step"]
    assert "Bosco Labs company-accounts" in step and "european_company_accounts" in step
    assert "apify.com/bosco_labs/company-accounts) with uk_company_numbers=['03117531']" in step


def test_lei_lookup_by_name_dedupes_and_keeps_rank_order(web):
    rows = call("lei_lookup", query=" asml ", max_results=5)
    assert [r["lei"] for r in rows] == [LEI, SUB_LEI]
    assert web.seen[0].url.params["q"] == "asml"
    assert len(json.dumps(rows)) < 5000


@pytest.mark.parametrize(
    "tool,args,match",
    [
        ("lei_lookup", {"query": "00000000000000000000"}, "No LEI record"),
        ("lei_lookup", {"query": "zzz"}, "724500Y6DUVHQD6OXN27"),
        ("sec_company_lookup", {"query": "nosuchcompany"}, "AAPL"),
        ("sec_company_lookup", {"query": "999"}, "320193"),
    ],
)
def test_free_tools_not_found_teach(web, tool, args, match):
    with pytest.raises(ToolError, match=match):
        call(tool, **args)


@pytest.mark.parametrize(
    "tool,args",
    [
        ("lei_lookup", {"query": "a"}),
        ("lei_lookup", {"query": "asml", "max_results": 6}),
        ("sec_company_lookup", {"query": ""}),
        ("sec_company_lookup", {"query": "x" * 101}),
    ],
)
def test_free_tools_reject_bad_input(web, tool, args):
    with pytest.raises(ToolError):
        call(tool, **args)
    assert web.seen == []


def test_sec_lookup_by_ticker(web):
    (row,) = call("sec_company_lookup", query="aapl")
    assert row["cik"] == "320193" and row["name"] == "Apple Inc." and row["tickers"] == ["AAPL"]
    assert row["sic"] == "3571" and row["fiscal_year_end"] == "0926"
    assert row["source_url"] == "https://www.sec.gov/edgar/browse/?CIK=320193"
    assert "sec-filings-feed" in row["next_step"] and "sec_insider_trades" in row["next_step"]
    assert row["next_step"].endswith("with ciks=['320193'].")
    assert "filings" not in row
    tickers_req, sub_req = web.seen
    assert sub_req.url.path == "/submissions/CIK0000320193.json"
    assert all(r.headers["User-Agent"] == "BoscoLabs support@boscolabs.dev" for r in web.seen)


def test_sec_lookup_by_name_ranks_and_caches_tickers_file(web):
    assert [r["cik"] for r in call("sec_company_lookup", query="microsoft")] == ["789019"]
    assert [r["cik"] for r in call("sec_company_lookup", query="hathaway")] == ["1067983"]
    (row,) = call("sec_company_lookup", query="Alphabet", max_results=1)
    assert row["tickers"] == ["GOOGL", "GOOG"]
    assert len([r for r in web.seen if r.url.host == "www.sec.gov"]) == 1


def test_sec_lookup_by_cik_skips_tickers_file(web):
    (row,) = call("sec_company_lookup", query="0000777")
    assert row["cik"] == "777" and row["name"] == "NO TICKER FILER"
    assert [r.url.host for r in web.seen] == ["data.sec.gov"]


def test_free_tools_retry_once_then_teach(web):
    web.fail = [503]
    assert call("lei_lookup", query=LEI)[0]["lei"] == LEI
    assert len(web.seen) == 2
    web.fail = [429, 429]
    with pytest.raises(ToolError, match="rate-limiting"):
        call("lei_lookup", query=LEI)

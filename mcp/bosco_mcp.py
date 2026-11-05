"""Bosco Labs data: one MCP server (stdio) for the Bosco Labs Apify Actors.

Each tool runs one Actor with the user's own APIFY_TOKEN, so every row is billed to the user's
Apify account (pay per event).
"""

import os
from datetime import date
from typing import Annotated, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

OWNER = "Bosco_labs"
APIFY_API = "https://api.apify.com/v2"
RUN_TIMEOUT = 240  # s the Actor run may take; run-sync waits at most 300 s
HTTP_TIMEOUT = RUN_TIMEOUT + 30
MAX_LIST = 25  # items per list parameter
MAX_TEXT = 300  # long texts (notice/award descriptions) are cut to this many characters

mcp = MCPServer(
    "bosco-labs-data",
    instructions=(
        "Official-source data (SEC EDGAR, US House Clerk, USAspending, EU TED, ESEF annual "
        "reports, UK/DK/NO company registers). Every row returned is billed to the user's own "
        "Apify account, so request only as many rows as the question needs. Cite the source "
        "link of each row."
    ),
)
RO = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

# Shared parameter types (validated by the server before the tool body runs).
Ticker = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9.\-]{0,9}$")]
Cik = Annotated[str, Field(pattern=r"^\d{1,10}$")]
Tickers = Annotated[
    list[Ticker], Field(min_length=1, max_length=MAX_LIST, description="Stock tickers, e.g. AAPL")
]
Ciks = Annotated[
    list[Cik],
    Field(min_length=1, max_length=MAX_LIST, description="SEC CIKs, e.g. 320193 (Apple)"),
]
Day = Annotated[date, Field(description="YYYY-MM-DD")]
Names = Annotated[
    list[Annotated[str, Field(min_length=2, max_length=100)]],
    Field(min_length=1, max_length=MAX_LIST),
]


def limit(hard: int, unit: str):
    return Annotated[int, Field(ge=1, le=hard, description=f"Max {unit} to return (1-{hard}).")]


async def run_actor(actor: str, payload: dict) -> list[dict]:
    """Run Bosco_labs~<actor> synchronously and return its dataset items."""
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        raise ToolError(
            "APIFY_TOKEN is not set in the MCP server's environment. Get a token at "
            "https://console.apify.com/settings/integrations and add it to the server config."
        )
    url = f"{APIFY_API}/acts/{OWNER}~{actor}/run-sync-get-dataset-items"
    payload = {k: v for k, v in payload.items() if v is not None}
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.post(
                url,
                params={"timeout": RUN_TIMEOUT, "clean": "true"},
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.TimeoutException as e:
        raise ToolError("The Apify run timed out; narrow the query or lower max_results.") from e
    except httpx.HTTPError as e:
        raise ToolError(f"Could not reach Apify: {type(e).__name__}") from e
    if r.status_code < 400:
        items = r.json()
        if not isinstance(items, list):
            raise ToolError("Unexpected response from Apify (no dataset items).")
        return items
    try:
        msg = r.json()["error"]["message"]
    except Exception:
        msg = r.text[:300]
    if r.status_code == 401:
        raise ToolError("Apify rejected the APIFY_TOKEN (401): check the token is correct.")
    if r.status_code in (402, 403):
        raise ToolError(
            f"Apify refused the run ({r.status_code}): the Apify account is probably out of "
            f"credit or has hit its usage limit. Top up at https://console.apify.com/billing. "
            f"Apify says: {msg}"
        )
    if r.status_code == 408:
        raise ToolError("The Apify run timed out; narrow the query or lower max_results.")
    raise ToolError(f"Apify returned HTTP {r.status_code}: {msg}")


def pick(row: dict, keys: list[str]) -> dict:
    """Keep the key fields; drop empty ones and cut long texts so results stay compact."""
    out = {}
    for k in keys:
        v = row.get(k)
        if v is None or v == [] or v == "":
            continue
        if isinstance(v, str) and len(v) > MAX_TEXT:
            v = v[:MAX_TEXT] + "..."
        out[k] = v
    return out


def upper(values: list[str] | None) -> list[str] | None:
    return None if values is None else [v.strip().upper() for v in values]


def iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def check_range(start: date | None, end: date | None) -> None:
    if start and end and start > end:
        raise ToolError("The start date must be on or before the end date.")


async def fetch(actor: str, payload: dict, keys: list[str], cap: int) -> list[dict]:
    return [pick(row, keys) for row in (await run_actor(actor, payload))[:cap]]


# --- EU annual reports (ESEF) -------------------------------------------------------------

ESEF_METRICS = [
    "period_end", "fiscal_year_start", "currency", "revenue", "gross_profit",
    "operating_profit", "ebitda", "net_income", "eps_basic", "eps_diluted", "total_assets",
    "total_equity", "total_liabilities", "cash_and_equivalents", "operating_cash_flow",
    "dividend_per_share", "operating_margin", "net_margin", "return_on_equity", "equity_ratio",
    "metrics_found",
]  # fmt: skip
ESEF_KEYS = ["lei", "company_name", "country", *ESEF_METRICS, "revenue_growth"]
ESEF_LINKS = ["viewer_url", "report_url", "source_url"]


@mcp.tool(annotations=RO)
async def eu_annual_report_financials(
    company: Annotated[
        str | None,
        Field(min_length=2, max_length=100, description='Part of the name, e.g. "heineken"'),
    ] = None,
    lei: Annotated[
        str | None,
        Field(pattern=r"^[A-Za-z0-9]{20}$", description="20-character Legal Entity Identifier"),
    ] = None,
    countries: Annotated[
        list[Annotated[str, Field(pattern=r"^[A-Za-z]{2}$")]] | None,
        Field(max_length=MAX_LIST, description="ISO alpha-2 filing countries, e.g. ['NL']"),
    ] = None,
    max_results: limit(10, "annual reports") = 3,
) -> list[dict]:
    """Audited annual financials of European listed companies, from their official ESEF
    annual reports (source: filings.xbrl.org; EU/EEA, UK and Ukraine, about 27,600 reports from
    28 countries; Germany is not covered). Use it for revenue, profit, margins, EPS, balance
    sheet, cash flow or dividends of a listed European company.

    Pass exactly one of `lei` (most precise) or `company` (case-insensitive part of the
    registered name; it can match several companies, so check `company_name`). `countries`
    narrows a name search. Newest fiscal year first.

    Returns one row per annual report: lei, company_name, country, period_end, currency,
    revenue, gross_profit, operating_profit, ebitda, net_income, eps_basic/diluted,
    total_assets, total_equity, total_liabilities, cash_and_equivalents, operating_cash_flow,
    dividend_per_share, operating_margin, net_margin, return_on_equity, equity_ratio,
    revenue_growth, prior_year (same metrics for the comparative year) and viewer_url (cite
    it: the report page where every value can be checked). Money is in full units of
    `currency`; ratios are decimals (0.25 = 25%). A missing metric was not tagged in the
    report; never treat it as zero.

    Cost to the user: $0.05 per annual report plus $0.01 per call. Takes about 10-60 s.
    """
    lei = upper([lei])[0] if lei else None
    if bool(lei) == bool(company):
        raise ToolError("Pass exactly one of `company` or `lei`.")
    payload = {
        "leis": [lei] if lei else None,
        "companyName": company.strip() if company else None,
        "countries": upper(countries) or [],  # [] = all countries (the Actor defaults to NL)
        "maxFilings": max_results,
        "includeRawFacts": False,
    }
    out = []
    for row in (await run_actor("esef-annual-reports", payload))[:max_results]:
        if row.get("record_type", "summary") != "summary":
            continue
        rep = pick(row, ESEF_KEYS)
        if prior := pick(row.get("prior_year") or {}, ESEF_METRICS):
            rep["prior_year"] = prior
        out.append(rep | pick(row, ESEF_LINKS))
    return out


# --- UK / Danish / Norwegian company accounts ----------------------------------------------

ACCOUNTS_KEYS = [
    "company_name", "country", "company_number", "cvr", "org_number", "lei", "period_end",
    "fiscal_year_start", "currency", "revenue", "gross_profit", "operating_profit",
    "profit_before_tax", "net_income", "total_assets", "current_assets",
    "cash_and_equivalents", "total_equity", "net_assets", "total_liabilities", "employees",
    "metrics_found", "report_url", "registry_url", "source_url",
]  # fmt: skip


@mcp.tool(annotations=RO)
async def european_company_accounts(
    uk_company_numbers: Annotated[
        list[Annotated[str, Field(pattern=r"^[A-Za-z0-9]{1,8}$")]] | None,
        Field(max_length=MAX_LIST, description="Companies House numbers, e.g. 03117531"),
    ] = None,
    dk_cvr_numbers: Annotated[
        list[Annotated[str, Field(pattern=r"^\d{8}$")]] | None,
        Field(max_length=MAX_LIST, description="Danish 8-digit CVR numbers, e.g. 24256790"),
    ] = None,
    no_org_numbers: Annotated[
        list[Annotated[str, Field(pattern=r"^\d{9}$")]] | None,
        Field(max_length=MAX_LIST, description="Norwegian 9-digit org numbers, e.g. 923609016"),
    ] = None,
    max_results: limit(10, "company-years per country") = 3,
) -> list[dict]:
    """Financials of UK, Danish and Norwegian companies, including private ones, from the
    accounts they file with Companies House (UK), Erhvervsstyrelsen (DK) and the Brønnøysund
    Register of Company Accounts (NO). Use it for revenue, profit, equity, cash or employees of
    a (private) company in these countries when you know its registration number.

    Coverage: UK every year filed digitally (iXBRL; paper/PDF-only years are skipped, and small
    UK companies often file no profit and loss account); Denmark all years; Norway the last 3
    fiscal years (own accounts, not group).
    Pass at least one registration number. Newest fiscal year first.

    Returns one row per company per fiscal year: company_name, country, the registration
    number, lei, period_end, currency, revenue, gross_profit, operating_profit,
    profit_before_tax, net_income, total_assets, current_assets, cash_and_equivalents,
    total_equity, net_assets, total_liabilities, employees, metrics_found and the source links
    (report_url, registry_url, source_url). A missing figure was not filed; never treat it as
    zero.

    Cost to the user: $0.04 per company-year returned.
    """
    uk = [n.zfill(8) for n in upper(uk_company_numbers) or []]
    ids = {"GB": uk, "DK": dk_cvr_numbers or [], "NO": no_org_numbers or []}
    countries = [c for c, v in ids.items() if v]
    if not countries:
        raise ToolError("Pass at least one UK company number, Danish CVR or Norwegian org number.")
    payload = {
        "countries": countries,
        "companyNumbers": uk or None,
        "cvrNumbers": dk_cvr_numbers,
        "orgNumbers": no_org_numbers,
        "enrichLei": True,
        "maxResults": max_results,
    }
    return await fetch("company-accounts", payload, ACCOUNTS_KEYS, max_results * len(countries))


# --- SEC insider trades (Form 4) -----------------------------------------------------------

INSIDER_KEYS = [
    "filing_date", "ticker", "issuer_name", "insider_name", "insider_roles", "officer_title",
    "transaction_date", "transaction_code", "transaction_type", "shares", "price", "value_usd",
    "shares_owned_after", "ownership", "plan_10b5_1", "in_cluster", "cluster_insiders",
    "filing_url",
]  # fmt: skip
TxCode = Literal[
    "P", "S", "A", "D", "F", "M", "C", "X", "G", "J", "I", "L", "W", "E", "H", "O", "Z", "K", "U"
]  # fmt: skip


@mcp.tool(annotations=RO)
async def sec_insider_trades(
    tickers: Tickers | None = None,
    ciks: Ciks | None = None,
    transaction_codes: Annotated[
        list[TxCode] | None,
        Field(
            min_length=1,
            description="Form 4 codes; omit for P (open-market purchase) and S (sale). "
            "Others: A award, M option exercise, F tax withholding, G gift.",
        ),
    ] = None,
    insider_roles: list[Literal["director", "officer", "ten_percent_owner", "other"]] | None = None,
    min_value_usd: Annotated[int, Field(ge=0, description="Skip smaller trades")] = 0,
    date_from: Day | None = None,
    date_to: Day | None = None,
    lookback_days: Annotated[
        int | None,
        Field(
            ge=1,
            le=3650,
            description="Days back when date_from is omitted; omit for the default "
            "(90 days for tickers/CIKs, 7 days for the whole market)",
        ),
    ] = None,
    cluster: Annotated[
        Literal["buys", "sells", "both"] | None,
        Field(
            description="Only trades in a cluster: 2+ directors/officers of one company "
            "trading the same way within 30 days, together >= $100,000"
        ),
    ] = None,
    max_results: limit(100, "transactions") = 25,
) -> list[dict]:
    """US insider trades reported to the SEC on Form 4 (officers, directors, 10% owners),
    from today's filings back to 2006 (source: SEC EDGAR Form 4 XML and the SEC insider data
    sets). Use it for "who is buying/selling stock X", insider activity before an event, or
    market-wide insider buying (cluster buys).

    Filter by tickers or CIKs (omit both for the whole market; a whole-market scan of many
    days can take a minute or more, so prefer tickers). Filing date range: date_from/date_to,
    or the last `lookback_days` days. Newest first.

    Returns one row per transaction: filing_date, ticker, issuer_name, insider_name,
    insider_roles, officer_title, transaction_date, transaction_code (P buy, S sell, ...),
    shares, price, value_usd, shares_owned_after, plan_10b5_1 (pre-planned sale),
    in_cluster and filing_url (the SEC filing; cite it).

    Cost to the user: $0.0018 per transaction returned.
    """
    check_range(date_from, date_to)
    payload = {
        "tickers": upper(tickers),
        "ciks": ciks,
        "transactionCodes": transaction_codes,
        "insiderRoles": insider_roles,
        "minValueUsd": min_value_usd,
        "dateFrom": iso(date_from),
        "dateTo": iso(date_to),
        "lookbackDays": lookback_days,
        "clusterBuysOnly": cluster in ("buys", "both"),
        "clusterSellsOnly": cluster in ("sells", "both"),
        "includeClusterSignals": False,
        "maxResults": max_results,
    }
    return await fetch("sec-insider-trades", payload, INSIDER_KEYS, max_results)


# --- SEC EDGAR filings ----------------------------------------------------------------------

FILING_KEYS = [
    "filing_date", "accepted_at", "market_timing", "form", "ticker", "company_name", "cik",
    "items", "item_descriptions", "report_date", "primary_document_url", "filing_index_url",
]  # fmt: skip


@mcp.tool(annotations=RO)
async def sec_filings(
    tickers: Tickers | None = None,
    ciks: Ciks | None = None,
    form_types: Annotated[
        list[Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9 /\-]{0,19}$")]] | None,
        Field(max_length=MAX_LIST, description="e.g. 8-K, 10-K, 10-Q, S-1, 13D, DEF 14A"),
    ] = None,
    item_codes_8k: Annotated[
        list[Annotated[str, Field(pattern=r"^\d\.\d{2}$")]] | None,
        Field(
            max_length=MAX_LIST,
            description="Only 8-Ks with these items, e.g. 5.02 (officer change), 1.01, 2.01",
        ),
    ] = None,
    earnings_releases_only: Annotated[
        bool, Field(description="Only 8-K item 2.02 earnings releases")
    ] = False,
    date_from: Day | None = None,
    date_to: Day | None = None,
    lookback_days: Annotated[
        int | None,
        Field(
            ge=1,
            le=12000,
            description="Days back when date_from is omitted; omit to get a company's latest "
            "filings of any date (tickers/CIKs) or the last 7 days (whole market)",
        ),
    ] = None,
    max_results: limit(100, "filings") = 25,
) -> list[dict]:
    """SEC EDGAR filings of US-listed companies and other filers: any form (8-K, 10-K, 10-Q,
    S-1, 13D/13G, Form 4, DEF 14A, 20-F, ...), from filings accepted minutes ago back to 1994
    (source: SEC EDGAR submissions API, indexes and live feed). Use it to find a company's
    latest reports, earnings release dates and times, officer changes or other 8-K events, or
    market-wide filings of one type.

    Filter by tickers or CIKs (omit both for the whole market), form types, 8-K item codes or
    earnings releases only. Filing date range: date_from/date_to, or the last `lookback_days`
    days. Newest first.

    Returns one row per filing: filing_date, accepted_at, market_timing (before_open,
    market_hours, after_close), form, ticker, company_name, cik, items (8-K item codes),
    item_descriptions, report_date and links: primary_document_url (the document; cite it),
    filing_index_url.

    Cost to the user: $0.001 per filing returned.
    """
    check_range(date_from, date_to)
    payload = {
        "tickers": upper(tickers),
        "ciks": ciks,
        "formTypes": upper(form_types),
        "itemCodes": item_codes_8k,
        "earningsReleasesOnly": earnings_releases_only,
        "dateFrom": iso(date_from),
        "dateTo": iso(date_to),
        "lookbackDays": lookback_days,
        "maxResults": max_results,
    }
    return await fetch("sec-filings-feed", payload, FILING_KEYS, max_results)


# --- US House stock trades ------------------------------------------------------------------

HOUSE_KEYS = [
    "member_name", "state_district", "filing_date", "transaction_date", "days_to_disclose",
    "owner", "ticker", "asset_description", "asset_type", "transaction_type", "amount_min",
    "amount_max", "amount_text", "is_amendment", "pdf_url",
]  # fmt: skip


@mcp.tool(annotations=RO)
async def us_house_stock_trades(
    members: Annotated[
        Names | None, Field(description='Part of the member name, e.g. "Pelosi"')
    ] = None,
    tickers: Tickers | None = None,
    transaction_types: list[Literal["purchase", "sale", "exchange"]] | None = None,
    filed_from: Annotated[Day | None, Field(description="Default: 30 days ago")] = None,
    filed_to: Day | None = None,
    years: Annotated[
        list[Annotated[int, Field(ge=2014, le=2100)]] | None,
        Field(max_length=13, description="Whole filing years for history, e.g. [2020, 2021]"),
    ] = None,
    min_amount_usd: Annotated[
        int | None, Field(ge=0, description="e.g. 15001 skips the $1,001-$15,000 range")
    ] = None,
    max_results: limit(100, "trades") = 25,
) -> list[dict]:
    """Stock, option, fund and bond trades disclosed by members of the US House of
    Representatives under the STOCK Act (Periodic Transaction Reports), from January 2014 to
    today (source: official filings of the Clerk of the House). Use it for "what did
    Representative X trade", "which House members traded NVDA", or recent congressional trades.

    Filter by member name, tickers, transaction type and filing date (default: the last 30
    days); use `years` for older history. Newest filings first.

    Returns one row per trade: member_name, state_district, filing_date, transaction_date,
    days_to_disclose, owner (self, spouse, joint, child), ticker, asset_description,
    asset_type, transaction_type, amount_min/amount_max (USD range as filed), amount_text,
    is_amendment and pdf_url (the filing; cite it). Amounts are ranges, not exact values.
    The Senate is not covered.

    Cost to the user: $0.0018 per trade returned.
    """
    check_range(filed_from, filed_to)
    payload = {
        "members": members,
        "tickers": upper(tickers),
        "transactionTypes": transaction_types,
        "filedFrom": iso(filed_from),
        "filedTo": iso(filed_to),
        "years": [str(y) for y in years] if years else None,
        "minAmountUsd": min_amount_usd,
        "maxResults": max_results,
    }
    return await fetch("us-house-trades", payload, HOUSE_KEYS, max_results)


# --- EU public tenders (TED) ----------------------------------------------------------------

TENDER_KEYS = [
    "notice_id", "published", "notice_type", "title", "description", "buyer_name",
    "buyer_country", "main_cpv", "estimated_value", "awarded_value", "currency",
    "winner_names", "deadline", "procedure_type", "ted_url",
]  # fmt: skip
NoticeType = Literal[
    "contract_notice", "contract_award", "prior_information",
    "direct_award_preannouncement", "contract_modification", "market_consultation",
]  # fmt: skip


@mcp.tool(annotations=RO)
async def eu_public_tenders(
    keywords: Annotated[
        str | None,
        Field(max_length=200, description="All words must appear, any language, e.g. cloud"),
    ] = None,
    countries: Annotated[
        list[Annotated[str, Field(pattern=r"^[A-Za-z]{2,3}$")]] | None,
        Field(max_length=MAX_LIST, description="Buyer countries, ISO codes, e.g. ['DE', 'FR']"),
    ] = None,
    cpv_codes: Annotated[
        list[Annotated[str, Field(pattern=r"^\d{2,8}$")]] | None,
        Field(
            max_length=MAX_LIST,
            description="CPV sector prefixes: 72 IT services, 45 construction, 3312 medical",
        ),
    ] = None,
    notice_types: Annotated[
        list[NoticeType] | None,
        Field(
            min_length=1,
            description="Omit for open calls for tenders (contract_notice); "
            "contract_award = who won and for how much",
        ),
    ] = None,
    published_from: Annotated[Day | None, Field(description="Default: 7 days ago")] = None,
    published_to: Day | None = None,
    min_value_eur: Annotated[
        int | None, Field(ge=0, description="Leaves out notices without an EUR value")
    ] = None,
    max_results: limit(100, "notices") = 25,
) -> list[dict]:
    """European public procurement notices from TED (Tenders Electronic Daily), the EU's
    official procurement journal: every above-threshold public contract in the EU/EEA,
    Switzerland and more, about 22,000 notices a week (source: official TED Search API). Use
    it to find open calls for tenders (with deadline and estimated value), contract awards
    (winners and awarded value) or planned purchases, by keyword, buyer country or sector.

    Default: open calls for tenders published in the last 7 days. Newest first.

    Returns one row per notice: notice_id, published, notice_type, title, description
    (shortened), buyer_name, buyer_country, main_cpv, estimated_value, awarded_value,
    currency, winner_names, deadline, procedure_type and ted_url (the notice; cite it).

    Cost to the user: $0.002 per notice returned.
    """
    check_range(published_from, published_to)
    payload = {
        "keywords": keywords.strip() if keywords else None,
        "countries": upper(countries),
        "cpvCodes": cpv_codes,
        "noticeTypes": notice_types,
        "publishedFrom": iso(published_from),
        "publishedTo": iso(published_to),
        "minValueEur": min_value_eur,
        "maxResults": max_results,
    }
    return await fetch("eu-tenders", payload, TENDER_KEYS, max_results)


# --- DoD / federal contract awards ----------------------------------------------------------

DOD_KEYS = [
    "action_date", "recipient_name", "parent_name", "ticker", "amount_usd", "new_award",
    "awarding_agency", "awarding_sub_agency", "award_id", "naics_description",
    "psc_description", "description", "shares_outstanding", "usaspending_url",
]  # fmt: skip


@mcp.tool(annotations=RO)
async def dod_contract_awards(
    recipients: Annotated[
        Names | None, Field(description='Winner or parent name contains, e.g. "kratos"')
    ] = None,
    tickers: Tickers | None = None,
    date_from: Annotated[
        Day | None, Field(description="Signing date; default: 135 days before date_to")
    ] = None,
    date_to: Day | None = None,
    min_amount_usd: Annotated[
        int, Field(ge=0, description="Min obligated per award and day")
    ] = 7_500_000,
    agencies: Annotated[
        Names | None,
        Field(description='Top-tier agency; omit for DoD; e.g. "Department of Homeland Security"'),
    ] = None,
    naics_codes: Annotated[
        list[Annotated[str, Field(pattern=r"^\d{2,6}$")]] | None,
        Field(max_length=MAX_LIST, description="Industry codes, e.g. 336414"),
    ] = None,
    psc_codes: Annotated[
        list[Annotated[str, Field(pattern=r"^[A-Za-z0-9]{4}$")]] | None,
        Field(max_length=MAX_LIST, description="Product/service codes, e.g. 1410, R425"),
    ] = None,
    max_results: limit(50, "award rows") = 10,
) -> list[dict]:
    """US Department of Defense contract awards (or any other federal agency's) since FY2008:
    who won, how much was obligated, which service, the parent company and the winner's US
    stock ticker with SEC shares outstanding (source: USAspending.gov / FPDS, tickers from the
    SEC). Use it for "which contracts did Lockheed/Kratos win", the largest recent Pentagon
    awards, or awards in an industry (NAICS/PSC).

    Default: DoD award-days of at least $7.5M (the DoD's public announcement threshold),
    signed in the last 135 days. DoD data is published with a delay of up to ~3 months, so
    the most recent weeks are incomplete. Newest signing dates first, then largest amounts.
    Slow: a call can take a minute or more, so keep max_results small.

    Returns one row per award per signing day: action_date, recipient_name, parent_name,
    ticker, amount_usd (summed obligations that day), new_award, awarding_agency,
    awarding_sub_agency, award_id, naics_description, psc_description, description
    (shortened), shares_outstanding and usaspending_url (the award page; cite it).

    Cost to the user: $0.005 per award row returned.
    """
    check_range(date_from, date_to)
    payload = {
        "recipients": recipients,
        "tickers": upper(tickers),
        "dateFrom": iso(date_from),
        "dateTo": iso(date_to),
        "minAmountUsd": min_amount_usd,
        "agencies": agencies,
        "naicsCodes": naics_codes,
        "pscCodes": upper(psc_codes),
        "maxResults": max_results,
    }
    return await fetch("dod-contract-awards", payload, DOD_KEYS, max_results)


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()

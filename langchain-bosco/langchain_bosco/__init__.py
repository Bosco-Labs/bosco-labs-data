"""LangChain tools for Bosco Labs: official records (company registers, SEC EDGAR, sanctions
lists, EU and national law) for agents, each row with its source URL. https://boscolabs.dev"""

import os
import re
from typing import Any

import httpx
from langchain_core.tools import BaseTool, BaseToolkit, ToolException
from pydantic import BaseModel, Field

__all__ = [
    "BoscoTool",
    "BoscoToolkit",
    "CounterpartyCheckTool",
    "PlanOfficialRecordsQueryTool",
    "run_bosco_tool",
]

DEFAULT_BASE_URL = "https://api.boscolabs.dev"
TIMEOUT = 65.0  # the API answers within 60 s (its own budget is 55 s)


def _post(path: str, body: dict, api_key: str | None, base_url: str, keyed: bool) -> dict:
    headers = {}
    if keyed:
        key = api_key or os.environ.get("BOSCO_API_KEY")
        if not key:
            raise ToolException(
                "Bosco Labs API key missing: set BOSCO_API_KEY or pass api_key. "
                "Get one at https://boscolabs.dev/api.html"
            )
        headers["Authorization"] = f"Bearer {key}"
    res = httpx.post(f"{base_url}{path}", json=body, headers=headers, timeout=TIMEOUT)
    try:
        data = res.json()
    except ValueError:
        data = None
    if res.is_error:
        err = (data or {}).get("error") or {}
        msg = err.get("message") or res.reason_phrase
        raise ToolException(f"Bosco Labs {res.status_code} {err.get('code', '')}: {msg}")
    return data


def run_bosco_tool(
    name: str, input: dict, api_key: str | None = None, base_url: str = DEFAULT_BASE_URL
) -> dict:
    """Call any Bosco Labs tool ("counterparty-check" or "counterparty_check") with its input.
    Paid: needs an API key (BOSCO_API_KEY). Raises ToolException on an API error."""
    slug = name.replace("_", "-")
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        raise ToolException(f"Not a Bosco Labs tool name: {name}")
    return _post(f"/v1/{slug}", input, api_key, base_url, keyed=True)


class _Bosco(BaseTool):
    api_key: str | None = Field(default=None, exclude=True, repr=False)
    base_url: str = DEFAULT_BASE_URL
    handle_tool_error: bool = True  # API errors go back to the model as text


class CounterpartyCheckInput(BaseModel):
    query: str = Field(
        pattern=r"^[^\[\]{}<>\r\n]*$",
        description='Company name (e.g. "Novo Nordisk") or identifier: LEI, UK company number, '
        "Danish CVR, Norwegian org number, French SIREN/SIRET, Finnish Business ID, Estonian "
        "registry code, US ticker or SEC CIK.",
    )
    country: str | None = Field(
        default=None,
        pattern=r"^\s*([A-Za-z]{2})?\s*$",
        description='ISO 3166 alpha-2 country code to disambiguate, e.g. "DK", "GB", "NO".',
    )
    vatNumber: str | None = Field(
        default=None, description='EU VAT number with country prefix, e.g. "DK24256790".'
    )
    iban: str | None = Field(
        default=None, description="IBAN the counterparty wants to be paid on (checked offline)."
    )
    walletAddresses: list[str] | None = Field(
        default=None, max_length=10, description="Crypto wallet addresses, matched against OFAC."
    )


class CounterpartyCheckTool(_Bosco):
    name: str = "counterparty_check"
    description: str = (
        "Can I do business with this company? One KYB checklist from official sources: register "
        "status, LEI, insolvency, recent accounts, sanctions (OFAC, UN, UK, EU) on the company "
        "and its officers, VAT (VIES) and IBAN when given. Screening aid, not a compliance, "
        "credit or legal determination. Costs $0.05 per company checked; an ambiguous name "
        "returns candidates for free."
    )
    args_schema: type[BaseModel] = CounterpartyCheckInput

    def _run(self, **kwargs: Any) -> dict:
        body = {k: v for k, v in kwargs.items() if v is not None}
        return run_bosco_tool("counterparty-check", body, self.api_key, self.base_url)


class PlanInput(BaseModel):
    question: str = Field(max_length=1000, description="The user's question, verbatim.")
    entities: dict[str, Any] | None = Field(
        default=None,
        description="What you already extracted from the question; the planner trusts it. Keys: "
        "company_names, person_names, tickers, countries (lists of strings), identifiers "
        '({"lei": [...], "vat": [...], ...}), keywords, date_from, date_to (YYYY-MM-DD).',
    )


class PlanOfficialRecordsQueryTool(_Bosco):
    name: str = "plan_official_records_query"
    description: str = (
        "Free, no key needed. Turns a question in plain words into the exact typed Bosco Labs "
        "calls that answer it (tool, input, why, maximum price of each step) and what is not "
        "covered. Pass the question verbatim and the entities you extracted from it, then run "
        "each step with the tool of that name."
    )
    args_schema: type[BaseModel] = PlanInput

    def _run(self, question: str, entities: dict | None = None) -> dict:
        body = {"question": question} | ({"entities": entities} if entities else {})
        return _post("/v1/plan", body, None, self.base_url, keyed=False)


class ToolInput(BaseModel):
    input: dict[str, Any] = Field(
        description="The tool input as a JSON object, e.g. a step's `input` from "
        "plan_official_records_query."
    )


class BoscoTool(_Bosco):
    """Any Bosco Labs tool by slug, taking its input as one JSON object."""

    slug: str
    args_schema: type[BaseModel] = ToolInput

    def _run(self, input: dict) -> dict:
        return run_bosco_tool(self.slug, input, self.api_key, self.base_url)


class BoscoToolkit(BaseToolkit):
    """The free planner plus one tool per entry of GET /v1/tools?compact=true."""

    api_key: str | None = Field(default=None, exclude=True, repr=False)
    base_url: str = DEFAULT_BASE_URL

    def get_tools(self) -> list[BaseTool]:
        res = httpx.get(f"{self.base_url}/v1/tools", params={"compact": "true"}, timeout=30)
        res.raise_for_status()
        tools: list[BaseTool] = [PlanOfficialRecordsQueryTool(base_url=self.base_url)]
        for t in res.json()["tools"]:
            needs = t.get("needs") or ", ".join(t.get("required", [])) or "see the planner"
            desc = (
                f"{t['title']}. {t['description']} Input needs: {needs}. Price: "
                f"${t['price_usd_per_unit']} per {t['event']} (typical call "
                f"${t['typical_call_usd']}). Get the exact input from "
                "plan_official_records_query."
            )
            tools.append(
                BoscoTool(
                    name=t["tool"].replace("-", "_"),
                    slug=t["tool"],
                    description=desc,
                    api_key=self.api_key,
                    base_url=self.base_url,
                )
            )
        return tools

"""Offline: httpx is mocked, nothing reaches the API."""

import httpx
import langchain_bosco as lb
import pytest

CATALOGUE = {
    "tools": [
        {
            "tool": "counterparty-check",
            "title": "Counterparty Check API",
            "description": "KYB checklist per company...",
            "event": "counterparty-check",
            "price_usd_per_unit": 0.05,
            "typical_call_usd": 0.05,
            "required": ["query"],
        },
        {
            "tool": "sanctions-screening",
            "title": "Sanctions Screening API",
            "description": "OFAC, UN, UK, EU...",
            "event": "name-screened",
            "price_usd_per_unit": 0.002,
            "typical_call_usd": 0.002,
            "required": [],
            "needs": "names or addresses",
        },
    ]
}


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def post(url, json, headers, timeout):
        seen.append((url, json, headers))
        if url.endswith("/v1/sanctions-screening"):
            body = {"error": {"code": "insufficient_credits", "message": "Top up"}}
            return httpx.Response(402, json=body, request=httpx.Request("POST", url))
        return httpx.Response(200, json={"rows": [{"ok": True}]})

    def get(url, params, timeout):
        seen.append((url, params, None))
        return httpx.Response(200, json=CATALOGUE, request=httpx.Request("GET", url))

    monkeypatch.setattr(lb.httpx, "post", post)
    monkeypatch.setattr(lb.httpx, "get", get)
    monkeypatch.delenv("BOSCO_API_KEY", raising=False)
    return seen


def test_counterparty_check_sends_key_and_input(calls):
    out = lb.CounterpartyCheckTool(api_key="k1").invoke({"query": "24256790", "country": "DK"})
    url, body, headers = calls[0]
    assert url == "https://api.boscolabs.dev/v1/counterparty-check"
    assert body == {"query": "24256790", "country": "DK"}
    assert headers == {"Authorization": "Bearer k1"}
    assert out == {"rows": [{"ok": True}]}


def test_planner_is_free(calls):
    lb.PlanOfficialRecordsQueryTool().invoke({"question": "Is Rosneft sanctioned?"})
    url, body, headers = calls[0]
    assert url == "https://api.boscolabs.dev/v1/plan"
    assert body == {"question": "Is Rosneft sanctioned?"}
    assert headers == {}


def test_key_from_env_and_missing_key(calls, monkeypatch):
    assert "API key missing" in lb.CounterpartyCheckTool().invoke({"query": "x"})
    assert calls == []
    monkeypatch.setenv("BOSCO_API_KEY", "envkey")
    lb.run_bosco_tool("company_check", {"query": "a"})
    assert calls[0][0].endswith("/v1/company-check")
    assert calls[0][2] == {"Authorization": "Bearer envkey"}


def test_errors_reach_the_model_as_text(calls):
    out = lb.BoscoTool(name="s", slug="sanctions-screening", description="d", api_key="k")
    assert out.invoke({"input": {"names": ["x"]}}) == (
        "Bosco Labs 402 insufficient_credits: Top up"
    )
    with pytest.raises(lb.ToolException, match="Not a Bosco Labs tool name"):
        lb.run_bosco_tool("../me", {}, api_key="k")


def test_toolkit_loads_compact_catalogue(calls):
    tools = lb.BoscoToolkit(api_key="k").get_tools()
    assert calls[0][1] == {"compact": "true"}
    assert [t.name for t in tools] == [
        "plan_official_records_query",
        "counterparty_check",
        "sanctions_screening",
    ]
    assert "names or addresses" in tools[2].description
    tools[1].invoke({"input": {"query": "Novo Nordisk"}})
    assert calls[1][0].endswith("/v1/counterparty-check")
    assert calls[1][1] == {"query": "Novo Nordisk"}

"""Vendor onboarding check on the Bosco Labs API.

    from vendor_check import check_vendor
    result = check_vendor("Novo Nordisk A/S", country="DK")

With BOSCO_API_KEY set (or api_key=...) this runs the paid `counterparty-check` ($0.05 per
company; an ambiguous name returns free candidates). Without a key it uses the free endpoints
only: the planner (POST /v1/plan) and the free LEI and SEC lookups (/mcp/free).
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

__all__ = ["check_vendor", "demo_names", "VendorCheckError"]
__version__ = "0.1.0"

API = os.environ.get("BOSCO_API_URL", "https://api.boscolabs.dev")
GET_KEY = "https://boscolabs.dev/api.html"
FIXTURE = Path(__file__).with_name("demo_fixture.json")


class VendorCheckError(Exception):
    pass


def _post(path: str, body: dict, key: str | None = None, timeout: float = 90) -> dict:
    headers = {
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
        "user-agent": f"vendor-check/{__version__}",
    }
    if key:
        headers["authorization"] = f"Bearer {key}"
    req = urllib.request.Request(API + path, json.dumps(body).encode(), headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e).get("error") or {}
        except ValueError:
            err = {}
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise VendorCheckError(f"HTTP {e.code} from {path}: {msg or e.reason}") from None
    except urllib.error.URLError as e:
        raise VendorCheckError(f"Cannot reach {API}: {e.reason}") from None


def _free_tool(name: str, query: str) -> list[dict]:
    """Call one free lookup on the keyless MCP endpoint (stateless JSON-RPC, no session)."""
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": {"query": query, "max_results": 3}},
    }
    res = _post("/mcp/free", body).get("result") or {}
    if res.get("isError"):
        return []
    rows = (res.get("structuredContent") or {}).get("result") or []
    return rows if isinstance(rows, list) else [rows]


def free_check(name: str, country: str | None = None) -> dict:
    entities = {"company_names": [name], **({"countries": [country]} if country else {})}
    plan = _post(
        "/v1/plan", {"question": f"Counterparty check of supplier {name}", "entities": entities}
    )
    leis = _free_tool("lei_lookup", name)
    if country:  # keep the candidates from the country asked for
        leis = [r for r in leis if r.get("legal_address_country") == country.upper()] or leis
    sec = _free_tool("sec_company_lookup", name) if (country or "").upper() == "US" else []
    return {
        "mode": "free",
        "query": name,
        "country": country,
        "plan": plan,
        "lei_candidates": leis,
        "sec_matches": sec,
    }


def paid_check(name: str, key: str, country=None, vat_number=None, iban=None) -> dict:
    body = {"query": name, "country": country, "vatNumber": vat_number, "iban": iban}
    resp = _post("/v1/counterparty-check", {k: v for k, v in body.items() if v}, key)
    rows = resp.get("rows") or []
    return {
        "mode": "paid",
        "query": name,
        "country": country,
        "row": rows[0] if rows else None,
        "charged_usd": resp.get("charged_usd"),
        "warnings": resp.get("warnings", []),
    }


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def demo_names() -> list[str]:
    return [c["query"] for c in _fixture()["companies"]]


def demo_check(name: str) -> dict:
    fx = _fixture()
    for c in fx["companies"]:
        if c["query"].casefold() == name.strip().casefold():
            return {
                **c,
                "mode": c.get("mode", "free"),
                "demo": True,
                "fetched_at": fx["fetched_at"],
                "label": c.get("label", fx["label"]),
            }
    raise VendorCheckError(f"{name!r} is not in the demo set; try one of {demo_names()}")


def check_vendor(
    name: str,
    country: str | None = None,
    vat_number: str | None = None,
    iban: str | None = None,
    api_key: str | None = None,
    demo: bool = False,
) -> dict:
    """Check one supplier. Returns a dict with `mode` "paid", "free" or demo data.

    paid: `row` is the counterparty-check row (`checks`: pass, fail, review or unverified, each
    with a source_url). free: `plan` (what the paid check would cost) and `lei_candidates`.
    """
    if not name or not name.strip():
        raise VendorCheckError("A company name or identifier is required")
    if demo:
        return demo_check(name)
    key = api_key or os.environ.get("BOSCO_API_KEY")
    if key:
        return paid_check(name.strip(), key, country, vat_number, iban)
    return free_check(name.strip(), country)


def price_usd(result: dict) -> float | None:
    """The maximum price of the paid check, as the free planner quoted it."""
    return (result.get("plan") or {}).get("total_max_usd")

"""Bosco Labs x402 example agent: screen a company on sanctions lists, then look it up.

Every call is paid per call in USDC on Base with x402 (scheme `upto`: you pay only what is
delivered). No Bosco Labs account or API key. The wallet key comes from X402_PRIVATE_KEY.

    python agent.py "Novo Nordisk A/S" --country DK            # sanctions, then company-check
    python agent.py "Apple Inc" --identifiers                   # sanctions, then identifier-resolver
    python agent.py "Novo Nordisk A/S" --dry-run                # show the 402 quote, pay nothing
"""

import argparse
import asyncio
import base64
import json
import os

import httpx

API = "https://api.boscolabs.dev"
NETWORK = "eip155:8453"  # Base mainnet
RPC = "https://mainnet.base.org"


def b64json(value):
    return json.loads(base64.b64decode(value)) if value else None


def quote(path, payload):
    """Call without paying: the API answers 402 with the price in the PAYMENT-REQUIRED header."""
    r = httpx.post(API + path, json=payload, timeout=60)
    print(f"{path}: HTTP {r.status_code}")
    for offer in (b64json(r.headers.get("payment-required")) or {}).get("accepts", []):
        print(f"  {offer['scheme']:5} up to ${int(offer['amount']) / 1e6:.4f} USDC on {offer['network']}")


async def paid_call(http, path, payload):
    """POST with x402: the client reads the 402, signs the USDC payment and retries."""
    r = await http.post(API + path, json=payload)
    body = r.json()
    settled = b64json(r.headers.get("payment-response"))
    tx = settled.get("transaction") if settled else None
    print(f"{path}: HTTP {r.status_code}, charged ${body.get('charged_usd', 0)}, tx {tx or '-'}")
    if r.status_code == 404:  # no_results: nothing was settled
        return []
    if r.status_code != 200:
        raise SystemExit(f"{path} failed: {body.get('error')}")
    return body["rows"]


async def run(name, country, identifiers):
    from eth_account import Account
    from x402 import x402Client
    from x402.http.clients.httpx import x402HttpxClient
    from x402.mechanisms.evm.signers import EthAccountSignerWithRPC
    from x402.mechanisms.evm.upto.client import UptoEvmScheme

    account = Account.from_key(os.environ["X402_PRIVATE_KEY"])  # never hardcode a key
    client = x402Client()
    client.register(NETWORK, UptoEvmScheme(EthAccountSignerWithRPC(account, RPC)))
    print(f"Paying from {account.address} (USDC on Base)")

    async with x402HttpxClient(client, timeout=90) as http:
        screen = {"names": [name], "entityType": "organization"} | ({"country": country} if country else {})
        hit = (await paid_call(http, "/v1/sanctions-screening", screen) or [{}])[0]
        print(f"  {hit.get('summary', 'no answer')}")
        if hit.get("match_found"):
            print("Possible sanctions match: stopping here, review it by hand.")
            return

        if identifiers:
            rows = await paid_call(http, "/v1/identifier-resolver", {"identifier": name, "idType": "name"})
            for row in rows:
                print(f"  {row['issuer_name']}: LEI {row['lei']}, ISIN {row['isin']}, CIK {row['cik']}")
                print(f"  tickers {[t.get('ticker') for t in row['tickers']]}  source {row['source_url']}")
        else:
            check = {"query": name, "include": ["identity", "financials"]} | ({"country": country} if country else {})
            for row in await paid_call(http, "/v1/company-check", check):
                who = row.get("identity") or {}
                print(f"  {who.get('legal_name')} ({who.get('country')}), {who.get('status')}, LEI {who.get('lei')}")
                print(f"  {who.get('register')} no. {who.get('registration_number')}; sources: {len(row['sources'])}")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("name", help="company name, e.g. 'Novo Nordisk A/S'")
    p.add_argument("--country", help="ISO alpha-2 country, e.g. DK (sharpens both lookups)")
    p.add_argument("--identifiers", action="store_true", help="resolve LEI/ISIN/CIK/tickers instead of company-check")
    p.add_argument("--dry-run", action="store_true", help="only show the 402 price quote; no key, nothing paid")
    a = p.parse_args()
    if a.dry_run:
        quote("/v1/sanctions-screening", {"names": [a.name]})
        return
    asyncio.run(run(a.name, a.country, a.identifiers))


if __name__ == "__main__":
    main()

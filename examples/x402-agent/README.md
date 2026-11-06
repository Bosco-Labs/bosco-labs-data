# x402 example agent: sanctions check, then company data

A small agent that pays the Bosco Labs API per call in USDC on Base with
[x402](https://www.x402.org/). No account, no API key, no sign-up.

Given a company name it:

1. screens the name on the OFAC, US Consolidated, UK and EU sanctions lists
   (`POST /v1/sanctions-screening`, $0.01 per name);
2. stops if there is a possible match;
3. if clear, fetches company data from the national registers and GLEIF
   (`POST /v1/company-check`, $0.03 per report), or with `--identifiers` resolves its
   LEI, ISIN, CIK and tickers (`POST /v1/identifier-resolver`, $0.002).

For each call it prints what was charged (`charged_usd`) and the settlement transaction hash.
Current prices for every tool: `GET https://api.boscolabs.dev/v1/tools`.

## How the payment works

- Any `POST https://api.boscolabs.dev/v1/<tool>` without an API key answers
  `402 Payment Required` with a `PAYMENT-REQUIRED` header (x402 v2) that states the price.
- The x402 client signs a USDC authorization and retries. With the `upto` scheme you authorize
  the quoted maximum and only what was delivered is settled (rows x price, at least $0.005).
- Empty answers (`404`, `no_results`) settle nothing.
- USDC on Base mainnet only; no ETH needed for gas (gasless permit).

## Run it

Use a **dedicated wallet** for this, holding only a few dollars of USDC on Base. Never use the
key of a wallet with real savings, and never commit the key.

```bash
pip install -r requirements.txt
python agent.py "Novo Nordisk A/S" --dry-run          # shows the 402 quote; no key, pays nothing

export X402_PRIVATE_KEY=0x...                          # the dedicated wallet's key
python agent.py "Novo Nordisk A/S" --country DK        # sanctions check, then company-check
python agent.py "Apple Inc" --identifiers               # sanctions check, then identifier-resolver
```

A full run costs about $0.04 (company-check) or $0.012 (identifiers).

## Use it from your own code

The payment part is a few lines (from `agent.py`):

```python
import os
from eth_account import Account
from x402 import x402Client
from x402.http.clients.httpx import x402HttpxClient
from x402.mechanisms.evm.signers import EthAccountSignerWithRPC
from x402.mechanisms.evm.upto.client import UptoEvmScheme

client = x402Client()
account = Account.from_key(os.environ["X402_PRIVATE_KEY"])
client.register("eip155:8453", UptoEvmScheme(EthAccountSignerWithRPC(account, "https://mainnet.base.org")))
async with x402HttpxClient(client, timeout=90) as http:
    r = await http.post("https://api.boscolabs.dev/v1/sanctions-screening", json={"names": ["Sovcomflot"]})
```

The settlement is in the `payment-response` response header (base64 JSON with `transaction`).
TypeScript: `@x402/fetch` with `UptoEvmScheme` from `@x402/evm/upto/client`; see the
[official x402 fetch docs](https://github.com/coinbase/x402/tree/main/typescript/packages/http/fetch).

More on the API, prices and limits: https://boscolabs.dev/api.html#x402

Sanctions results are information with a source link per list, not legal advice. Questions:
support@boscolabs.dev

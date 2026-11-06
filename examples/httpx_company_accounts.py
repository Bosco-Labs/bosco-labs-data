# Plain HTTP, no framework: Bosco Labs Company Financials (bosco_labs/company-accounts).
# Docs: https://docs.apify.com/api/v2/act-run-sync-get-dataset-items-post
#       https://docs.apify.com/api/v2  (Authentication: "Authorization: Bearer <token>")
# One POST runs the Actor and returns its dataset items. Runs over 300 s return HTTP 408;
# use the async run endpoint for long jobs.
#
#   pip install httpx
#   export APIFY_TOKEN=...        # https://console.apify.com/settings/integrations
import json
import os

import httpx

resp = httpx.post(
    "https://api.apify.com/v2/actors/bosco_labs~company-accounts/run-sync-get-dataset-items",
    headers={"Authorization": f"Bearer {os.environ['APIFY_TOKEN']}"},
    params={"maxTotalChargeUsd": 0.50},  # hard cap on what this run can cost you
    json={"countries": ["NO"], "orgNumbers": ["923609016"], "maxResults": 1},  # Equinor, latest year
    timeout=310,
)
resp.raise_for_status()

for row in resp.json():
    print(json.dumps({k: row.get(k) for k in (
        "company_name", "lei", "period_end", "currency", "revenue", "net_income", "total_equity",
    )}, indent=2))

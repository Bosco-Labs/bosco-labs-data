# Claude (Anthropic Messages API) calling Bosco Labs Actors through Apify's hosted MCP server.
# Docs: https://docs.apify.com/platform/integrations/mcp  (tools= query parameter, Bearer token)
#       https://platform.claude.com/docs/en/agents-and-tools/mcp-connector  (mcp_servers + mcp_toolset)
# Checked against anthropic 2.6.0 (the create() parameters exist; no live run).
# unverified: that Apify accepts the token sent through the connector's authorization_token
# (Apify documents "Authorization: Bearer <APIFY_TOKEN>"; the connector sends OAuth Bearer tokens).
#
#   pip install anthropic
#   export APIFY_TOKEN=...        # https://console.apify.com/settings/integrations
#   export ANTHROPIC_API_KEY=...
import os

import anthropic

client = anthropic.Anthropic()
response = client.beta.messages.create(
    model="claude-opus-5-5",
    max_tokens=16000,
    betas=["mcp-client-2025-11-20", "server-side-fallback-2026-07-01"],
    fallbacks="default",  # another model answers if this one declines
    mcp_servers=[{
        "type": "url",
        "url": "https://mcp.apify.com?tools=bosco_labs/sec-insider-trades,bosco_labs/sec-filings-feed",
        "name": "bosco-labs",
        "authorization_token": os.environ["APIFY_TOKEN"],
    }],
    tools=[{"type": "mcp_toolset", "mcp_server_name": "bosco-labs"}],
    system="Keep maxResults at 50 or less on every Actor call (billed per row). Cite filing URLs.",
    messages=[{"role": "user", "content": (
        "When did Nvidia publish its last earnings release, and did any Nvidia insiders sell "
        "shares in the 30 days after it?"
    )}],
)

if response.stop_reason == "refusal":
    print("Declined:", response.stop_details)
for block in response.content:
    if block.type == "text":
        print(block.text)

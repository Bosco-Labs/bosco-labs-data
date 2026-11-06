# LangChain / LangGraph agent with Bosco Labs SEC Insider Trades (bosco_labs/sec-insider-trades).
# Docs: https://docs.apify.com/platform/integrations/langgraph
#       https://docs.apify.com/platform/integrations/langchain
# Checked against langchain 1.4.9, langchain-apify 0.2.0, langchain-anthropic 1.7.10 (imports and
# signatures only; no live run).
#
#   pip install langchain langgraph langchain-apify langchain-anthropic
#   export APIFY_TOKEN=...        # https://console.apify.com/settings/integrations
#   export ANTHROPIC_API_KEY=...
from langchain.agents import create_agent
from langchain_apify import ApifyActorsTool

# The tool reads the Actor's input schema from Apify when it is created, so APIFY_TOKEN must be set.
insider_trades = ApifyActorsTool("bosco_labs/sec-insider-trades")

agent = create_agent(
    "anthropic:claude-opus-5-5",  # any init_chat_model provider string works here
    [insider_trades],
    system_prompt=(
        "You answer questions about SEC Form 4 insider trades. Always pass maxResults of 50 or "
        "less (the Actor bills per row). Cite the filing_url of every trade you mention."
    ),
)

question = "Did any Tesla insiders buy shares in the last 90 days?"
result = agent.invoke({"messages": [("human", question)]})
print(result["messages"][-1].text)

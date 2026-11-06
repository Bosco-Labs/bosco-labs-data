# CrewAI agent with Bosco Labs Congress Stock Trades (bosco_labs/us-house-trades).
# Docs: https://docs.apify.com/platform/integrations/crewai
# Checked against crewai 1.15.35, crewai-tools 1.15.35, langchain-apify 0.2.0 (imports and
# signatures only; no live run).
#
#   pip install "crewai[tools,anthropic]" langchain-apify
#   export APIFY_API_TOKEN=...    # CrewAI's tool reads this name; https://console.apify.com/settings/integrations
#   export ANTHROPIC_API_KEY=...
from datetime import date, timedelta

from crewai import LLM, Agent, Crew, Task
from crewai_tools import ApifyActorsTool

# The tool reads the Actor's input schema from Apify when it is created, so the token must be set.
house_trades = ApifyActorsTool(actor_name="bosco_labs/us-house-trades")

analyst = Agent(
    role="Congressional trading analyst",
    goal="Report which stocks House members traded, with links to the filings",
    backstory="You read STOCK Act Periodic Transaction Reports and summarise them plainly.",
    tools=[house_trades],
    llm=LLM(model="anthropic/claude-opus-5-5"),
)

task = Task(
    description=(
        "Find House members' NVDA trades filed in the last 365 days. Call the tool with run_input "
        f'{{"tickers": ["NVDA"], "filedFrom": "{date.today() - timedelta(days=365)}", "maxResults": 25}}.'
    ),
    expected_output="A table: member, transaction_date, purchase or sale, amount_text, pdf_url.",
    agent=analyst,
)

print(Crew(agents=[analyst], tasks=[task]).kickoff())

# langchain-bosco

LangChain tools for [Bosco Labs](https://boscolabs.dev): answers from official records
(company registers, SEC EDGAR, sanctions lists, EU and national law, ECB and Eurostat), each
row with its source URL.

```bash
pip install langchain-bosco
```

```python
from langchain.agents import create_agent
from langchain_bosco import CounterpartyCheckTool, PlanOfficialRecordsQueryTool

agent = create_agent(
    "openai:gpt-5-mini",
    tools=[CounterpartyCheckTool(), PlanOfficialRecordsQueryTool()],  # key: BOSCO_API_KEY
)
result = agent.invoke(
    {"messages": [{"role": "user", "content": "Can we pay Novo Nordisk (CVR 24256790)?"}]}
)
print(result["messages"][-1].content)
```

## Tools

| Class | What it does | Price |
| --- | --- | --- |
| `CounterpartyCheckTool` | KYB checklist for one company: register status, LEI, insolvency, recent accounts, sanctions (OFAC, UN, UK, EU) on the company and its officers, VAT (VIES) and IBAN when given. | $0.05 per company checked; an ambiguous name returns candidates free |
| `PlanOfficialRecordsQueryTool` | A question in plain words -> the exact Bosco Labs calls, their input and maximum price. | Free, no key |
| `BoscoTool(name=..., slug=..., description=...)` | Any Bosco Labs tool by slug; input is one JSON object. | The tool's price |
| `BoscoToolkit().get_tools()` | The planner plus one `BoscoTool` per tool in [`/v1/tools?compact=true`](https://api.boscolabs.dev/v1/tools?compact=true). | Per tool |
| `run_bosco_tool(name, input)` | Plain function, for code outside an agent. | The tool's price |

```python
from langchain_bosco import BoscoToolkit

tools = BoscoToolkit().get_tools()  # one HTTP call to the free catalogue
```

## Auth

Paid tools need a Bosco Labs API key (prepaid credits): get one at
<https://boscolabs.dev/api.html> and set `BOSCO_API_KEY`, or pass `api_key=...` to a tool or
the toolkit. Every tool and the toolkit also take `base_url`. The planner needs no key.

API errors (bad input, no credits, a source down) come back to the model as text
(`handle_tool_error=True`); `run_bosco_tool` raises `ToolException`. Nothing is charged on an
error.

Docs: <https://boscolabs.dev/llms.txt> - OpenAPI: <https://api.boscolabs.dev/openapi.json> -
support: support@boscolabs.dev

The counterparty check is a screening aid, not a compliance, credit or legal determination:
review every `fail` and `review` before acting.

## Development

```bash
uv run --isolated --with-editable . --with pytest pytest -q
```

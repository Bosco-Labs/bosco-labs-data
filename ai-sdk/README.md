# @bosco_labs/ai-sdk

[Vercel AI SDK](https://ai-sdk.dev) tools for [Bosco Labs](https://boscolabs.dev): answers from
official records (company registers, SEC EDGAR, sanctions lists, EU and national law, ECB and
Eurostat), each row with its source URL.

```bash
npm install @bosco_labs/ai-sdk ai zod
```

```ts
import { generateText, isStepCount } from 'ai';
import { counterpartyCheck, planOfficialRecordsQuery, callBoscoTool } from '@bosco_labs/ai-sdk';

const { text } = await generateText({
  model: 'openai/gpt-5-mini',
  prompt: 'Can we pay invoice DK5000400440116243 from Novo Nordisk (CVR 24256790)?',
  tools: { counterpartyCheck: counterpartyCheck(), plan: planOfficialRecordsQuery(), callBoscoTool: callBoscoTool() },
  stopWhen: isStepCount(5),
});
console.log(text);
```

## Tools

| Export | What it does | Price |
| --- | --- | --- |
| `counterpartyCheck()` | KYB checklist for one company: register status, LEI, insolvency, recent accounts, sanctions (OFAC, UN, UK, EU) on the company and its officers, VAT (VIES) and IBAN when given. | $0.05 per company checked; an ambiguous name returns candidates free |
| `planOfficialRecordsQuery()` | A question in plain words -> the exact Bosco Labs calls, their input and maximum price. | Free, no key |
| `callBoscoTool()` | Runs any Bosco Labs tool with its input (e.g. a step from the planner). | The tool's price ([catalogue](https://api.boscolabs.dev/v1/tools?compact=true)) |
| `runBoscoTool(name, input)` | The same as a plain async function, for code outside a model call. | The tool's price |

## Auth

Paid tools need a Bosco Labs API key (prepaid credits; a new key comes with $5 of free credit,
no card): get one at <https://boscolabs.dev/api.html> and set `BOSCO_API_KEY`, or pass it:
`counterpartyCheck({ apiKey: process.env.MY_KEY })`. Every factory also takes `baseUrl`.
The planner needs no key.

API errors (bad input, no credits, a source down) throw an `Error` with the API's code and
message; the AI SDK returns it to the model as a tool error. Nothing is charged on an error.

Docs: <https://boscolabs.dev/llms.txt> - OpenAPI: <https://api.boscolabs.dev/openapi.json> -
support: support@boscolabs.dev

The counterparty check is a screening aid, not a compliance, credit or legal determination:
review every `fail` and `review` before acting.

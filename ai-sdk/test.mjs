// Offline check of the built package: fetch is mocked, nothing reaches the API.
import assert from 'node:assert/strict';
import { counterpartyCheck, planOfficialRecordsQuery, callBoscoTool, runBoscoTool } from './dist/index.js';

const calls = [];
globalThis.fetch = async (url, init) => {
  calls.push({ url, init });
  const fail = url.endsWith('/v1/sanctions-screening');
  return new Response(JSON.stringify(fail ? { error: { code: 'insufficient_credits', message: 'Top up' } } : { ok: true }),
    { status: fail ? 402 : 200 });
};
const opts = { toolCallId: '1', messages: [] };

await counterpartyCheck({ apiKey: 'k1' }).execute({ query: '24256790', country: 'DK' }, opts);
assert.equal(calls[0].url, 'https://api.boscolabs.dev/v1/counterparty-check');
assert.equal(calls[0].init.headers.Authorization, 'Bearer k1');
assert.deepEqual(JSON.parse(calls[0].init.body), { query: '24256790', country: 'DK' });

await planOfficialRecordsQuery().execute({ question: 'Is Rosneft sanctioned?' }, opts);
assert.equal(calls[1].url, 'https://api.boscolabs.dev/v1/plan');
assert.equal(calls[1].init.headers.Authorization, undefined); // free: no key sent

process.env.BOSCO_API_KEY = 'envkey';
await callBoscoTool({ baseUrl: 'http://x' }).execute({ tool: 'company_check', input: { query: 'a' } }, opts);
assert.equal(calls[2].url, 'http://x/v1/company-check');
assert.equal(calls[2].init.headers.Authorization, 'Bearer envkey');

await assert.rejects(runBoscoTool('sanctions-screening', {}), /402 insufficient_credits: Top up/);
await assert.rejects(runBoscoTool('../me', {}), /Not a Bosco Labs tool name/);
delete process.env.BOSCO_API_KEY;
await assert.rejects(runBoscoTool('company-check', {}), /API key missing/);
console.log('ai-sdk: all checks passed');

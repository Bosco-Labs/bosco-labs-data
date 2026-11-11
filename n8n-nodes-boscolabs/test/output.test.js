'use strict';

// What the node returns: one item per row, the full response on request, simplified rows,
// and what a user sees when the API refuses a call. HTTP is mocked: no live calls.

const test = require('node:test');
const assert = require('node:assert/strict');

const { run, ok } = require('./helpers.js');
const { SIMPLE_FIELDS } = require('../dist/nodes/BoscoLabs/request.js');

// Shapes follow recorded answers of the live API (shortened); company names are public companies.
const COUNTERPARTY_ROW = {
	schema_version: '1',
	query: 'Carillion plc',
	status: 'checked',
	company: { legal_name: 'CARILLION PLC', country: 'GB', registration_number: '03782379' },
	checks: [{ check: 'register_status', status: 'fail', detail: 'Register status: liquidation.' }],
	summary: { pass: 3, fail: 2, review: 0, unverified: 4, needs_attention: ['register_status'] },
	notice: 'Screening aid built from official sources.',
	latest_financials: null,
	people: { officers: [] },
	insolvency: { notices: [] },
	us_listing: null,
	sanctions: { entity: {} },
	vat: null,
	iban: null,
	wallets: [],
	warnings: [],
	source_url: 'https://find-and-update.company-information.service.gov.uk/company/03782379',
	retrieved_at: '2026-11-10T23:28:32+00:00',
};

const VAT_ROWS = [
	{
		query: 'IE6388047V',
		check_type: 'vat',
		status: 'pass',
		valid: true,
		checks: [],
		source: 'VIES',
	},
	{
		query: 'NL91ABNA0417164300',
		check_type: 'iban',
		status: 'pass',
		valid: true,
		bank_code: 'ABNA',
	},
];

const envelope = (tool, rows, extra = {}) => ({
	tool,
	rows,
	count: rows.length,
	warnings: [],
	message: '',
	charged_usd: 0.004,
	balance_usd: 4.9,
	duration_seconds: 1.2,
	...extra,
});

const VAT_PARAMS = {
	resource: 'vatIban',
	operation: 'check',
	vatNumbers: 'IE6388047V',
	ibans: 'NL91ABNA0417164300',
};

test('output: one item per row, linked to its input item', async () => {
	const { output, error } = await run({
		params: { ...VAT_PARAMS, simplify: false },
		respond: () => ok(envelope('vat-iban-check', VAT_ROWS)),
	});
	assert.equal(error, undefined);
	assert.deepEqual(output, [
		{ json: VAT_ROWS[0], pairedItem: { item: 0 } },
		{ json: VAT_ROWS[1], pairedItem: { item: 0 } },
	]);
});

test('output: Return Full Response gives one item with the whole answer', async () => {
	const body = envelope('vat-iban-check', VAT_ROWS);
	const { output } = await run({
		params: { ...VAT_PARAMS, options: { returnFullResponse: true } },
		respond: () => ok(body),
	});
	assert.deepEqual(output, [{ json: body, pairedItem: { item: 0 } }]);
	assert.equal(output[0].json.charged_usd, 0.004);
});

test('output: Simplify keeps the checklist and the summary a workflow branches on', async () => {
	const { output } = await run({
		params: {
			resource: 'company',
			operation: 'checkCounterparty',
			query: 'Carillion plc',
			simplify: true,
		},
		respond: () => ok(envelope('counterparty-check', [COUNTERPARTY_ROW])),
	});
	assert.equal(output.length, 1);
	const row = output[0].json;
	assert.equal(row.summary.fail, 2);
	assert.deepEqual(row.summary.needs_attention, ['register_status']);
	assert.equal(row.checks[0].status, 'fail');
	assert.equal(row.source_url, COUNTERPARTY_ROW.source_url);
	assert.equal(row.people, undefined);
	assert.equal(row.sanctions, undefined);
	assert.ok(Object.keys(row).length <= 10);
});

test('output: Simplify is on by default and never keeps more than 10 fields', async () => {
	const { output } = await run({
		params: { resource: 'company', operation: 'checkCounterparty', query: 'Carillion plc' },
		respond: () => ok(envelope('counterparty-check', [COUNTERPARTY_ROW])),
	});
	assert.equal(output[0].json.notice, undefined);
	for (const [tool, fields] of Object.entries(SIMPLE_FIELDS)) {
		// a company-accounts row carries one of three register numbers; the other two are dropped
		const dropped = tool === 'company-accounts' ? 2 : 0;
		assert.ok(fields.length - dropped <= 10, tool);
	}
});

test('output: a company-accounts row keeps the number of its own register only', async () => {
	const row = {
		country: 'NO',
		company_number: null,
		cvr: null,
		org_number: '999999999',
		company_name: 'EXAMPLE AS',
		period_end: '2025-12-31',
		currency: 'NOK',
		revenue: null,
		net_income: 120000,
		total_assets: 900000,
		total_equity: 400000,
		employees: null,
		sources: {},
		source_url: 'https://data.brreg.no/regnskapsregisteret/regnskap/999999999',
	};
	const { output } = await run({
		params: {
			resource: 'company',
			operation: 'getAccounts',
			orgNumbers: '999999999',
			maxResults: 1,
		},
		respond: () => ok(envelope('company-accounts', [row])),
	});
	const simple = output[0].json;
	assert.equal(simple.org_number, '999999999');
	assert.ok(!('cvr' in simple) && !('company_number' in simple));
	assert.equal(simple.revenue, null, 'a figure the accounts do not give stays null');
	assert.equal(simple.sources, undefined);
	assert.equal(Object.keys(simple).length, 10);
});

test('output: no rows gives no items and passes the API message on as a hint', async () => {
	const { output, hints, error } = await run({
		params: { resource: 'company', operation: 'getNewUk', sicCodes: '99999', maxResults: 100 },
		respond: () =>
			ok(
				envelope('uk-new-companies', [], {
					message: 'No companies incorporated 2026-11-09..2026-11-09. Nothing was charged.',
					warnings: ['Companies House stopped answering; partial results (0).'],
					charged_usd: 0,
				}),
			),
	});
	assert.equal(error, undefined);
	assert.deepEqual(output, []);
	assert.deepEqual(
		hints.map((h) => h.type),
		['warning', 'info'],
	);
	assert.match(hints[1].message, /Nothing was charged/);
});

test('refused input: the API message is shown with how to fix it', async () => {
	const { error, output } = await run({
		params: { resource: 'company', operation: 'getReport', query: 'zzzz no such company' },
		respond: () => ({
			statusCode: 400,
			headers: {},
			body: {
				error: {
					code: 'invalid_input',
					message: 'No company found for "zzzz". Nothing was charged.',
				},
			},
		}),
	});
	assert.equal(output, undefined);
	assert.equal(error.name, 'NodeApiError');
	assert.equal(error.message, 'No company found for "zzzz". Nothing was charged.');
	assert.equal(error.httpCode, '400');
	assert.match(error.description, /Change the fields of this node/);
	assert.equal(error.context.itemIndex, 0);
});

test('unknown key and empty balance: the description says where to go', async () => {
	const unknownKey = await run({
		params: VAT_PARAMS,
		respond: () => ({
			statusCode: 401,
			headers: {},
			body: { error: { code: 'bad_key', message: 'That API key is unknown or was replaced.' } },
		}),
	});
	assert.equal(unknownKey.error.httpCode, '401');
	assert.match(unknownKey.error.description, /Bosco Labs API credential/);
	assert.match(unknownKey.error.description, /Nothing was charged/);

	const noCredits = await run({
		params: VAT_PARAMS,
		respond: () => ({
			statusCode: 402,
			headers: {},
			body: {
				error: {
					code: 'insufficient_credits',
					message: 'This call may cost up to 0.004 USD; your balance does not cover it.',
				},
			},
		}),
	});
	assert.equal(noCredits.error.httpCode, '402');
	assert.match(noCredits.error.description, /boscolabs\.dev\/api\.html/);
});

test('a gateway page instead of JSON still gives a readable message', async () => {
	const { error } = await run({
		params: VAT_PARAMS,
		respond: () => ({ statusCode: 502, headers: {}, body: '<html>Bad Gateway</html>' }),
	});
	assert.equal(error.httpCode, '502');
	assert.match(error.message, /HTTP status 502/);
});

test('Continue On Fail: a refused item becomes an item with the message, the rest still runs', async () => {
	const { output, error, calls } = await run({
		continueOnFail: true,
		items: [{ json: {} }, { json: {} }],
		params: [
			{ ...VAT_PARAMS, vatNumbers: 'XX1', ibans: '' },
			{ ...VAT_PARAMS, simplify: false },
		],
		respond: (options, index) =>
			index === 0
				? {
						statusCode: 400,
						headers: {},
						body: {
							error: { code: 'invalid_input', message: 'Not a VAT number. Nothing was charged.' },
						},
					}
				: ok(envelope('vat-iban-check', VAT_ROWS)),
	});
	assert.equal(error, undefined);
	assert.equal(calls.length, 2);
	assert.deepEqual(output[0], {
		json: { error: 'Not a VAT number. Nothing was charged.' },
		pairedItem: { item: 0 },
	});
	assert.deepEqual(output[1], { json: VAT_ROWS[0], pairedItem: { item: 1 } });
});

test('a network failure is wrapped for the n8n UI', async () => {
	const { error } = await run({
		params: VAT_PARAMS,
		respond: () => {
			throw Object.assign(new Error('connect ETIMEDOUT'), { code: 'ETIMEDOUT' });
		},
	});
	assert.equal(error.name, 'NodeApiError');
});

// ---- input the API would refuse is stopped before any request ------------------------------

const REFUSED_BEFORE_SENDING = [
	{
		name: 'no company',
		params: { resource: 'company', operation: 'checkCounterparty', query: '  ' },
		message: /'Company' is empty/,
	},
	{
		name: 'more than 10 VAT numbers',
		params: {
			resource: 'vatIban',
			operation: 'check',
			vatNumbers: Array.from({ length: 11 }, (_, i) => `IE638804${i}V`).join(','),
		},
		message: /'VAT Numbers' takes at most 10 values per call, got 11/,
	},
	{
		name: 'more than 50 names',
		params: {
			resource: 'sanctions',
			operation: 'screen',
			names: Array.from({ length: 51 }, (_, i) => `Name ${i}`).join('\n'),
		},
		message: /'Names' takes at most 50 values per call, got 51/,
	},
	{
		name: 'nothing to screen',
		params: { resource: 'sanctions', operation: 'screen', names: '' },
		message: /Nothing to screen/,
	},
	{
		name: 'nothing to check',
		params: { resource: 'vatIban', operation: 'check', vatNumbers: '', ibans: '' },
		message: /Nothing to check/,
	},
	{
		name: 'accounts without a registration number',
		params: { resource: 'company', operation: 'getAccounts', maxResults: 5 },
		message: /No registration number given/,
	},
	{
		name: 'accounts for more than 5 companies',
		params: {
			resource: 'company',
			operation: 'getAccounts',
			companyNumbers: '1,2,3',
			cvrNumbers: '4,5',
			orgNumbers: '6',
			maxResults: 5,
		},
		message: /At most 5 companies per call/,
	},
	{
		name: 'max results over the API cap',
		params: { resource: 'company', operation: 'getNewUk', maxResults: 500 },
		message: /'Max Results' must be a whole number from 1 to 200/,
	},
	{
		name: 'a date that is not YYYY-MM-DD',
		params: {
			resource: 'company',
			operation: 'getNewUk',
			incorporatedFrom: '04/11/2026',
			maxResults: 10,
		},
		message: /'Incorporated From' must be a date as YYYY-MM-DD/,
	},
	{
		name: 'a question over 1000 characters',
		params: { resource: 'question', operation: 'plan', question: 'x'.repeat(1001) },
		message: /at most 1000 characters/,
	},
];

for (const c of REFUSED_BEFORE_SENDING) {
	test(`not sent: ${c.name}`, async () => {
		const { error, calls } = await run({ params: c.params });
		assert.equal(calls.length, 0, 'no request, so nothing can be charged');
		assert.equal(error.name, 'NodeOperationError');
		assert.match(error.message, c.message);
		assert.ok(error.description, 'says how to get unstuck');
	});
}

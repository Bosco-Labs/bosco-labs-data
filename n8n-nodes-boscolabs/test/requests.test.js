'use strict';

// The request the node sends for each operation must match the API contract
// (test/api-contract.json, a snapshot of GET /v1/tools). HTTP is mocked: no live calls.

const test = require('node:test');
const assert = require('node:assert/strict');

const contract = require('./api-contract.json').tools;
const pkg = require('../package.json');
const { run } = require('./helpers.js');
const { BoscoLabs } = require('../dist/nodes/BoscoLabs/BoscoLabs.node.js');
const { USER_AGENT, VERSION } = require('../dist/nodes/BoscoLabs/request.js');

/** Checks one request body against the published schema of its tool. */
function assertMatchesContract(tool, body) {
	const schema = contract[tool];
	assert.ok(schema, `unknown tool ${tool}`);
	for (const name of schema.required) {
		assert.ok(name in body, `${tool}: required field ${name} is missing`);
	}
	for (const [name, value] of Object.entries(body)) {
		const field = schema.properties[name];
		assert.ok(field, `${tool}: the API has no input field '${name}'`);
		if (field.type === 'string') {
			assert.equal(typeof value, 'string', `${tool}.${name} must be a string`);
			assert.notEqual(value, '', `${tool}.${name}: empty strings are left out`);
		}
		if (field.type === 'integer') {
			assert.ok(Number.isInteger(value), `${tool}.${name} must be an integer`);
			if (field.minimum !== undefined) assert.ok(value >= field.minimum, `${tool}.${name} min`);
			if (field.maximum !== undefined) assert.ok(value <= field.maximum, `${tool}.${name} max`);
		}
		if (field.type === 'boolean') assert.equal(typeof value, 'boolean', `${tool}.${name}`);
		if (field.type === 'array') {
			assert.ok(Array.isArray(value), `${tool}.${name} must be an array`);
			for (const entry of value) assert.equal(typeof entry, 'string', `${tool}.${name} items`);
			if (field.maxItems !== undefined) {
				assert.ok(value.length <= field.maxItems, `${tool}.${name} maxItems`);
			}
			for (const entry of value) {
				if (field.itemEnum) assert.ok(field.itemEnum.includes(entry), `${tool}.${name}: ${entry}`);
				if (field.itemSuggested) {
					assert.ok(field.itemSuggested.includes(entry), `${tool}.${name}: ${entry}`);
				}
			}
		}
		if (field.enum) assert.ok(field.enum.includes(value), `${tool}.${name}: ${value}`);
	}
}

const CASES = [
	{
		name: 'counterparty check, company only',
		params: { resource: 'company', operation: 'checkCounterparty', query: ' Novo Nordisk ' },
		tool: 'counterparty-check',
		body: { query: 'Novo Nordisk' },
	},
	{
		name: 'counterparty check, all fields',
		params: {
			resource: 'company',
			operation: 'checkCounterparty',
			query: '24256790',
			additionalFields: {
				country: 'DK',
				vatNumber: 'DK24256790',
				iban: 'DK5000400440116243',
				walletAddresses: '0x7FF9cFad3877F21d41Da833E2F775dB0569eE3D9, bc1qexample',
			},
		},
		tool: 'counterparty-check',
		body: {
			query: '24256790',
			country: 'DK',
			vatNumber: 'DK24256790',
			iban: 'DK5000400440116243',
			walletAddresses: ['0x7FF9cFad3877F21d41Da833E2F775dB0569eE3D9', 'bc1qexample'],
		},
	},
	{
		name: 'company report, defaults',
		params: { resource: 'company', operation: 'getReport', query: 'Tesco PLC' },
		tool: 'company-check',
		body: { query: 'Tesco PLC' },
	},
	{
		name: 'company report, sections and years',
		params: {
			resource: 'company',
			operation: 'getReport',
			query: '00445790',
			additionalFields: {
				country: 'GB',
				maxYears: 5,
				include: ['identity', 'charges', 'insolvency'],
			},
		},
		tool: 'company-check',
		body: {
			query: '00445790',
			country: 'GB',
			maxYears: 5,
			include: ['identity', 'charges', 'insolvency'],
		},
	},
	{
		name: 'company accounts, one register',
		params: {
			resource: 'company',
			operation: 'getAccounts',
			companyNumbers: '',
			cvrNumbers: '24256790',
			orgNumbers: '',
			maxResults: 1,
		},
		tool: 'company-accounts',
		body: { cvrNumbers: ['24256790'], maxResults: 1 },
	},
	{
		name: 'company accounts, three registers and no LEI',
		params: {
			resource: 'company',
			operation: 'getAccounts',
			companyNumbers: '03117531, SC123456',
			cvrNumbers: ['24256790'],
			orgNumbers: '923609016',
			maxResults: 5,
			additionalFields: { enrichLei: false },
		},
		tool: 'company-accounts',
		body: {
			companyNumbers: ['03117531', 'SC123456'],
			cvrNumbers: ['24256790'],
			orgNumbers: ['923609016'],
			maxResults: 5,
			enrichLei: false,
		},
	},
	{
		name: 'new UK companies, defaults (yesterday, all sectors)',
		params: {
			resource: 'company',
			operation: 'getNewUk',
			sicCodes: '',
			incorporatedFrom: '',
			incorporatedTo: '',
			maxResults: 100,
		},
		tool: 'uk-new-companies',
		body: { maxResults: 100 },
	},
	{
		name: 'new UK companies, SIC codes, date-times and filters',
		params: {
			resource: 'company',
			operation: 'getNewUk',
			sicCodes: '62, 6201',
			incorporatedFrom: '2026-11-03T09:15:00.000+01:00',
			incorporatedTo: '2026-11-09',
			maxResults: 200,
			additionalFields: { location: 'Manchester', companyTypes: ['ltd'] },
		},
		tool: 'uk-new-companies',
		body: {
			sicCodes: ['62', '6201'],
			incorporatedFrom: '2026-11-03',
			incorporatedTo: '2026-11-09',
			maxResults: 200,
			location: 'Manchester',
			companyTypes: ['ltd'],
		},
	},
	{
		name: 'new UK companies, every company type',
		params: {
			resource: 'company',
			operation: 'getNewUk',
			sicCodes: '68',
			maxResults: 50,
			additionalFields: { companyTypes: [] },
		},
		tool: 'uk-new-companies',
		body: { sicCodes: ['68'], maxResults: 50, companyTypes: [] },
	},
	{
		name: 'sanctions screening, names one per line (a comma stays in the name)',
		params: {
			resource: 'sanctions',
			operation: 'screen',
			names: 'Sovcomflot\nAcme Trading, Inc.\n\n',
		},
		tool: 'sanctions-screening',
		body: { names: ['Sovcomflot', 'Acme Trading, Inc.'] },
	},
	{
		name: 'sanctions screening, all fields',
		params: {
			resource: 'sanctions',
			operation: 'screen',
			names: ['Sovcomflot'],
			additionalFields: {
				addresses: '0x7FF9cFad3877F21d41Da833E2F775dB0569eE3D9',
				country: 'RU',
				entityType: 'organization',
				minScore: 90,
				lists: ['ofac_sdn', 'uk'],
			},
		},
		tool: 'sanctions-screening',
		body: {
			names: ['Sovcomflot'],
			addresses: ['0x7FF9cFad3877F21d41Da833E2F775dB0569eE3D9'],
			country: 'RU',
			entityType: 'organization',
			minScore: 90,
			lists: ['ofac_sdn', 'uk'],
		},
	},
	{
		name: 'VAT and IBAN check',
		params: {
			resource: 'vatIban',
			operation: 'check',
			vatNumbers: 'IE6388047V',
			ibans: 'NL91ABNA0417164300, DE89 3704 0044 0532 0130 00',
			additionalFields: {
				expectedName: 'Google Ireland Ltd',
				expectedCountry: 'IE',
				requesterVatNumber: 'NL123456789B01',
			},
		},
		tool: 'vat-iban-check',
		body: {
			vatNumbers: ['IE6388047V'],
			ibans: ['NL91ABNA0417164300', 'DE89 3704 0044 0532 0130 00'],
			expectedName: 'Google Ireland Ltd',
			expectedCountry: 'IE',
			requesterVatNumber: 'NL123456789B01',
		},
	},
	{
		name: 'VAT check from a JSON array in text (as an AI agent may send it)',
		params: {
			resource: 'vatIban',
			operation: 'check',
			vatNumbers: '["IE6388047V","NL004495445B01"]',
			ibans: '',
		},
		tool: 'vat-iban-check',
		body: { vatNumbers: ['IE6388047V', 'NL004495445B01'] },
	},
];

for (const c of CASES) {
	test(`request: ${c.name}`, async () => {
		const { calls, error } = await run({ params: c.params });
		assert.equal(error, undefined);
		assert.equal(calls.length, 1);
		const { credential, options } = calls[0];
		assert.equal(credential, 'boscoLabsApi', 'paid tools go through the credential');
		assert.equal(options.method, 'POST');
		assert.equal(options.url, `https://api.boscolabs.dev/v1/${c.tool}`);
		assert.equal(options.json, true);
		assert.equal(options.headers['User-Agent'], `n8n-nodes-boscolabs/${pkg.version}`);
		assert.equal(
			options.headers.Authorization,
			undefined,
			'the key comes from the credential only',
		);
		assert.deepEqual(options.body, c.body);
		assertMatchesContract(c.tool, options.body);
	});
}

test('request: the planner is called without credentials', async () => {
	const { calls, output, error } = await run({
		params: { resource: 'question', operation: 'plan', question: ' Is Rosneft sanctioned? ' },
		respond: () => ({
			statusCode: 200,
			headers: {},
			body: { plan_id: 'p1.x', steps: [{ tool: 'sanctions-screening' }], total_max_usd: 0.01 },
		}),
	});
	assert.equal(error, undefined);
	assert.equal(calls.length, 1);
	assert.equal(calls[0].credential, null, 'plain httpRequest, no credential');
	assert.equal(calls[0].options.url, 'https://api.boscolabs.dev/v1/plan');
	assert.equal(calls[0].options.method, 'POST');
	assert.deepEqual(calls[0].options.body, { question: 'Is Rosneft sanctioned?' });
	assert.equal(calls[0].options.headers['User-Agent'], USER_AGENT);
	assert.deepEqual(output, [
		{
			json: { plan_id: 'p1.x', steps: [{ tool: 'sanctions-screening' }], total_max_usd: 0.01 },
			pairedItem: { item: 0 },
		},
	]);
});

test('request: one call per input item', async () => {
	const { calls } = await run({
		items: [{ json: {} }, { json: {} }],
		params: [
			{ resource: 'company', operation: 'checkCounterparty', query: 'A Ltd' },
			{ resource: 'company', operation: 'checkCounterparty', query: 'B Ltd' },
		],
	});
	assert.deepEqual(
		calls.map((c) => c.options.body.query),
		['A Ltd', 'B Ltd'],
	);
});

test('version: the User-Agent constant is in step with package.json', () => {
	assert.equal(VERSION, pkg.version);
	assert.equal(USER_AGENT, `n8n-nodes-boscolabs/${pkg.version}`);
});

// ---- the node description against the contract --------------------------------------------

const description = new BoscoLabs().description;
const TOOL_OF = {
	'company:checkCounterparty': 'counterparty-check',
	'company:getReport': 'company-check',
	'company:getAccounts': 'company-accounts',
	'company:getNewUk': 'uk-new-companies',
	'sanctions:screen': 'sanctions-screening',
	'vatIban:check': 'vat-iban-check',
};
const NOT_API_FIELDS = new Set(['additionalFields', 'pricingNotice', 'accountsNotice']);

function shownFor(property, resource, operation) {
	const shown = property.displayOptions?.show ?? {};
	return (
		(!shown.resource || shown.resource.includes(resource)) &&
		(!shown.operation || shown.operation.includes(operation))
	);
}

function fieldsOf(resource, operation) {
	const fields = [];
	for (const property of description.properties) {
		if (['resource', 'operation', 'simplify', 'options'].includes(property.name)) continue;
		if (!shownFor(property, resource, operation)) continue;
		if (property.name === 'additionalFields') fields.push(...property.options);
		else if (!NOT_API_FIELDS.has(property.name)) fields.push(property);
	}
	return fields;
}

for (const [key, tool] of Object.entries(TOOL_OF)) {
	const [resource, operation] = key.split(':');

	test(`description: ${key} uses the API's field names, defaults and limits`, () => {
		const schema = contract[tool];
		const fields = fieldsOf(resource, operation);
		assert.ok(fields.length > 0);
		for (const field of fields) {
			const api = schema.properties[field.name];
			assert.ok(api, `${tool} has no input field '${field.name}'`);
			if (api.type === 'integer') {
				assert.equal(field.type, 'number');
				assert.equal(field.default, api.default, `${field.name} default`);
				assert.equal(field.typeOptions.minValue, api.minimum, `${field.name} min`);
				assert.equal(field.typeOptions.maxValue, api.maximum, `${field.name} max`);
			}
			if (api.type === 'boolean') assert.equal(field.default, api.default, `${field.name} default`);
			if (api.enum) {
				assert.deepEqual(field.options.map((o) => o.value).sort(), [...api.enum].sort());
				assert.equal(field.default, api.default, `${field.name} default`);
			}
			if (field.type === 'multiOptions') {
				const allowed = api.itemEnum ?? api.itemSuggested;
				assert.deepEqual(field.options.map((o) => o.value).sort(), [...allowed].sort());
				// no default on the API means "all" (sanctions lists): the node leaves it empty too
				assert.deepEqual(field.default, api.default ?? [], `${field.name} default`);
			}
			if (api.type === 'array' && api.maxItems !== undefined && field.type === 'string') {
				assert.match(field.description, new RegExp(`at most ${api.maxItems}\\b`), field.name);
			}
		}
		for (const name of schema.required) {
			const field = fields.find((f) => f.name === name);
			assert.ok(field?.required, `${tool}.${name} is required on the API`);
		}
	});

	test(`description: ${key} states the API's price`, () => {
		const operations = description.properties.find(
			(p) => p.name === 'operation' && p.displayOptions.show.resource.includes(resource),
		);
		const option = operations.options.find((o) => o.value === operation);
		assert.ok(option, `operation ${operation}`);
		assert.match(option.description, new RegExp(`\\$${contract[tool].price_usd_per_row}\\b`));
		assert.ok(option.action, 'an action label for the nodes panel');
	});
}

test('description: credentials are required for paid resources and hidden for the planner', () => {
	assert.equal(description.usableAsTool, true);
	assert.equal(description.credentials.length, 1);
	const [credential] = description.credentials;
	assert.equal(credential.name, 'boscoLabsApi');
	assert.equal(credential.required, true);
	assert.deepEqual([...credential.displayOptions.show.resource].sort(), [
		'company',
		'sanctions',
		'vatIban',
	]);
});

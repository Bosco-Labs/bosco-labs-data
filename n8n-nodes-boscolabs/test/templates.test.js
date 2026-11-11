'use strict';

// The workflow templates must import cleanly: valid JSON, only this node and core n8n nodes,
// every Bosco Labs node set to an operation and to fields that exist, every connection resolved.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const { BoscoLabs } = require('../dist/nodes/BoscoLabs/BoscoLabs.node.js');
const { run } = require('./helpers.js');

const DIR = path.join(__dirname, '..', 'templates');
const BOSCO = 'n8n-nodes-boscolabs.boscoLabs';
const CORE = new Set([
	'n8n-nodes-base.manualTrigger',
	'n8n-nodes-base.scheduleTrigger',
	'n8n-nodes-base.if',
	'n8n-nodes-base.set',
	'n8n-nodes-base.stickyNote',
]);
const EXPECTED = [
	'screen-new-supplier.json',
	'validate-vat-and-company-before-invoicing.json',
	'weekly-new-uk-companies-by-sic-code.json',
];

const description = new BoscoLabs().description;

function shown(property, parameters) {
	const rules = property.displayOptions?.show ?? {};
	return Object.entries(rules).every(([name, values]) => values.includes(parameters[name]));
}

test('templates: the three workflows are there, each listed in templates/README.md', () => {
	const files = fs.readdirSync(DIR).filter((f) => f.endsWith('.json')).sort();
	assert.deepEqual(files, EXPECTED);
	const readme = fs.readFileSync(path.join(DIR, 'README.md'), 'utf8');
	for (const file of files) {
		assert.ok(readme.includes(file), `${file} is described in templates/README.md`);
		const workflow = JSON.parse(fs.readFileSync(path.join(DIR, file), 'utf8'));
		assert.ok(readme.includes(workflow.name), `the title of ${file} is in templates/README.md`);
	}
});

for (const file of EXPECTED) {
	const workflow = JSON.parse(fs.readFileSync(path.join(DIR, file), 'utf8'));

	test(`templates: ${file} uses this node and core nodes only, with a setup note`, () => {
		assert.ok(workflow.name.length > 10);
		const names = workflow.nodes.map((n) => n.name);
		assert.equal(new Set(names).size, names.length, 'node names are unique');
		assert.equal(new Set(workflow.nodes.map((n) => n.id)).size, names.length, 'node ids are unique');
		for (const node of workflow.nodes) {
			assert.ok(node.type === BOSCO || CORE.has(node.type), `unexpected node type ${node.type}`);
			assert.equal(node.credentials, undefined, 'no credential ids in a template');
		}
		assert.ok(workflow.nodes.some((n) => n.type === BOSCO));
		const note = workflow.nodes.find((n) => n.type === 'n8n-nodes-base.stickyNote');
		assert.match(note.parameters.content, /### Setup/);
		assert.match(note.parameters.content, /boscolabs\.dev\/api\.html/);
		assert.doesNotMatch(JSON.stringify(workflow), /bl_live_/, 'no API key in a template');
	});

	test(`templates: ${file} connections point at existing nodes`, () => {
		const names = new Set(workflow.nodes.map((n) => n.name));
		const connected = new Set();
		for (const [from, outputs] of Object.entries(workflow.connections)) {
			assert.ok(names.has(from), `connection from unknown node ${from}`);
			connected.add(from);
			for (const branch of outputs.main) {
				for (const target of branch) {
					assert.ok(names.has(target.node), `connection to unknown node ${target.node}`);
					connected.add(target.node);
				}
			}
		}
		for (const node of workflow.nodes) {
			if (node.type !== 'n8n-nodes-base.stickyNote') {
				assert.ok(connected.has(node.name), `${node.name} is not connected`);
			}
		}
		// expressions that name another node must name one that exists
		for (const match of JSON.stringify(workflow).matchAll(/\$\('([^']+)'\)/g)) {
			assert.ok(names.has(match[1]), `expression refers to unknown node ${match[1]}`);
		}
	});

	test(`templates: ${file} Bosco Labs nodes use parameters the node has`, async () => {
		for (const node of workflow.nodes.filter((n) => n.type === BOSCO)) {
			const p = node.parameters;
			assert.equal(node.typeVersion, description.version);
			const operations = description.properties.filter((x) => x.name === 'operation' && shown(x, p));
			assert.equal(operations.length, 1, `${node.name}: resource ${p.resource}`);
			assert.ok(operations[0].options.some((o) => o.value === p.operation), `${node.name}: operation`);
			const visible = description.properties.filter((x) => shown(x, p));
			for (const [name, value] of Object.entries(p)) {
				const property = visible.find((x) => x.name === name);
				assert.ok(property, `${node.name}: the node has no field '${name}' for this operation`);
				if (property.type === 'collection') {
					for (const key of Object.keys(value)) {
						assert.ok(property.options.some((o) => o.name === key), `${node.name}: ${name}.${key}`);
					}
				}
			}
			// with the expressions replaced by sample values, the node builds a request for it
			const resolved = JSON.parse(
				JSON.stringify(p, (key, value) => {
					if (typeof value !== 'string' || !value.startsWith('=')) return value;
					return /incorporated/i.test(key) ? '2026-11-03' : 'DK24256790';
				}),
			);
			const { calls, error } = await run({ params: resolved });
			assert.equal(error, undefined, `${node.name}: ${error?.message}`);
			assert.equal(calls.length, 1);
		}
	});
}

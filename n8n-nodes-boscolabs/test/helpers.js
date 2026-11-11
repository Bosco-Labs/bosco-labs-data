'use strict';

// Offline test helpers: a stand-in for n8n's execute context with mocked HTTP helpers.
// Nothing here calls the live API.

const { BoscoLabs } = require('../dist/nodes/BoscoLabs/BoscoLabs.node.js');

const ok = (body) => ({ statusCode: 200, headers: {}, body });

/**
 * Runs the node once.
 * `params`: the node parameters, one object for every item or an array with one object per item.
 * `respond`: (options, callIndex) => full HTTP response; default: an empty, free answer.
 */
async function run({ params, items = [{ json: {} }], respond, continueOnFail = false }) {
	const calls = [];
	const hints = [];
	const answer = async (credential, options) => {
		calls.push({ credential, options });
		const response = respond
			? await respond(options, calls.length - 1)
			: ok({ tool: 'x', rows: [], count: 0, warnings: [], message: '', charged_usd: 0 });
		return response;
	};
	const context = {
		getInputData: () => items,
		getNode: () => ({
			id: '1',
			name: 'Bosco Labs',
			type: 'n8n-nodes-boscolabs.boscoLabs',
			typeVersion: 1,
			position: [0, 0],
			parameters: {},
		}),
		getNodeParameter: (name, itemIndex, fallback) => {
			const own = Array.isArray(params) ? params[itemIndex] : params;
			return name in own ? own[name] : fallback;
		},
		continueOnFail: () => continueOnFail,
		addExecutionHints: (...added) => hints.push(...added),
		helpers: {
			httpRequest: async (options) => answer(null, options),
			httpRequestWithAuthentication: async function (credential, options) {
				return answer(credential, options);
			},
		},
	};
	let output;
	let error;
	try {
		[output] = await new BoscoLabs().execute.call(context);
	} catch (thrown) {
		error = thrown;
	}
	return { output, error, calls, hints };
}

module.exports = { run, ok };

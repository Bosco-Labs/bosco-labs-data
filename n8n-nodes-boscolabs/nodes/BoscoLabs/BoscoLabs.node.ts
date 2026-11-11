import type {
	IDataObject,
	IExecuteFunctions,
	IHttpRequestOptions,
	IN8nHttpFullResponse,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
	JsonObject,
	NodeExecutionHint,
} from 'n8n-workflow';
import { NodeApiError, NodeConnectionTypes, NodeOperationError } from 'n8n-workflow';

import { fieldProperties, operationProperties, resourceProperty } from './descriptions';
import {
	API_BASE_URL,
	BoscoInputError,
	buildRequest,
	describeFailure,
	simplifyRow,
	USER_AGENT,
} from './request';

const CREDENTIAL = 'boscoLabsApi';
/** The API answers within 55 seconds or says that it timed out; this leaves room for the network. */
const TIMEOUT_MS = 70_000;
const MAX_HINTS = 5;

export class BoscoLabs implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'Bosco Labs',
		name: 'boscoLabs',
		icon: { light: 'file:../../icons/boscolabs.svg', dark: 'file:../../icons/boscolabs.dark.svg' },
		group: ['transform'],
		version: 1,
		subtitle: '={{$parameter["operation"] + ": " + $parameter["resource"]}}',
		description:
			'Check companies against official registers, sanctions lists and VIES, with a source link per result',
		defaults: {
			name: 'Bosco Labs',
		},
		usableAsTool: true,
		inputs: [NodeConnectionTypes.Main],
		outputs: [NodeConnectionTypes.Main],
		credentials: [
			{
				name: CREDENTIAL,
				required: true,
				displayOptions: {
					show: {
						resource: ['company', 'sanctions', 'vatIban'],
					},
				},
			},
		],
		properties: [resourceProperty, ...operationProperties, ...fieldProperties],
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const returnData: INodeExecutionData[] = [];
		const hints: NodeExecutionHint[] = [];

		for (let itemIndex = 0; itemIndex < items.length; itemIndex++) {
			try {
				const resource = this.getNodeParameter('resource', itemIndex) as string;
				const operation = this.getNodeParameter('operation', itemIndex) as string;

				let request;
				try {
					request = buildRequest(resource, operation, (name, fallback) =>
						this.getNodeParameter(name, itemIndex, fallback),
					);
				} catch (error) {
					throw new NodeOperationError(this.getNode(), error as Error, {
						itemIndex,
						description: error instanceof BoscoInputError ? error.description : undefined,
					});
				}

				const options: IHttpRequestOptions = {
					method: 'POST',
					url: `${API_BASE_URL}/v1/${request.tool}`,
					headers: { Accept: 'application/json', 'User-Agent': USER_AGENT },
					body: request.body,
					json: true,
					returnFullResponse: true,
					ignoreHttpStatusErrors: true,
					timeout: TIMEOUT_MS,
				};

				let response: IN8nHttpFullResponse;
				try {
					response = (
						request.authenticated
							? await this.helpers.httpRequestWithAuthentication.call(this, CREDENTIAL, options)
							: await this.helpers.httpRequest(options)
					) as IN8nHttpFullResponse;
				} catch (error) {
					throw new NodeApiError(this.getNode(), error as JsonObject, { itemIndex });
				}

				if (response.statusCode >= 400) {
					const failure = describeFailure(response.statusCode, response.body);
					throw new NodeApiError(this.getNode(), { code: failure.code } as JsonObject, {
						message: failure.message,
						description: failure.description,
						httpCode: String(response.statusCode),
						itemIndex,
					});
				}

				const body = response.body as IDataObject;
				const rows = body?.rows;

				if (!request.authenticated || !Array.isArray(rows)) {
					// the planner answers with one plan, not with rows
					returnData.push({ json: body, pairedItem: { item: itemIndex } });
					continue;
				}

				const output = this.getNodeParameter('options', itemIndex, {}) as IDataObject;
				if (output.returnFullResponse === true) {
					returnData.push({ json: body, pairedItem: { item: itemIndex } });
					continue;
				}

				const simplify = this.getNodeParameter('simplify', itemIndex, true) as boolean;
				for (const row of rows as IDataObject[]) {
					returnData.push({
						json: simplify ? simplifyRow(request.tool, row) : row,
						pairedItem: { item: itemIndex },
					});
				}

				// rows carry no envelope: pass on what the API said about an empty or partial answer
				const warnings = Array.isArray(body.warnings) ? (body.warnings as unknown[]) : [];
				for (const warning of warnings) {
					hints.push({ message: String(warning), type: 'warning', location: 'outputPane' });
				}
				if (rows.length === 0 && typeof body.message === 'string' && body.message !== '') {
					hints.push({ message: body.message, type: 'info', location: 'outputPane' });
				}
			} catch (error) {
				if (this.continueOnFail()) {
					returnData.push({
						json: { error: (error as Error).message },
						pairedItem: { item: itemIndex },
					});
					continue;
				}
				if (error instanceof NodeApiError) {
					// re-wrapping hands back the same error, with its HTTP status and description
					throw new NodeApiError(this.getNode(), error as unknown as JsonObject, { itemIndex });
				}
				throw new NodeOperationError(this.getNode(), error as Error, { itemIndex });
			}
		}

		if (hints.length > 0 && typeof this.addExecutionHints === 'function') {
			this.addExecutionHints(...hints.slice(0, MAX_HINTS));
		}

		return [returnData];
	}
}

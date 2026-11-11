import type { IDataObject } from 'n8n-workflow';
import { jsonParse } from 'n8n-workflow';

export const API_BASE_URL = 'https://api.boscolabs.dev';

/** Sent as User-Agent so the API can count calls per client; keep in step with package.json. */
export const VERSION = '0.1.0';
export const USER_AGENT = `n8n-nodes-boscolabs/${VERSION}`;

/** Reads one node parameter of the current item; `fallback` is returned when it is not set. */
export type ParameterReader = (name: string, fallback?: unknown) => unknown;

export interface BoscoRequest {
	/** Tool name on the API, used as the path: POST /v1/<tool>. */
	tool: string;
	body: IDataObject;
	/** False for the free planner, which runs without an API key. */
	authenticated: boolean;
}

/** Input the API would refuse; raised before any request is sent, so nothing is charged. */
export class BoscoInputError extends Error {
	constructor(
		message: string,
		readonly description: string,
	) {
		super(message);
		this.name = 'BoscoInputError';
	}
}

const COMMA_OR_LINE = /[,;\n]/;
const LINE = /\n/;

/** A list from an array, a JSON array in text, or text with separators. Empty entries are dropped. */
export function toList(value: unknown, separator: RegExp = COMMA_OR_LINE): string[] {
	if (value === undefined || value === null) return [];
	if (Array.isArray(value)) {
		return value.map((entry) => String(entry ?? '').trim()).filter((entry) => entry !== '');
	}
	const text = String(value).trim();
	if (text.startsWith('[')) {
		const parsed = jsonParse<unknown>(text, { fallbackValue: undefined });
		if (Array.isArray(parsed)) return toList(parsed);
	}
	return text
		.split(separator)
		.map((entry) => entry.trim())
		.filter((entry) => entry !== '');
}

function limited(label: string, values: string[], max: number): string[] {
	if (values.length > max) {
		throw new BoscoInputError(
			`'${label}' takes at most ${max} values per call, got ${values.length}`,
			`Split the list over several items (for example with a Loop Over Items node set to a batch size of ${max}). Nothing was charged.`,
		);
	}
	return values;
}

function text(value: unknown): string {
	return value === undefined || value === null ? '' : String(value).trim();
}

function integer(label: string, value: unknown, min: number, max: number): number {
	const parsed = typeof value === 'number' ? value : Number(text(value));
	if (!Number.isInteger(parsed) || parsed < min || parsed > max) {
		throw new BoscoInputError(
			`'${label}' must be a whole number from ${min} to ${max}, got '${text(value)}'`,
			'Change the value of this field. Nothing was charged.',
		);
	}
	return parsed;
}

/** YYYY-MM-DD from a date or an ISO date-time (n8n expressions such as $now give the latter). */
function isoDate(label: string, value: unknown): string {
	const raw = text(value);
	if (raw === '') return '';
	const match = /^(\d{4}-\d{2}-\d{2})(?:$|[T ])/.exec(raw);
	if (!match) {
		throw new BoscoInputError(
			`'${label}' must be a date as YYYY-MM-DD, got '${raw}'`,
			"Use a date such as 2026-11-04, or an expression such as {{ $now.minus({ days: 7 }).toFormat('yyyy-MM-dd') }}. Nothing was charged.",
		);
	}
	return match[1];
}

function required(label: string, value: unknown): string {
	const raw = text(value);
	if (raw === '') {
		throw new BoscoInputError(`'${label}' is empty`, 'Fill in this field. Nothing was charged.');
	}
	return raw;
}

function setText(body: IDataObject, key: string, value: unknown): void {
	const raw = text(value);
	if (raw !== '') body[key] = raw;
}

function collection(get: ParameterReader, name: string): IDataObject {
	const value = get(name, {});
	return value !== null && typeof value === 'object' && !Array.isArray(value)
		? (value as IDataObject)
		: {};
}

function counterpartyCheck(get: ParameterReader): IDataObject {
	const extra = collection(get, 'additionalFields');
	const body: IDataObject = { query: required('Company', get('query', '')) };
	setText(body, 'country', extra.country);
	setText(body, 'vatNumber', extra.vatNumber);
	setText(body, 'iban', extra.iban);
	const wallets = limited('Wallet Addresses', toList(extra.walletAddresses), 10);
	if (wallets.length > 0) body.walletAddresses = wallets;
	return body;
}

function companyReport(get: ParameterReader): IDataObject {
	const extra = collection(get, 'additionalFields');
	const body: IDataObject = { query: required('Company', get('query', '')) };
	setText(body, 'country', extra.country);
	if (extra.maxYears !== undefined) {
		body.maxYears = integer('Financial Years', extra.maxYears, 1, 10);
	}
	if (extra.include !== undefined) {
		const sections = toList(extra.include);
		// an empty list means the default sections on the API, so it is left out
		if (sections.length > 0) body.include = sections;
	}
	return body;
}

function companyAccounts(get: ParameterReader): IDataObject {
	const extra = collection(get, 'additionalFields');
	const lists: Array<[string, string[]]> = [
		['companyNumbers', toList(get('companyNumbers', ''))],
		['cvrNumbers', toList(get('cvrNumbers', ''))],
		['orgNumbers', toList(get('orgNumbers', ''))],
	];
	const total = lists.reduce((sum, [, values]) => sum + values.length, 0);
	if (total === 0) {
		throw new BoscoInputError(
			'No registration number given',
			"Fill in 'UK Company Numbers', 'Danish CVR Numbers' or 'Norwegian Organisation Numbers'. Nothing was charged.",
		);
	}
	if (total > 5) {
		throw new BoscoInputError(
			`At most 5 companies per call across the three number fields, got ${total}`,
			'Split the numbers over several items. Nothing was charged.',
		);
	}
	const body: IDataObject = {};
	for (const [key, values] of lists) {
		if (values.length > 0) body[key] = values;
	}
	body.maxResults = integer('Max Company-Years per Country', get('maxResults', 5), 1, 10);
	if (typeof extra.enrichLei === 'boolean') body.enrichLei = extra.enrichLei;
	return body;
}

function newUkCompanies(get: ParameterReader): IDataObject {
	const extra = collection(get, 'additionalFields');
	const body: IDataObject = {};
	const sicCodes = toList(get('sicCodes', ''));
	if (sicCodes.length > 0) body.sicCodes = sicCodes;
	setText(body, 'incorporatedFrom', isoDate('Incorporated From', get('incorporatedFrom', '')));
	setText(body, 'incorporatedTo', isoDate('Incorporated To', get('incorporatedTo', '')));
	body.maxResults = integer('Max Results', get('maxResults', 100), 1, 200);
	setText(body, 'location', extra.location);
	// an empty list is meaningful here: it asks for every company type
	if (extra.companyTypes !== undefined) body.companyTypes = toList(extra.companyTypes);
	return body;
}

function sanctionsScreening(get: ParameterReader): IDataObject {
	const extra = collection(get, 'additionalFields');
	const names = limited('Names', toList(get('names', ''), LINE), 50);
	const addresses = limited('Wallet Addresses', toList(extra.addresses), 50);
	if (names.length === 0 && addresses.length === 0) {
		throw new BoscoInputError(
			'Nothing to screen',
			"Fill in 'Names', or add 'Wallet Addresses' under Additional Fields. Nothing was charged.",
		);
	}
	const body: IDataObject = {};
	if (names.length > 0) body.names = names;
	if (addresses.length > 0) body.addresses = addresses;
	setText(body, 'country', extra.country);
	setText(body, 'entityType', extra.entityType);
	if (extra.minScore !== undefined) {
		body.minScore = integer('Minimum Match Score', extra.minScore, 50, 100);
	}
	const lists = toList(extra.lists);
	if (lists.length > 0) body.lists = lists;
	return body;
}

function vatIbanCheck(get: ParameterReader): IDataObject {
	const extra = collection(get, 'additionalFields');
	const vatNumbers = limited('VAT Numbers', toList(get('vatNumbers', '')), 10);
	const ibans = limited('IBANs', toList(get('ibans', '')), 50);
	if (vatNumbers.length === 0 && ibans.length === 0) {
		throw new BoscoInputError(
			'Nothing to check',
			"Fill in 'VAT Numbers', 'IBANs' or both. Nothing was charged.",
		);
	}
	const body: IDataObject = {};
	if (vatNumbers.length > 0) body.vatNumbers = vatNumbers;
	if (ibans.length > 0) body.ibans = ibans;
	setText(body, 'expectedName', extra.expectedName);
	setText(body, 'expectedCountry', extra.expectedCountry);
	setText(body, 'requesterVatNumber', extra.requesterVatNumber);
	return body;
}

function planQuestion(get: ParameterReader): IDataObject {
	const question = required('Question', get('question', ''));
	if (question.length > 1000) {
		throw new BoscoInputError(
			`'Question' takes at most 1000 characters, got ${question.length}`,
			'Shorten the question.',
		);
	}
	return { question };
}

const OPERATIONS: Record<
	string,
	{ tool: string; authenticated: boolean; body: (get: ParameterReader) => IDataObject }
> = {
	'company:checkCounterparty': {
		tool: 'counterparty-check',
		authenticated: true,
		body: counterpartyCheck,
	},
	'company:getReport': { tool: 'company-check', authenticated: true, body: companyReport },
	'company:getAccounts': { tool: 'company-accounts', authenticated: true, body: companyAccounts },
	'company:getNewUk': { tool: 'uk-new-companies', authenticated: true, body: newUkCompanies },
	'sanctions:screen': {
		tool: 'sanctions-screening',
		authenticated: true,
		body: sanctionsScreening,
	},
	'vatIban:check': { tool: 'vat-iban-check', authenticated: true, body: vatIbanCheck },
	'question:plan': { tool: 'plan', authenticated: false, body: planQuestion },
};

/** The API call for one item: which tool, with which JSON body, with or without the key. */
export function buildRequest(
	resource: string,
	operation: string,
	get: ParameterReader,
): BoscoRequest {
	const entry = OPERATIONS[`${resource}:${operation}`];
	if (!entry) {
		throw new BoscoInputError(
			`The operation '${operation}' is not available for the resource '${resource}'`,
			'Pick the resource and the operation again in the node.',
		);
	}
	return { tool: entry.tool, authenticated: entry.authenticated, body: entry.body(get) };
}

/** Fields kept per row when Simplify is on: at most 10, the source link included where rows have one. */
export const SIMPLE_FIELDS: Record<string, string[]> = {
	'counterparty-check': [
		'query',
		'status',
		'company',
		'checks',
		'summary',
		'candidates',
		'sanctions_hits',
		'message',
		'warnings',
		'source_url',
	],
	'company-check': [
		'query',
		'query_type',
		'country',
		'identity',
		'financials',
		'candidates',
		'not_found',
		'warnings',
		'sources',
		'retrieved_at',
	],
	'company-accounts': [
		'country',
		'company_number',
		'cvr',
		'org_number',
		'company_name',
		'period_end',
		'currency',
		'revenue',
		'net_income',
		'total_assets',
		'total_equity',
		'source_url',
	],
	'vat-iban-check': [
		'query',
		'check_type',
		'country_code',
		'status',
		'valid',
		'reason',
		'registered_name',
		'name_match',
		'country_match',
		'source_url',
	],
	'sanctions-screening': [
		'query',
		'match_found',
		'match_count',
		'best_score',
		'summary',
		'complete',
		'lists_not_checked',
		'matches',
		'warnings',
		'checked_at',
	],
	'uk-new-companies': [
		'company_number',
		'company_name',
		'company_type',
		'company_status',
		'incorporation_date',
		'sic_codes',
		'sic_descriptions',
		'registered_office_address',
		'postal_code',
		'source_url',
	],
};

/** A row of company-accounts carries the number of one register; the other two are null. */
const DROPPED_WHEN_NULL = new Set(['company_number', 'cvr', 'org_number']);

export function simplifyRow(tool: string, row: IDataObject): IDataObject {
	const fields = SIMPLE_FIELDS[tool];
	if (!fields) return row;
	const simple: IDataObject = {};
	for (const field of fields) {
		if (!(field in row)) continue;
		if (row[field] === null && DROPPED_WHEN_NULL.has(field)) continue;
		simple[field] = row[field];
	}
	return simple;
}

const HOW_TO_FIX: Record<string, string> = {
	invalid_input: 'Change the fields of this node as the message says.',
	bad_key:
		'Check the API key in the Bosco Labs API credential. You can get a key at https://boscolabs.dev/api.html#key.',
	insufficient_credits:
		'Add credits or raise the daily cap of your key at https://boscolabs.dev/api.html, then run the node again.',
	rate_limited:
		'Wait a few seconds and run the node again, or turn on Retry On Fail in the node settings.',
	source_failed:
		'An official source did not answer. Run the node again in a minute, or turn on Retry On Fail in the node settings.',
	timeout:
		'The sources took too long. Run the node again, or ask for less in one call (fewer numbers or names).',
	paused: 'The Bosco Labs API is paused. Try again later; see https://boscolabs.dev/status.html.',
};

export interface BoscoApiFailure {
	message: string;
	description: string;
	code: string;
}

/** What went wrong and how to get unstuck, from the API's `{"error": {"code", "message"}}` body. */
export function describeFailure(statusCode: number, body: unknown): BoscoApiFailure {
	const error =
		body !== null && typeof body === 'object' && !Array.isArray(body)
			? (body as IDataObject).error
			: undefined;
	const detail =
		error !== null && typeof error === 'object' && !Array.isArray(error)
			? (error as IDataObject)
			: {};
	const code = text(detail.code) || `http_${statusCode}`;
	const message =
		text(detail.message) || `The Bosco Labs API answered with HTTP status ${statusCode}`;
	const charged = /charged/i.test(message) ? '' : ' Nothing was charged for this call.';
	const fix =
		HOW_TO_FIX[code] ??
		'Run the node again; if it keeps happening, write to support@boscolabs.dev.';
	return { message, description: `${fix}${charged}`, code };
}

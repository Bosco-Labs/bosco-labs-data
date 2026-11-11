import type { INodeProperties } from 'n8n-workflow';

const PAID_RESOURCES = ['company', 'sanctions', 'vatIban'];

const show = (resource: string, operation: string) => ({
	show: { resource: [resource], operation: [operation] },
});

export const resourceProperty: INodeProperties = {
	displayName: 'Resource',
	name: 'resource',
	type: 'options',
	noDataExpression: true,
	options: [
		{
			name: 'Company',
			value: 'company',
			description: 'Checks, reports, accounts and new registrations from official registers',
		},
		{
			name: 'Question',
			value: 'question',
			description: 'The free planner: which calls answer a question, and what they cost',
		},
		{
			name: 'Sanctions List',
			value: 'sanctions',
			description: 'OFAC, UN, UK, EU and US export lists',
		},
		{
			name: 'VAT and IBAN',
			value: 'vatIban',
			description: 'EU VAT numbers (VIES) and IBANs',
		},
	],
	default: 'company',
};

export const operationProperties: INodeProperties[] = [
	{
		displayName: 'Operation',
		name: 'operation',
		type: 'options',
		noDataExpression: true,
		displayOptions: { show: { resource: ['company'] } },
		options: [
			{
				name: 'Check Counterparty',
				value: 'checkCounterparty',
				action: 'Check counterparty',
				description:
					'Run a KYB checklist on one company: register status, LEI, insolvency, recent accounts, sanctions, VAT and IBAN. Costs $0.05 per company checked.',
			},
			{
				name: 'Get Accounts',
				value: 'getAccounts',
				action: 'Get company accounts',
				description:
					'Retrieve filed annual accounts of UK, Danish and Norwegian companies by registration number. Costs $0.04 per company-year.',
			},
			{
				name: 'Get New UK Companies',
				value: 'getNewUk',
				action: 'Get new UK companies',
				description:
					'List companies incorporated in the UK on a day or in a date range, from Companies House. Costs $0.002 per company.',
			},
			{
				name: 'Get Report',
				value: 'getReport',
				action: 'Get company report',
				description:
					'Retrieve a due diligence report on one company: identity, LEI, officers and owners, financials and SEC filings. Costs $0.03 per report.',
			},
		],
		default: 'checkCounterparty',
	},
	{
		displayName: 'Operation',
		name: 'operation',
		type: 'options',
		noDataExpression: true,
		displayOptions: { show: { resource: ['question'] } },
		options: [
			{
				name: 'Plan',
				value: 'plan',
				action: 'Plan question',
				description:
					'Turn a question in plain words into the Bosco Labs calls that answer it, with their input and maximum price. Free, runs without credentials.',
			},
		],
		default: 'plan',
	},
	{
		displayName: 'Operation',
		name: 'operation',
		type: 'options',
		noDataExpression: true,
		displayOptions: { show: { resource: ['sanctions'] } },
		options: [
			{
				name: 'Screen',
				value: 'screen',
				action: 'Screen names against sanctions lists',
				description:
					'Check company, person or vessel names and crypto wallet addresses against the OFAC, UN, UK, EU and US export lists. Costs $0.01 per name or address.',
			},
		],
		default: 'screen',
	},
	{
		displayName: 'Operation',
		name: 'operation',
		type: 'options',
		noDataExpression: true,
		displayOptions: { show: { resource: ['vatIban'] } },
		options: [
			{
				name: 'Check',
				value: 'check',
				action: 'Check VAT number or IBAN',
				description:
					'Validate EU VAT numbers live in VIES and IBANs by structure and check digits. Costs $0.002 per number with a definite answer.',
			},
		],
		default: 'check',
	},
];

const pricingNotice: INodeProperties = {
	displayName:
		'Charged per result from the prepaid credits of your Bosco Labs API key. Calls that return nothing or do not succeed are free.',
	name: 'pricingNotice',
	type: 'notice',
	displayOptions: { show: { resource: PAID_RESOURCES } },
	default: '',
};

const counterpartyFields: INodeProperties[] = [
	{
		displayName: 'Company',
		name: 'query',
		type: 'string',
		required: true,
		displayOptions: show('company', 'checkCounterparty'),
		default: '',
		placeholder: 'e.g. Novo Nordisk',
		description:
			'A company name or an identifier: LEI, UK company number, Danish CVR, Norwegian organisation number, French SIREN or SIRET, Finnish Business ID, Estonian registry code, Irish CRO number, Czech IČO, Latvian registration number, US ticker or SEC CIK. A name that fits several companies returns the candidates and is not charged.',
	},
	{
		displayName: 'Additional Fields',
		name: 'additionalFields',
		type: 'collection',
		placeholder: 'Add Field',
		displayOptions: show('company', 'checkCounterparty'),
		default: {},
		options: [
			{
				displayName: 'Country',
				name: 'country',
				type: 'string',
				default: '',
				placeholder: 'e.g. DK',
				description:
					'ISO 3166 alpha-2 code. With a name it limits the search to that country; with a number it says which register the number belongs to.',
			},
			{
				displayName: 'IBAN',
				name: 'iban',
				type: 'string',
				default: '',
				placeholder: 'e.g. DK5000400440116243',
				description:
					'The bank account the company wants to be paid on. Checked for length, layout, check digits and country. No bank is contacted, so this does not prove who holds the account.',
			},
			{
				displayName: 'VAT Number',
				name: 'vatNumber',
				type: 'string',
				default: '',
				placeholder: 'e.g. DK24256790',
				description:
					'The EU VAT number the company gave you, with its country prefix. Checked live in VIES and compared with the name and country in the register.',
			},
			{
				displayName: 'Wallet Addresses',
				name: 'walletAddresses',
				type: 'string',
				default: '',
				placeholder: 'e.g. 0x7FF9cFad3877F21d41Da833E2F775dB0569eE3D9',
				description:
					'Crypto wallet addresses the company wants to be paid on, separated by commas (at most 10). Each is compared with the addresses OFAC lists.',
			},
		],
	},
];

const reportFields: INodeProperties[] = [
	{
		displayName: 'Company',
		name: 'query',
		type: 'string',
		required: true,
		displayOptions: show('company', 'getReport'),
		default: '',
		placeholder: 'e.g. Novo Nordisk',
		description:
			'A company name or an identifier: LEI, UK company number, Danish CVR, Norwegian organisation number, French SIREN or SIRET, Finnish Business ID, Estonian registry code, Irish CRO number, Czech IČO, Latvian registration number, US ticker, SEC CIK or FDIC certificate (FDIC:628). A name that fits several companies returns the candidates.',
	},
	{
		displayName: 'Additional Fields',
		name: 'additionalFields',
		type: 'collection',
		placeholder: 'Add Field',
		displayOptions: show('company', 'getReport'),
		default: {},
		options: [
			{
				displayName: 'Country',
				name: 'country',
				type: 'string',
				default: '',
				placeholder: 'e.g. DK',
				description:
					'ISO 3166 alpha-2 code. With a name it limits the search to that country; with a number it says which register the number belongs to.',
			},
			{
				displayName: 'Financial Years',
				name: 'maxYears',
				type: 'number',
				typeOptions: { minValue: 1, maxValue: 10 },
				default: 3,
				description:
					'How many fiscal years of key figures to return, newest first (1 to 10). The price is the same for any number of years.',
			},
			{
				displayName: 'Sections',
				name: 'include',
				type: 'multiOptions',
				options: [
					{
						name: 'Appointments',
						value: 'appointments',
						description: 'Other company appointments of each current UK officer',
					},
					{
						name: 'Charges',
						value: 'charges',
						description: 'UK registered mortgages and secured debt',
					},
					{
						name: 'Financials',
						value: 'financials',
						description: 'Key figures from filed accounts',
					},
					{
						name: 'Identity',
						value: 'identity',
						description: 'Register entry, LEI and addresses',
					},
					{
						name: 'Insolvency',
						value: 'insolvency',
						description: 'UK notices in The Gazette and Polish KRS entries',
					},
					{
						name: 'People',
						value: 'people',
						description: 'UK officers and owners; Polish board, proxies and shareholders',
					},
					{
						name: 'US Filings',
						value: 'us',
						description: 'SEC filings of companies listed in the US',
					},
				],
				default: ['identity', 'financials', 'us', 'people'],
				description:
					'Which sections of the report to fill. The price is the same for any number of sections.',
			},
		],
	},
];

const accountsFields: INodeProperties[] = [
	{
		displayName:
			'Give at least one registration number. At most 5 companies per call across the three fields.',
		name: 'accountsNotice',
		type: 'notice',
		displayOptions: show('company', 'getAccounts'),
		default: '',
	},
	{
		displayName: 'UK Company Numbers',
		name: 'companyNumbers',
		type: 'string',
		displayOptions: show('company', 'getAccounts'),
		default: '',
		placeholder: 'e.g. 03117531',
		description:
			'Companies House numbers, separated by commas (at most 5). Returns accounts filed digitally (iXBRL), newest first; accounts filed only on paper or as PDF are skipped.',
	},
	{
		displayName: 'Danish CVR Numbers',
		name: 'cvrNumbers',
		type: 'string',
		displayOptions: show('company', 'getAccounts'),
		default: '',
		placeholder: 'e.g. 24256790',
		description:
			'CVR numbers of 8 digits, separated by commas (at most 5). All years are available.',
	},
	{
		displayName: 'Norwegian Organisation Numbers',
		name: 'orgNumbers',
		type: 'string',
		displayOptions: show('company', 'getAccounts'),
		default: '',
		placeholder: 'e.g. 923609016',
		description:
			'Organisation numbers of 9 digits, separated by commas (at most 5). The last 3 fiscal years are available.',
	},
	{
		displayName: 'Max Company-Years per Country',
		name: 'maxResults',
		type: 'number',
		typeOptions: { minValue: 1, maxValue: 10 },
		displayOptions: show('company', 'getAccounts'),
		default: 5,
		description:
			'The most company-years to return per country, newest first (1 to 10). Use 1 for only the latest accounts. Each company-year returned is charged.',
	},
	{
		displayName: 'Additional Fields',
		name: 'additionalFields',
		type: 'collection',
		placeholder: 'Add Field',
		displayOptions: show('company', 'getAccounts'),
		default: {},
		options: [
			{
				displayName: 'Add LEI',
				name: 'enrichLei',
				type: 'boolean',
				default: true,
				description:
					'Whether to look up the Legal Entity Identifier of each company at GLEIF and add it to the result',
			},
		],
	},
];

const newUkFields: INodeProperties[] = [
	{
		displayName: 'SIC Codes',
		name: 'sicCodes',
		type: 'string',
		displayOptions: show('company', 'getNewUk'),
		default: '',
		placeholder: 'e.g. 62',
		description:
			'UK SIC 2007 code prefixes, separated by commas. A prefix matches every code below it: 62 is IT and software, 6201 is software development, 68 is real estate. Leave empty for all sectors.',
	},
	{
		displayName: 'Incorporated From',
		name: 'incorporatedFrom',
		type: 'string',
		displayOptions: show('company', 'getNewUk'),
		default: '',
		placeholder: 'e.g. 2026-11-01',
		description:
			'The earliest incorporation date, as YYYY-MM-DD. Leave empty to use the same day as Incorporated To; with both empty the day is yesterday (UTC).',
	},
	{
		displayName: 'Incorporated To',
		name: 'incorporatedTo',
		type: 'string',
		displayOptions: show('company', 'getNewUk'),
		default: '',
		placeholder: 'e.g. 2026-11-04',
		description:
			'The latest incorporation date (inclusive), as YYYY-MM-DD. Leave empty for yesterday (UTC).',
	},
	{
		displayName: 'Max Results',
		name: 'maxResults',
		type: 'number',
		typeOptions: { minValue: 1, maxValue: 200 },
		displayOptions: show('company', 'getNewUk'),
		default: 100,
		description:
			'The most companies to return (1 to 200). Each company returned is charged. When the result reaches this number, more may exist: narrow the dates or the SIC codes.',
	},
	{
		displayName: 'Additional Fields',
		name: 'additionalFields',
		type: 'collection',
		placeholder: 'Add Field',
		displayOptions: show('company', 'getNewUk'),
		default: {},
		options: [
			{
				displayName: 'Company Types',
				name: 'companyTypes',
				type: 'multiOptions',
				options: [
					{ name: 'Assurance Company', value: 'assurance-company' },
					{
						name: 'Charitable Incorporated Organisation (CIO)',
						value: 'charitable-incorporated-organisation',
					},
					{ name: 'Converted or Closed', value: 'converted-or-closed' },
					{ name: 'European Economic Interest Grouping (EEIG)', value: 'eeig' },
					{
						name: 'European Public Limited Company (SE)',
						value: 'european-public-limited-liability-company-se',
					},
					{
						name: 'Further Education or Sixth Form College',
						value: 'further-education-or-sixth-form-college-corporation',
					},
					{ name: 'ICVC (Securities)', value: 'icvc-securities' },
					{ name: 'ICVC (Umbrella)', value: 'icvc-umbrella' },
					{ name: 'ICVC (Warrant)', value: 'icvc-warrant' },
					{
						name: 'Industrial and Provident Society',
						value: 'industrial-and-provident-society',
					},
					{
						name: 'Investment Company with Variable Capital',
						value: 'investment-company-with-variable-capital',
					},
					{
						name: 'Limited by Guarantee',
						value: 'private-limited-guarant-nsc',
					},
					{
						name: 'Limited by Guarantee, Exempt From Using Limited',
						value: 'private-limited-guarant-nsc-limited-exemption',
					},
					{
						name: 'Limited by Shares, Section 30 Exemption',
						value: 'private-limited-shares-section-30-exemption',
					},
					{ name: 'Limited Liability Partnership (LLP)', value: 'llp' },
					{ name: 'Limited Partnership', value: 'limited-partnership' },
					{ name: 'Northern Ireland Company', value: 'northern-ireland' },
					{ name: 'Northern Ireland, Other', value: 'northern-ireland-other' },
					{ name: 'Old Public Company', value: 'old-public-company' },
					{ name: 'Other', value: 'other' },
					{ name: 'Overseas Company', value: 'oversea-company' },
					{ name: 'Private Limited Company (Ltd)', value: 'ltd' },
					{ name: 'Private Unlimited Company', value: 'private-unlimited' },
					{
						name: 'Private Unlimited Company Without Share Capital',
						value: 'private-unlimited-nsc',
					},
					{ name: 'Protected Cell Company', value: 'protected-cell-company' },
					{ name: 'Public Limited Company (PLC)', value: 'plc' },
					{ name: 'Registered Overseas Entity', value: 'registered-overseas-entity' },
					{ name: 'Registered Society', value: 'registered-society-non-jurisdictional' },
					{ name: 'Royal Charter Company', value: 'royal-charter' },
					{
						name: 'Scottish Charitable Incorporated Organisation',
						value: 'scottish-charitable-incorporated-organisation',
					},
					{ name: 'Scottish Qualifying Partnership', value: 'scottish-partnership' },
					{ name: 'UK Establishment of an Overseas Company', value: 'uk-establishment' },
					{ name: 'Unregistered Company', value: 'unregistered-company' },
				],
				default: ['ltd', 'plc', 'llp'],
				description:
					'Companies House company types to return. Remove every type to return all types.',
			},
			{
				displayName: 'Location',
				name: 'location',
				type: 'string',
				default: '',
				placeholder: 'e.g. Manchester',
				description:
					'Registered office location as free text: a town, county or postcode area. Leave empty for all of the UK.',
			},
		],
	},
];

const sanctionsFields: INodeProperties[] = [
	{
		displayName: 'Names',
		name: 'names',
		type: 'string',
		typeOptions: { rows: 3 },
		displayOptions: show('sanctions', 'screen'),
		default: '',
		placeholder: 'e.g. Sovcomflot',
		description:
			'Company, person or vessel names to screen, one per line (at most 50). A comma stays part of the name. Each name gives one result and one charge. Give names, wallet addresses or both.',
	},
	{
		displayName: 'Additional Fields',
		name: 'additionalFields',
		type: 'collection',
		placeholder: 'Add Field',
		displayOptions: show('sanctions', 'screen'),
		default: {},
		options: [
			{
				displayName: 'Country',
				name: 'country',
				type: 'string',
				default: '',
				placeholder: 'e.g. RU',
				description:
					'Country of the party you are screening, as an ISO 3166 alpha-2 code or English name. It never hides a match: listings that name other countries move to the end of the matches.',
			},
			{
				displayName: 'Entity Type',
				name: 'entityType',
				type: 'options',
				options: [
					{ name: 'Any', value: 'any' },
					{ name: 'Organization', value: 'organization' },
					{ name: 'Person', value: 'person' },
					{ name: 'Vessel', value: 'vessel' },
				],
				default: 'any',
				description:
					'Only return listings of this type. Listings whose type the list does not state are always kept.',
			},
			{
				displayName: 'Lists',
				name: 'lists',
				type: 'multiOptions',
				options: [
					{ name: 'EU Consolidated Financial Sanctions List', value: 'eu' },
					{ name: 'OFAC Consolidated (Non-SDN) List', value: 'ofac_consolidated' },
					{ name: 'OFAC SDN List', value: 'ofac_sdn' },
					{ name: 'UK Sanctions List', value: 'uk' },
					{ name: 'UN Security Council Consolidated List', value: 'un' },
					{ name: 'US Consolidated Screening List (Commerce, State)', value: 'us_csl' },
				],
				default: [],
				description:
					'Which lists to check. Leave empty for all six. The price is the same for any number of lists.',
			},
			{
				displayName: 'Minimum Match Score',
				name: 'minScore',
				type: 'number',
				typeOptions: { minValue: 50, maxValue: 100 },
				default: 85,
				description:
					'The lowest similarity score that counts as a match (50 to 100). 100 is the same name after normalisation; lower values find more spelling variants and more false positives.',
			},
			{
				displayName: 'Wallet Addresses',
				name: 'addresses',
				type: 'string',
				default: '',
				placeholder: 'e.g. 0x7FF9cFad3877F21d41Da833E2F775dB0569eE3D9',
				description:
					'Crypto wallet addresses to check, separated by commas (at most 50). Each is compared with the addresses the lists publish and charged like a name.',
			},
		],
	},
];

const vatIbanFields: INodeProperties[] = [
	{
		displayName: 'VAT Numbers',
		name: 'vatNumbers',
		type: 'string',
		displayOptions: show('vatIban', 'check'),
		default: '',
		placeholder: 'e.g. IE6388047V',
		description:
			'EU VAT numbers with their country prefix, separated by commas (at most 10). Each is checked live in VIES, about 1 to 3 seconds per number. Give VAT numbers, IBANs or both.',
	},
	{
		displayName: 'IBANs',
		name: 'ibans',
		type: 'string',
		displayOptions: show('vatIban', 'check'),
		default: '',
		placeholder: 'e.g. NL91ABNA0417164300',
		description:
			'IBANs to validate, separated by commas (at most 50). Checks length, layout, check digits and bank code. No bank is contacted.',
	},
	{
		displayName: 'Additional Fields',
		name: 'additionalFields',
		type: 'collection',
		placeholder: 'Add Field',
		displayOptions: show('vatIban', 'check'),
		default: {},
		options: [
			{
				displayName: 'Expected Company Name',
				name: 'expectedName',
				type: 'string',
				default: '',
				placeholder: 'e.g. Google Ireland Ltd',
				description:
					'The company name you expect behind the VAT numbers. Compared with the name VIES returns, ignoring case, accents, punctuation and legal forms. Some member states, such as Germany, share no name.',
			},
			{
				displayName: 'Expected Country',
				name: 'expectedCountry',
				type: 'string',
				default: '',
				placeholder: 'e.g. NL',
				description:
					'ISO 3166 alpha-2 code of the country you expect. Compared with the country of each VAT number and IBAN.',
			},
			{
				displayName: 'Your Own VAT Number',
				name: 'requesterVatNumber',
				type: 'string',
				default: '',
				placeholder: 'e.g. NL123456789B01',
				description:
					'Your own EU VAT number. VIES then returns a consultation number that proves to a tax authority that you checked a number at a given time.',
			},
		],
	},
];

const questionFields: INodeProperties[] = [
	{
		displayName: 'Question',
		name: 'question',
		type: 'string',
		typeOptions: { rows: 2 },
		required: true,
		displayOptions: show('question', 'plan'),
		default: '',
		placeholder: 'e.g. Is Rosneft on the EU sanctions list?',
		description:
			'The question in plain words (at most 1000 characters). Returns the calls that answer it, their input and their maximum price. It does not run them.',
	},
];

const outputFields: INodeProperties[] = [
	{
		displayName: 'Simplify',
		name: 'simplify',
		type: 'boolean',
		displayOptions: { show: { resource: PAID_RESOURCES } },
		default: true,
		description: 'Whether to return a simplified version of the response instead of the raw data',
	},
	{
		displayName: 'Options',
		name: 'options',
		type: 'collection',
		placeholder: 'Add option',
		displayOptions: { show: { resource: PAID_RESOURCES } },
		default: {},
		options: [
			{
				displayName: 'Return Full Response',
				name: 'returnFullResponse',
				type: 'boolean',
				default: false,
				description:
					'Whether to return one item with the whole API response (rows, count, warnings, message, charged_usd and balance_usd) instead of one item per row',
			},
		],
	},
];

export const fieldProperties: INodeProperties[] = [
	pricingNotice,
	...counterpartyFields,
	...reportFields,
	...accountsFields,
	...newUkFields,
	...sanctionsFields,
	...vatIbanFields,
	...questionFields,
	...outputFields,
];

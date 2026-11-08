import { tool } from 'ai';
import { z } from 'zod';

export const DEFAULT_BASE_URL = 'https://api.boscolabs.dev';

export interface BoscoOptions {
  /** Bosco Labs API key (bl_live_...). Defaults to process.env.BOSCO_API_KEY. */
  apiKey?: string;
  /** Defaults to https://api.boscolabs.dev. */
  baseUrl?: string;
}

async function post(path: string, body: unknown, options: BoscoOptions, keyed: boolean) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (keyed) {
    const key = options.apiKey ?? process.env.BOSCO_API_KEY;
    if (!key) {
      throw new Error(
        'Bosco Labs API key missing: set BOSCO_API_KEY or pass { apiKey }. ' +
          'Get one at https://boscolabs.dev/api.html',
      );
    }
    headers.Authorization = `Bearer ${key}`;
  }
  const res = await fetch(`${options.baseUrl ?? DEFAULT_BASE_URL}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = data?.error;
    throw new Error(`Bosco Labs ${res.status} ${err?.code ?? ''}: ${err?.message ?? res.statusText}`);
  }
  return data;
}

/**
 * Call any Bosco Labs tool by name ("counterparty-check" or "counterparty_check") with its
 * input. Paid: needs an API key. The catalogue is at https://api.boscolabs.dev/v1/tools.
 */
export async function runBoscoTool(
  name: string,
  input: Record<string, unknown>,
  options: BoscoOptions = {},
) {
  const slug = name.replace(/_/g, '-');
  if (!/^[a-z0-9-]+$/.test(slug)) throw new Error(`Not a Bosco Labs tool name: ${name}`);
  return post(`/v1/${slug}`, input, options, true);
}

const noMarkup = /^[^\[\]{}<>\r\n]*$/;

/** KYB checklist for one company from official registers. $0.05 per company checked. */
export const counterpartyCheck = (options: BoscoOptions = {}) =>
  tool({
    description:
      'Can I do business with this company? One KYB checklist from official sources: register ' +
      'status, LEI, insolvency, recent accounts, sanctions (OFAC, UN, UK, EU) on the company and ' +
      'its officers, VAT (VIES) and IBAN when given. Screening aid, not a compliance, credit or ' +
      'legal determination. Costs $0.05 per company checked; an ambiguous name returns ' +
      'candidates for free.',
    inputSchema: z.object({
      query: z
        .string()
        .regex(noMarkup)
        .describe(
          'Company name (e.g. "Novo Nordisk") or identifier: LEI, UK company number, Danish CVR, ' +
            'Norwegian org number, French SIREN/SIRET, Finnish Business ID, Estonian registry ' +
            'code, US ticker or SEC CIK.',
        ),
      country: z
        .string()
        .regex(/^\s*([A-Za-z]{2})?\s*$/)
        .optional()
        .describe('ISO 3166 alpha-2 country code to disambiguate, e.g. "DK", "GB", "NO".'),
      vatNumber: z
        .string()
        .regex(noMarkup)
        .optional()
        .describe('EU VAT number with country prefix, e.g. "DK24256790"; checked live in VIES.'),
      iban: z
        .string()
        .regex(noMarkup)
        .optional()
        .describe('IBAN the counterparty wants to be paid on; checked offline.'),
      walletAddresses: z
        .array(z.string())
        .max(10)
        .optional()
        .describe('Crypto wallet addresses, matched exactly against OFAC-listed addresses.'),
    }),
    execute: async (input) => runBoscoTool('counterparty-check', input, options),
  });

const list = z.array(z.string()).optional();

/** Free planner: a question in plain words -> the exact Bosco Labs calls, with max prices. */
export const planOfficialRecordsQuery = (options: BoscoOptions = {}) =>
  tool({
    description:
      'Free, no key needed. Turns a question in plain words into the exact typed Bosco Labs ' +
      'calls that answer it (tool, input, why, maximum price of each step) and what is not ' +
      'covered. Pass the question verbatim and the entities you extracted from it. Run the ' +
      'steps with callBoscoTool (paid) or another Bosco Labs tool.',
    inputSchema: z.object({
      question: z.string().max(1000).describe("The user's question, verbatim."),
      entities: z
        .object({
          company_names: list.describe('Companies, e.g. ["Novo Nordisk A/S"].'),
          person_names: list.describe('People, e.g. ["Nancy Pelosi"].'),
          tickers: list.describe('US stock tickers, e.g. ["NVDA"].'),
          countries: list.describe('ISO 3166 alpha-2 codes, e.g. ["DE", "NL"].'),
          identifiers: z
            .record(z.string(), z.array(z.string()))
            .optional()
            .describe('Identifiers by kind (lei, cik, company_number, vat, iban, ...).'),
          keywords: z.string().optional().describe('Topic or search phrase.'),
          date_from: z.string().optional().describe('YYYY-MM-DD, start of the period.'),
          date_to: z.string().optional().describe('YYYY-MM-DD, end of the period.'),
        })
        .optional()
        .describe('What you already extracted from the question; the planner trusts it.'),
    }),
    execute: async (input) => post('/v1/plan', input, options, false),
  });

/** Generic tool: run any Bosco Labs tool, e.g. a step returned by planOfficialRecordsQuery. */
export const callBoscoTool = (options: BoscoOptions = {}) =>
  tool({
    description:
      'Run one Bosco Labs official-records tool (paid, prepaid credits) with its exact input, ' +
      'e.g. a step from planOfficialRecordsQuery. Catalogue and prices: ' +
      'https://api.boscolabs.dev/v1/tools?compact=true',
    inputSchema: z.object({
      tool: z.string().describe('Tool name, e.g. "counterparty-check" or "sanctions-screening".'),
      input: z.record(z.string(), z.unknown()).describe('The tool input as a JSON object.'),
    }),
    execute: async ({ tool: name, input }) => runBoscoTool(name, input, options),
  });

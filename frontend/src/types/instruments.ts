/**
 * Instrument contracts. Mirrors `backend/app/schemas/instruments.py`.
 *
 * The backend is the source of truth for which stocks are tradable; this file
 * only describes the shape it returns. Never hard-code a stock list here.
 */

export type InstrumentType = 'EQUITY';

export interface Instrument {
  symbol: string;
  company_name: string;
  exchange: string;
  instrument_type: InstrumentType;
  /** Null until the backend has probed the provider for this symbol. */
  data_available: boolean | null;
}

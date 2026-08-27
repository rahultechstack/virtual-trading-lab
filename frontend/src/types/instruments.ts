/**
 * Instrument contracts. Mirrors `backend/app/schemas/instruments.py`.
 *
 * The backend is the source of truth for what is tradable; this file only
 * describes the shape it returns. Never hard-code an instrument list here, and
 * never decide here whether something is a stock or a coin — read
 * `asset_class`.
 */

/** The dispatch key for market rules, data, fees and quantity handling. */
export type AssetClass = 'STOCK' | 'CRYPTO';

/** The finer label shown to users, inside an asset class. */
export type InstrumentType = 'EQUITY' | 'CRYPTOCURRENCY';

export interface Instrument {
  symbol: string;
  /** Company name for a stock, asset name for a coin. */
  company_name: string;
  asset_class: AssetClass;
  /** Venue code: `NSE`, or `CRYPTO` for coins. */
  exchange: string;
  /** Human label, e.g. `NSE Cash Market`. */
  market: string;
  /** Human label, e.g. `09:15-15:30 IST, Mon-Fri` or `24/7`. */
  trading_hours: string;
  instrument_type: InstrumentType;
  /**
   * Smallest tradable increment, as a Decimal string: `1` for a stock,
   * `0.00000001` for crypto. An order size must be a whole multiple of it —
   * the backend rejects anything else.
   */
  quantity_step: string;
  /** Whether fractional sizes are allowed. Drives the quantity input. */
  is_fractional: boolean;
  /** Decimal places implied by `quantity_step`. */
  quantity_precision: number;
  /** Null until the backend has probed the provider for this symbol. */
  data_available: boolean | null;
}

export const ASSET_CLASS_LABELS: Record<AssetClass, string> = {
  STOCK: 'Stock',
  CRYPTO: 'Crypto',
};

/** Filter options for the instrument picker. `null` means "everything". */
export type AssetFilter = AssetClass | null;

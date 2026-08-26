/**
 * THE INSTRUMENT THIS PLATFORM TRADES.
 *
 * ============================================================================
 *  TO TRADE A DIFFERENT SHARE, CHANGE IT IN TWO PLACES:
 *
 *    1. backend/.env      TRADING_SYMBOL=TCS
 *                         TRADING_EXCHANGE=NSE
 *
 *    2. frontend/.env     VITE_TRADING_SYMBOL=TCS
 *                         VITE_TRADING_EXCHANGE=NSE
 *
 *  Then restart both:  docker compose up -d --force-recreate backend frontend
 * ============================================================================
 *
 * The backend is the authority: every quote, candle, order and position it
 * returns already carries its own `symbol`, and the UI displays that. The
 * values here are only used as the *placeholder* shown before the first tick
 * arrives, and for the browser tab title — so a mismatch is cosmetic, not
 * functional. Keeping them in step just avoids a flash of the wrong name.
 */

export interface Instrument {
  /** Ticker as the exchange lists it, e.g. "RELIANCE", "TCS", "INFY". */
  symbol: string;
  /** Exchange code. The backend maps this to a vendor suffix (NSE -> .NS). */
  exchange: string;
  /** Shown in the browser tab. */
  displayName: string;
}

const SYMBOL = import.meta.env.VITE_TRADING_SYMBOL ?? 'RELIANCE';
const EXCHANGE = import.meta.env.VITE_TRADING_EXCHANGE ?? 'NSE';

export const INSTRUMENT: Instrument = {
  symbol: SYMBOL,
  exchange: EXCHANGE,
  displayName: `${EXCHANGE}:${SYMBOL}`,
};

/** Placeholder symbol, used until the first tick tells us the real one. */
export const DEFAULT_SYMBOL = INSTRUMENT.symbol;

/** Placeholder exchange, used until the first tick tells us the real one. */
export const DEFAULT_EXCHANGE = INSTRUMENT.exchange;

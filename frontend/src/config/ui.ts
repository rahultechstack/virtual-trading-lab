/**
 * **UI BEHAVIOUR.**
 *
 * Page sizes, refresh cadences and input defaults. Nothing here changes what
 * the backend does — these only shape what the browser asks for and how often.
 *
 * The backend caps every page size independently (`MAX_HISTORY_PAGE_SIZE`,
 * `MAX_SNAPSHOT_PAGE_SIZE` in `backend/.env`); raising a number here above the
 * backend's cap gets a 422, not more rows.
 */

/** Rows shown in the terminal's inline Orders and Trades tabs. */
export const TERMINAL_HISTORY_LIMIT = 25;

/** Rows fetched by the full-page Orders and Trades histories. */
export const HISTORY_PAGE_LIMIT = 200;

/**
 * Snapshots fetched for the portfolio equity curve.
 *
 * Higher than a normal page because it is plotted, not read.
 */
export const SNAPSHOT_PAGE_LIMIT = 1_000;

/**
 * Minimum gap between re-valuing the account against a new price.
 *
 * Ticks arrive far faster than the portfolio needs re-reading; without this
 * every tick would cause a round trip.
 */
export const REVALUE_THROTTLE_MS = 3_000;

/** How often the market-open badge re-checks. A session boundary is minute-scale. */
export const MARKET_STATUS_REFRESH_MS = 60_000;

/** Debounce on the instrument search box, so typing is not one request per key. */
export const INSTRUMENT_SEARCH_DEBOUNCE_MS = 180;

/** Instruments requested per search. The backend caps this too. */
export const INSTRUMENT_SEARCH_LIMIT = 100;

/** Quick-size buttons for an instrument that trades in whole units. */
export const WHOLE_QUANTITY_PRESETS = ['1', '10', '50', '100'] as const;

/**
 * Quick-size buttons for a fractional instrument.
 *
 * Deliberately fractions of one unit rather than a rupee value: one BTC and
 * one DOGE differ by seven orders of magnitude, so a fixed rupee ladder would
 * be useless for one of them.
 */
export const FRACTIONAL_QUANTITY_PRESETS = ['0.001', '0.01', '0.1', '1'] as const;

/** Default order size, per asset class, when the instrument changes. */
export const DEFAULT_WHOLE_QUANTITY = '10';
export const DEFAULT_FRACTIONAL_QUANTITY = '0.01';

/** localStorage key for the user's chosen indicators. */
export const INDICATOR_STORAGE_KEY = 'vtrader.indicators';

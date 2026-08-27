/**
 * Market calendar contracts. Mirrors `backend/app/schemas/markets.py`.
 *
 * The backend decides whether a market is open. This file describes the answer
 * it returns — no component computes a trading schedule.
 */

import type { AssetClass } from './instruments';

export type TradingStatus =
  | 'OPEN'
  | 'PRE_OPEN'
  | 'CLOSED'
  | 'WEEKEND'
  | 'HOLIDAY';

export interface MarketStatus {
  symbol: string;
  asset_class: AssetClass;
  /** Human label, e.g. `NSE Cash Market`. */
  market: string;
  /** Calendar governing it: `nse` or `crypto`. */
  calendar: string;
  status: TradingStatus;
  is_open: boolean;
  /** True for a market with no session boundaries at all. */
  is_24x7: boolean;
  timezone: string;
  server_time: string;
  /** Null for a 24/7 market — it has no next open. */
  next_open: string | null;
  /** Null for a 24/7 market — it has no next close. */
  next_close: string | null;
  reason: string;
  /**
   * Whether the backend REFUSES orders while closed. When false the status is
   * informational and trading still works, which is the default for this
   * paper-trading lab.
   */
  enforced: boolean;
}

export const STATUS_LABELS: Record<TradingStatus, string> = {
  OPEN: 'Open',
  PRE_OPEN: 'Pre-open',
  CLOSED: 'Closed',
  WEEKEND: 'Weekend',
  HOLIDAY: 'Holiday',
};

/** Badge tone per status. OPEN is the only positive one. */
export const STATUS_TONE: Record<TradingStatus, 'positive' | 'warning' | 'muted'> = {
  OPEN: 'positive',
  PRE_OPEN: 'warning',
  CLOSED: 'muted',
  WEEKEND: 'muted',
  HOLIDAY: 'muted',
};

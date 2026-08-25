/**
 * Live price stream contracts.
 *
 * Mirrors the payloads built in `backend/app/realtime/price_stream.py`.
 * Money arrives as strings carrying Decimal values — never parse them into a
 * JavaScript number for arithmetic, only for display.
 */

/** Where the quoted depth came from. */
export type BidAskSource = 'provider' | 'modelled' | 'unavailable';

/** How the backend obtains prices from the upstream provider. */
export type StreamMode = 'push' | 'poll';

export interface PriceTick {
  symbol: string;
  exchange: string;

  last_price: string;
  bid: string | null;
  ask: string | null;
  /** `modelled` means the spread was derived, not observed. */
  bid_ask_source: BidAskSource;
  volume: number;
  timestamp: string;

  previous_close: string | null;
  day_open: string | null;
  day_high: string | null;
  day_low: string | null;
  change: string | null;
  change_percent: string | null;

  currency: string;
  provider: string;
  /** True when the price was simulated rather than observed. */
  is_mock: boolean;
  is_delayed: boolean;
  mode: StreamMode;
  server_time: string;
}

export interface StreamStatus {
  running: boolean;
  mode: StreamMode;
  provider: string;
  is_mock: boolean;
  is_delayed: boolean;
  symbol: string;
  exchange: string;
  poll_interval_seconds: number;
  connections: number;
  ticks_broadcast: number;
  errors: number;
  last_error: string | null;
  server_time?: string;
}

export interface StreamError {
  message: string;
  detail?: string;
  fatal?: boolean;
  timestamp?: string;
}

export type StreamMessage =
  | { type: 'tick'; data: PriceTick }
  | { type: 'status'; data: StreamStatus }
  | { type: 'error'; data: StreamError }
  | { type: 'pong'; data: { server_time: string } };

export type ConnectionState =
  | 'connecting'
  | 'live'
  | 'reconnecting'
  | 'offline';

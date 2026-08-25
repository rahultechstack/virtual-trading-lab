/**
 * Market-data contracts. Mirrors `backend/app/schemas/market_data.py`.
 */

export type Interval = '1m' | '5m' | '15m' | '30m' | '1h' | '1d' | '1wk' | '1mo';

export interface Candle {
  timestamp: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number;
}

export interface CandleSeries {
  symbol: string;
  exchange: string;
  interval: Interval;
  provider: string;
  count: number;
  candles: Candle[];
}

/** Timeframes offered in the chart toolbar, with a sensible bar count each. */
export const TIMEFRAMES: ReadonlyArray<{
  interval: Interval;
  label: string;
  limit: number;
}> = [
  { interval: '1m', label: '1m', limit: 240 },
  { interval: '5m', label: '5m', limit: 240 },
  { interval: '15m', label: '15m', limit: 200 },
  { interval: '1h', label: '1H', limit: 200 },
  { interval: '1d', label: '1D', limit: 250 },
  { interval: '1wk', label: '1W', limit: 200 },
];

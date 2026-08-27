/**
 * Indicator contracts. Mirrors `backend/app/schemas/indicators.py`.
 *
 * Values arrive as strings carrying Decimal, like every other number in this
 * API. They are converted to `number` only where the chart needs them.
 */

import { INDICATOR_COLORS } from '@/config/chart';

import type { Interval } from './marketData';

export type IndicatorType = 'sma' | 'ema' | 'rsi' | 'macd' | 'bbands' | 'vwap';

/** `price` overlays the candles; `separate` needs its own axis below. */
export type Pane = 'price' | 'separate';

export type SeriesStyle = 'line' | 'histogram';

export interface IndicatorPoint {
  timestamp: string;
  value: string;
}

export interface IndicatorSeries {
  key: string;
  label: string;
  style: SeriesStyle;
  points: IndicatorPoint[];
}

export interface Indicator {
  key: string;
  type: IndicatorType;
  label: string;
  pane: Pane;
  params: Record<string, number>;
  /** Leading bars with no value while the indicator warms up. */
  warmup: number;
  /** True when the candle window was too short to produce anything. */
  insufficient_data: boolean;
  scale_min: string | null;
  scale_max: string | null;
  series: IndicatorSeries[];
}

export interface IndicatorSet {
  symbol: string;
  exchange: string;
  interval: Interval;
  provider: string;
  candle_count: number;
  indicators: Indicator[];
}

/** A togglable preset. `spec` is what the API is asked for. */
export interface IndicatorPreset {
  id: string;
  spec: string;
  label: string;
  pane: Pane;
  color: string;
}

/**
 * The presets offered in the chart toolbar.
 *
 * Colours are fixed per preset rather than assigned by index, so an
 * indicator keeps its colour no matter which others are enabled.
 */
export const INDICATOR_PRESETS: readonly IndicatorPreset[] = [
  { id: 'sma20', spec: 'sma:20', label: 'SMA 20', pane: 'price', color: INDICATOR_COLORS.primary },
  { id: 'sma50', spec: 'sma:50', label: 'SMA 50', pane: 'price', color: INDICATOR_COLORS.violet },
  { id: 'ema21', spec: 'ema:21', label: 'EMA 21', pane: 'price', color: INDICATOR_COLORS.amber },
  { id: 'bbands', spec: 'bbands:20:2', label: 'Bollinger', pane: 'price', color: INDICATOR_COLORS.slate },
  { id: 'vwap', spec: 'vwap:20', label: 'VWAP', pane: 'price', color: INDICATOR_COLORS.teal },
  { id: 'rsi14', spec: 'rsi:14', label: 'RSI 14', pane: 'separate', color: INDICATOR_COLORS.primary },
  { id: 'macd', spec: 'macd:12:26:9', label: 'MACD', pane: 'separate', color: INDICATOR_COLORS.primary },
];

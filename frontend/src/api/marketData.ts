import { apiGet } from './client';
import type { CandleSeries, Interval } from '@/types/marketData';

export function fetchCandles(
  interval: Interval,
  limit: number,
  symbol?: string | null,
  signal?: AbortSignal,
): Promise<CandleSeries> {
  const query = new URLSearchParams({ interval, limit: String(limit) });
  if (symbol) query.set('symbol', symbol);
  return apiGet<CandleSeries>(`/market-data/candles?${query.toString()}`, signal);
}

import { apiGet } from './client';
import type { CandleSeries, Interval } from '@/types/marketData';

export function fetchCandles(
  interval: Interval,
  limit: number,
  signal?: AbortSignal,
): Promise<CandleSeries> {
  return apiGet<CandleSeries>(
    `/market-data/candles?interval=${interval}&limit=${limit}`,
    signal,
  );
}

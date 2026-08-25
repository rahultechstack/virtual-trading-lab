import { apiGet } from './client';
import type { Interval } from '@/types/marketData';
import type { IndicatorSet } from '@/types/indicators';

/**
 * Compute indicators over the same candle window the chart is drawing, so the
 * study and the price agree.
 */
export function fetchIndicators(
  interval: Interval,
  limit: number,
  specs: string[],
  signal?: AbortSignal,
): Promise<IndicatorSet> {
  const query = new URLSearchParams({
    interval,
    limit: String(limit),
    indicators: specs.join(','),
  });
  return apiGet<IndicatorSet>(`/indicators?${query.toString()}`, signal);
}

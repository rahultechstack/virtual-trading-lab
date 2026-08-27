import { apiGet } from './client';
import type { MarketStatus } from '@/types/markets';

/** Whether one instrument's market is open, and when it next changes. */
export function fetchMarketStatus(
  symbol?: string,
  signal?: AbortSignal,
): Promise<MarketStatus> {
  const query = symbol ? `?symbol=${encodeURIComponent(symbol)}` : '';
  return apiGet<MarketStatus>(`/markets/status${query}`, signal);
}

/** Trading status of every asset class at once. */
export function fetchMarketStatuses(
  signal?: AbortSignal,
): Promise<MarketStatus[]> {
  return apiGet<MarketStatus[]>('/markets/statuses', signal);
}

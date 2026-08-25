import { apiGet, apiPost } from './client';
import type { Performance, PortfolioSnapshot, SnapshotSeries } from '@/types/portfolio';

export function fetchSnapshots(
  limit = 500,
  signal?: AbortSignal,
): Promise<SnapshotSeries> {
  return apiGet<SnapshotSeries>(`/portfolio/snapshots?limit=${limit}`, signal);
}

export function fetchPerformance(signal?: AbortSignal): Promise<Performance> {
  return apiGet<Performance>('/portfolio/performance', signal);
}

/** Capture a snapshot now. `markPrice` values an open position. */
export function captureSnapshot(markPrice?: string | null): Promise<PortfolioSnapshot> {
  const query = markPrice ? `?mark_price=${encodeURIComponent(markPrice)}` : '';
  return apiPost<PortfolioSnapshot>(`/portfolio/snapshots${query}`);
}

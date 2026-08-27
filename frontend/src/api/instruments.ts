import { apiGet } from './client';
import type { AssetClass, Instrument } from '@/types/instruments';

/**
 * The tradable universe, optionally filtered by search text and asset class.
 *
 * The backend owns the catalogue; passing `assetClass` narrows it server-side
 * rather than filtering a full list in the browser.
 */
export function fetchInstruments(
  search?: string,
  assetClass?: AssetClass | null,
  limit = 100,
  signal?: AbortSignal,
): Promise<Instrument[]> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (search && search.trim()) query.set('search', search.trim());
  if (assetClass) query.set('asset_class', assetClass);
  return apiGet<Instrument[]>(`/instruments?${query.toString()}`, signal);
}

/** One instrument, with its provider availability verified server-side. */
export function fetchInstrument(
  symbol: string,
  signal?: AbortSignal,
): Promise<Instrument> {
  return apiGet<Instrument>(`/instruments/${encodeURIComponent(symbol)}`, signal);
}

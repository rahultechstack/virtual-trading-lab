import { apiGet } from './client';
import type { Instrument } from '@/types/instruments';

/** The tradable universe, optionally filtered by symbol or company name. */
export function fetchInstruments(
  search?: string,
  limit = 50,
  signal?: AbortSignal,
): Promise<Instrument[]> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (search && search.trim()) query.set('search', search.trim());
  return apiGet<Instrument[]>(`/instruments?${query.toString()}`, signal);
}

/** One instrument, with its provider availability verified server-side. */
export function fetchInstrument(
  symbol: string,
  signal?: AbortSignal,
): Promise<Instrument> {
  return apiGet<Instrument>(`/instruments/${encodeURIComponent(symbol)}`, signal);
}

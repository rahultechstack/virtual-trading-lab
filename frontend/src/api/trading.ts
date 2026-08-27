import { apiGet, apiPost } from './client';
import type {
  Order,
  OrderResult,
  PlaceOrderRequest,
  Portfolio,
  PortfolioSummary,
  Position,
  Trade,
} from '@/types/trading';

export function placeOrder(payload: PlaceOrderRequest): Promise<OrderResult> {
  return apiPost<OrderResult>('/trading/orders', payload);
}

export function fetchOrders(limit = 25, signal?: AbortSignal): Promise<Order[]> {
  return apiGet<Order[]>(`/trading/orders?limit=${limit}`, signal);
}

export function fetchTrades(limit = 25, signal?: AbortSignal): Promise<Trade[]> {
  return apiGet<Trade[]>(`/trading/trades?limit=${limit}`, signal);
}

export function fetchPosition(
  symbol?: string | null,
  signal?: AbortSignal,
): Promise<Position> {
  const query = symbol ? `?symbol=${encodeURIComponent(symbol)}` : '';
  return apiGet<Position>(`/trading/position${query}`, signal);
}

/** Every instrument that has ever traded. */
export function fetchPositions(signal?: AbortSignal): Promise<Position[]> {
  return apiGet<Position[]>('/trading/positions', signal);
}

/**
 * Whole-account valuation across every instrument.
 *
 * `marks` is a symbol -> price map; an open position without one is reported
 * unvalued rather than guessed at, which mirrors the backend contract.
 */
export function fetchPortfolioSummary(
  marks: Record<string, string>,
  signal?: AbortSignal,
): Promise<PortfolioSummary> {
  const pairs = Object.entries(marks)
    .filter(([, price]) => Boolean(price))
    .map(([symbol, price]) => `${symbol}:${price}`)
    .join(',');
  const query = pairs ? `?marks=${encodeURIComponent(pairs)}` : '';
  return apiGet<PortfolioSummary>(`/trading/portfolio/summary${query}`, signal);
}

/**
 * Portfolio valuation.
 *
 * `markPrice` is passed to the server so the P&L arithmetic stays in Decimal
 * rather than being recomputed in JavaScript floats. Without it the server
 * reports zero unrealized P&L by design.
 */
export function fetchPortfolio(
  markPrice?: string | null,
  symbol?: string | null,
  signal?: AbortSignal,
): Promise<Portfolio> {
  const query = new URLSearchParams();
  if (markPrice) query.set('mark_price', markPrice);
  if (symbol) query.set('symbol', symbol);
  const suffix = query.toString() ? `?${query.toString()}` : '';
  return apiGet<Portfolio>(`/trading/portfolio${suffix}`, signal);
}

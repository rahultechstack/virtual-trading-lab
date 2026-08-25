import { apiGet, apiPost } from './client';
import type {
  Order,
  OrderResult,
  PlaceOrderRequest,
  Portfolio,
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

export function fetchPosition(signal?: AbortSignal): Promise<Position> {
  return apiGet<Position>('/trading/position', signal);
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
  signal?: AbortSignal,
): Promise<Portfolio> {
  const query = markPrice ? `?mark_price=${encodeURIComponent(markPrice)}` : '';
  return apiGet<Portfolio>(`/trading/portfolio${query}`, signal);
}

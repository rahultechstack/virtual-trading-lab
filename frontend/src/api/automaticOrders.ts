import { apiGet, apiPost } from './client';
import type {
  AutomaticOrder,
  AutomaticOrderStatus,
  CreateAutomaticOrderRequest,
} from '@/types/automaticOrders';

export function createAutomaticOrder(
  payload: CreateAutomaticOrderRequest,
): Promise<AutomaticOrder> {
  return apiPost<AutomaticOrder>('/automatic-orders', payload);
}

export function fetchActiveAutomaticOrders(
  signal?: AbortSignal,
): Promise<AutomaticOrder[]> {
  return apiGet<AutomaticOrder[]>('/automatic-orders/active', signal);
}

export function fetchAutomaticOrderHistory(
  limit = 50,
  status?: AutomaticOrderStatus,
  signal?: AbortSignal,
): Promise<AutomaticOrder[]> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (status) query.set('status', status);
  return apiGet<AutomaticOrder[]>(`/automatic-orders?${query.toString()}`, signal);
}

export function cancelAutomaticOrder(id: number): Promise<AutomaticOrder> {
  return apiPost<AutomaticOrder>(`/automatic-orders/${id}/cancel`);
}

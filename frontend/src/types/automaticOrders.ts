/**
 * Automatic order contracts. Mirrors `backend/app/schemas/automatic_order.py`.
 *
 * Money arrives as strings carrying Decimal, like everywhere else in this API.
 */

export type AutomaticOrderType = 'STOP_LOSS' | 'PRICE_TRIGGER';

/** GTE fires at or above the trigger, LTE at or below it. */
export type TriggerCondition = 'GTE' | 'LTE';

export type AutomaticOrderStatus = 'ACTIVE' | 'TRIGGERED' | 'CANCELLED' | 'FAILED';

export interface AutomaticOrder {
  id: number;
  symbol: string;
  exchange: string;
  asset_class: import('./instruments').AssetClass;
  order_type: AutomaticOrderType;
  trigger_price: string;
  trigger_condition: TriggerCondition;
  action: import('./trading').OrderSide;
  /** Decimal string — fractional for crypto. */
  quantity: string;
  status: AutomaticOrderStatus;
  created_at: string;
  triggered_at: string | null;
  cancelled_at: string | null;
  trigger_market_price: string | null;
  triggered_order_id: number | null;
  reason: string | null;
}

export interface CreateAutomaticOrderRequest {
  order_type: AutomaticOrderType;
  trigger_price: string;
  trigger_condition: TriggerCondition;
  action: import('./trading').OrderSide;
  /** Decimal string, e.g. "100" or "0.001". Never a float. */
  quantity: string;
  /** Optional; lets the backend reject a stop that would fire immediately. */
  reference_price?: string | null;
  /** Instrument. Defaults to the backend's configured default. */
  symbol?: string;
}

export const CONDITION_LABELS: Record<TriggerCondition, string> = {
  GTE: '>=',
  LTE: '<=',
};

export const TYPE_LABELS: Record<AutomaticOrderType, string> = {
  STOP_LOSS: 'Stop Loss',
  PRICE_TRIGGER: 'Price Trigger',
};

export const STATUS_TONE: Record<AutomaticOrderStatus, string> = {
  ACTIVE: 'ok',
  TRIGGERED: 'degraded',
  CANCELLED: 'degraded',
  FAILED: 'error',
};

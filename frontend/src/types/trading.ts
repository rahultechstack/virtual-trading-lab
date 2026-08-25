/**
 * Trading contracts.
 *
 * Mirrors `backend/app/schemas/trading.py` and `wallet.py`. Every monetary
 * value arrives as a **string** carrying a Decimal — format it for display,
 * never do arithmetic on it as a JavaScript number.
 */

export type OrderSide = 'BUY' | 'SELL' | 'SHORT_SELL' | 'BUY_TO_COVER';
export type OrderStatus = 'PENDING' | 'FILLED' | 'REJECTED' | 'CANCELLED';
export type OrderType = 'MARKET';

export interface Wallet {
  id: number;
  currency: string;
  initial_balance: string;
  cash_balance: string;
  created_at: string;
  updated_at: string;
}

export interface Order {
  id: number;
  symbol: string;
  exchange: string;
  side: OrderSide;
  order_type: OrderType;
  quantity: number;
  requested_price: string | null;
  execution_price: string | null;
  status: OrderStatus;
  rejection_reason: string | null;
  created_at: string;
  filled_at: string | null;
}

export interface Trade {
  id: number;
  order_id: number;
  symbol: string;
  exchange: string;
  side: OrderSide;
  quantity: number;

  reference_price: string | null;
  bid_price: string | null;
  ask_price: string | null;
  execution_price: string;

  spread_cost: string;
  slippage_cost: string;

  brokerage: string;
  stt: string;
  exchange_charges: string;
  sebi_charges: string;
  stamp_duty: string;
  gst: string;
  dp_charges: string;
  total_charges: string;

  gross_pnl: string;
  net_pnl: string;

  closed_quantity: number;
  created_at: string;
}

export interface Position {
  symbol: string;
  exchange: string;
  /** Carries direction: > 0 long, 0 flat, < 0 short. */
  quantity: number;
  average_price: string;
  realized_pnl: string;
  total_charges: string;
  net_realized_pnl: string;
  updated_at: string | null;
}

export interface Portfolio {
  cash_balance: string;
  initial_balance: string;
  quantity: number;
  average_price: string;
  realized_pnl: string;
  total_charges: string;
  net_realized_pnl: string;
  unrealized_pnl: string;
  position_value: string;
  total_equity: string;
  total_pnl: string;
  net_total_pnl: string;
  mark_price: string | null;
  currency: string;
}

export interface PlaceOrderRequest {
  side: OrderSide;
  quantity: number;
  reference_price: string;
  symbol?: string;
}

export interface OrderResult {
  order: Order;
  trade: Trade;
  position: Position;
  gross_pnl: string;
  total_charges: string;
  net_pnl: string;
  cash_delta: string;
}

export const SIDE_LABELS: Record<OrderSide, string> = {
  BUY: 'Buy',
  SELL: 'Sell',
  SHORT_SELL: 'Short Sell',
  BUY_TO_COVER: 'Buy to Cover',
};

/** Sides that increase quantity are shown as bullish, the others bearish. */
export function isBullishSide(side: OrderSide): boolean {
  return side === 'BUY' || side === 'BUY_TO_COVER';
}

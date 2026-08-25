/**
 * Portfolio history and performance contracts.
 * Mirrors `backend/app/schemas/portfolio.py`.
 */

export type SnapshotSource = 'PERIODIC' | 'TRADE' | 'MANUAL';

export interface PortfolioSnapshot {
  id: number;
  captured_at: string;
  source: SnapshotSource;
  symbol: string;

  quantity: number;
  average_price: string;
  mark_price: string | null;

  cash: string;
  position_value: string;
  total_value: string;

  realized_pnl: string;
  total_charges: string;
  unrealized_pnl: string;
  net_pnl: string;
}

export interface SnapshotSeries {
  count: number;
  first_captured_at: string | null;
  last_captured_at: string | null;
  snapshots: PortfolioSnapshot[];
}

export interface TradeExtreme {
  trade_id: number;
  side: string;
  quantity: number;
  execution_price: string;
  gross_pnl: string;
  total_charges: string;
  net_pnl: string;
  created_at: string;
}

export interface Performance {
  total_trades: number;
  /** Fills that closed exposure; only these can win or lose. */
  closing_trades: number;
  winning_trades: number;
  losing_trades: number;
  breakeven_trades: number;
  win_rate: string | null;

  total_gross_pnl: string;
  total_charges: string;
  total_net_pnl: string;

  average_win: string | null;
  average_loss: string | null;
  profit_factor: string | null;

  largest_winning_trade: TradeExtreme | null;
  largest_losing_trade: TradeExtreme | null;

  total_orders: number;
  filled_orders: number;
  rejected_orders: number;
}

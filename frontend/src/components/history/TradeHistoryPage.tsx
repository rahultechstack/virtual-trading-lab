import { useCallback, useEffect, useState } from 'react';

import { PageShell } from './PageShell';
import { fetchTrades } from '@/api/trading';
import { HISTORY_PAGE_LIMIT as LIMIT } from '@/config/ui';
import { SIDE_LABELS, isBullishSide, type Trade } from '@/types/trading';
import {
  formatDateTime,
  formatQuantity,
  formatRupees,
  signClass,
} from '@/utils/format';

/**
 * Every executed fill, newest first.
 *
 * Shows the full contract note: where it filled against the reference price,
 * what the spread and slippage cost, the charges, and gross versus net P&L.
 */
export function TradeHistoryPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchTrades(LIMIT)
      .then(setTrades)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Failed to load trades.'),
      )
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  return (
    <PageShell
      title="Trade History"
      subtitle={`${trades.length} fill${trades.length === 1 ? '' : 's'}`}
      loading={loading}
      error={error}
      onRetry={load}
      actions={
        <button type="button" className="chip" onClick={load}>
          Refresh
        </button>
      }
    >
      {trades.length === 0 ? (
        <p className="muted table-empty">No trades yet.</p>
      ) : (
        <div className="table-scroll table-scroll--tall">
          <table className="table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Side</th>
                <th className="numeric">Qty</th>
                <th className="numeric">Reference</th>
                <th className="numeric">Fill</th>
                <th className="numeric">Spread</th>
                <th className="numeric">Slippage</th>
                <th className="numeric">Charges</th>
                <th className="numeric">Gross</th>
                <th className="numeric">Net</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((trade) => (
                <tr key={trade.id}>
                  <td className="muted">{formatDateTime(trade.created_at)}</td>
                  <td className={isBullishSide(trade.side) ? 'positive' : 'negative'}>
                    {SIDE_LABELS[trade.side]}
                  </td>
                  <td className="numeric">{formatQuantity(trade.quantity)}</td>
                  <td className="numeric muted">
                    {formatRupees(trade.reference_price)}
                  </td>
                  <td className="numeric">{formatRupees(trade.execution_price)}</td>
                  <td className="numeric muted">{formatRupees(trade.spread_cost)}</td>
                  <td className="numeric muted">{formatRupees(trade.slippage_cost)}</td>
                  <td className="numeric muted">{formatRupees(trade.total_charges)}</td>
                  <td className={`numeric ${signClass(trade.gross_pnl)}`}>
                    {formatRupees(trade.gross_pnl, { sign: true })}
                  </td>
                  <td className={`numeric ${signClass(trade.net_pnl)}`}>
                    {formatRupees(trade.net_pnl, { sign: true })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  );
}

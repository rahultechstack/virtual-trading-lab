import { SIDE_LABELS, isBullishSide, type Trade } from '@/types/trading';
import { formatQuantity, formatRupees, formatTime, signClass } from '@/utils/format';

interface Props {
  trades: Trade[];
}

/**
 * Executed trades, newest first.
 *
 * Shows gross P&L, charges and net side by side -- the three figures the
 * execution engine produces -- so the cost of trading is never hidden.
 */
export function TradeHistory({ trades }: Props) {
  if (trades.length === 0) {
    return <p className="muted table-empty">No trades yet.</p>;
  }

  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Side</th>
            <th className="numeric">Qty</th>
            <th className="numeric">Fill</th>
            <th className="numeric">Gross</th>
            <th className="numeric">Charges</th>
            <th className="numeric">Net</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => (
            <tr key={trade.id}>
              <td className="muted">{formatTime(trade.created_at)}</td>
              <td className={isBullishSide(trade.side) ? 'positive' : 'negative'}>
                {SIDE_LABELS[trade.side]}
              </td>
              <td className="numeric">{formatQuantity(trade.quantity)}</td>
              <td className="numeric">{formatRupees(trade.execution_price)}</td>
              <td className={`numeric ${signClass(trade.gross_pnl)}`}>
                {formatRupees(trade.gross_pnl, { sign: true })}
              </td>
              <td className="numeric muted">{formatRupees(trade.total_charges)}</td>
              <td className={`numeric ${signClass(trade.net_pnl)}`}>
                {formatRupees(trade.net_pnl, { sign: true })}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

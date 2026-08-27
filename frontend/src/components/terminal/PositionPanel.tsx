import { DEFAULT_EXCHANGE, DEFAULT_SYMBOL } from '@/config/instrument';
import type { Portfolio, Position } from '@/types/trading';
import {
  formatQuantity,
  formatRupees,
  signClass,
  toQuantity,
} from '@/utils/format';

interface Props {
  position: Position | null;
  portfolio: Portfolio | null;
  currentPrice: string | null;
}

type Direction = 'LONG' | 'SHORT' | 'FLAT';

function directionOf(quantity: number): Direction {
  if (quantity > 0) return 'LONG';
  if (quantity < 0) return 'SHORT';
  return 'FLAT';
}

/** The open position, valued at the live price. */
export function PositionPanel({ position, portfolio, currentPrice }: Props) {
  // A Decimal string on the wire; read as a number only for the sign test and
  // the display, never for arithmetic that is sent back.
  const quantity = toQuantity(position?.quantity);
  const direction = directionOf(quantity);
  const isFlat = direction === 'FLAT';

  return (
    <section className="panel">
      <header className="panel__header">
        <h2 className="panel__title">Position</h2>
        <span
          className={`badge badge--${
            direction === 'LONG' ? 'ok' : direction === 'SHORT' ? 'error' : 'degraded'
          }`}
        >
          {direction}
        </span>
      </header>

      {isFlat ? (
        <p className="muted">No open position.</p>
      ) : (
        <table className="table table--position">
          <thead>
            <tr>
              <th>Symbol</th>
              <th className="numeric">Qty</th>
              <th className="numeric">Avg price</th>
              <th className="numeric">Current</th>
              <th className="numeric">Unrealized</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <strong>{position?.symbol ?? DEFAULT_SYMBOL}</strong>
                <span className="muted"> {position?.exchange ?? DEFAULT_EXCHANGE}</span>
              </td>
              <td className={`numeric ${quantity > 0 ? 'positive' : 'negative'}`}>
                {formatQuantity(position?.quantity)}
              </td>
              <td className="numeric">{formatRupees(position?.average_price)}</td>
              <td className="numeric">{formatRupees(currentPrice)}</td>
              <td className={`numeric ${signClass(portfolio?.unrealized_pnl)}`}>
                {formatRupees(portfolio?.unrealized_pnl, { sign: true })}
              </td>
            </tr>
          </tbody>
        </table>
      )}
    </section>
  );
}

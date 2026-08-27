import { useCallback, useEffect, useState } from 'react';

import { PageShell } from './PageShell';
import { fetchOrders } from '@/api/trading';
import { HISTORY_PAGE_LIMIT as LIMIT } from '@/config/ui';
import { SIDE_LABELS, isBullishSide, type Order, type OrderStatus } from '@/types/trading';
import { formatDateTime, formatQuantity, formatRupees } from '@/utils/format';

const STATUS_TONE: Record<OrderStatus, string> = {
  FILLED: 'ok',
  PENDING: 'degraded',
  REJECTED: 'error',
  CANCELLED: 'degraded',
};

type Filter = 'ALL' | OrderStatus;

const FILTERS: ReadonlyArray<Filter> = ['ALL', 'FILLED', 'REJECTED'];

/**
 * Every order, newest first.
 *
 * Rejections are kept and shown with their reason -- the audit trail is about
 * what was attempted, not only what succeeded.
 */
export function OrderHistoryPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [filter, setFilter] = useState<Filter>('ALL');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchOrders(LIMIT)
      .then(setOrders)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Failed to load orders.'),
      )
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const visible =
    filter === 'ALL' ? orders : orders.filter((order) => order.status === filter);

  return (
    <PageShell
      title="Order History"
      subtitle={`${visible.length} of ${orders.length} order${orders.length === 1 ? '' : 's'}`}
      loading={loading}
      error={error}
      onRetry={load}
      actions={
        <>
          {FILTERS.map((value) => (
            <button
              key={value}
              type="button"
              className={`chip ${filter === value ? 'chip--active' : ''}`}
              onClick={() => setFilter(value)}
            >
              {value}
            </button>
          ))}
          <button type="button" className="chip" onClick={load}>
            Refresh
          </button>
        </>
      }
    >
      {visible.length === 0 ? (
        <p className="muted table-empty">No orders to show.</p>
      ) : (
        <div className="table-scroll table-scroll--tall">
          <table className="table">
            <thead>
              <tr>
                <th className="numeric">ID</th>
                <th>Time</th>
                <th>Side</th>
                <th className="numeric">Qty</th>
                <th className="numeric">Fill price</th>
                <th>Status</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((order) => (
                <tr key={order.id}>
                  <td className="numeric muted">{order.id}</td>
                  <td className="muted">{formatDateTime(order.created_at)}</td>
                  <td className={isBullishSide(order.side) ? 'positive' : 'negative'}>
                    {SIDE_LABELS[order.side]}
                  </td>
                  <td className="numeric">{formatQuantity(order.quantity)}</td>
                  <td className="numeric">{formatRupees(order.execution_price)}</td>
                  <td>
                    <span className={`badge badge--${STATUS_TONE[order.status]}`}>
                      {order.status}
                    </span>
                  </td>
                  <td className="muted reason-cell">
                    {order.rejection_reason ?? '\u2014'}
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

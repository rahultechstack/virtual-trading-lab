import { SIDE_LABELS, isBullishSide, type Order } from '@/types/trading';
import { formatQuantity, formatRupees, formatTime } from '@/utils/format';

interface Props {
  orders: Order[];
}

const STATUS_TONE: Record<Order['status'], string> = {
  FILLED: 'ok',
  PENDING: 'degraded',
  REJECTED: 'error',
  CANCELLED: 'degraded',
};

/** Recent orders, newest first. Rejections are shown with their reason. */
export function OrdersPanel({ orders }: Props) {
  if (orders.length === 0) {
    return <p className="muted table-empty">No orders yet.</p>;
  }

  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Side</th>
            <th className="numeric">Qty</th>
            <th className="numeric">Price</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => (
            <tr key={order.id}>
              <td className="muted">{formatTime(order.created_at)}</td>
              <td className={isBullishSide(order.side) ? 'positive' : 'negative'}>
                {SIDE_LABELS[order.side]}
              </td>
              <td className="numeric">{formatQuantity(order.quantity)}</td>
              <td className="numeric">{formatRupees(order.execution_price)}</td>
              <td>
                <span className={`badge badge--${STATUS_TONE[order.status]}`}>
                  {order.status}
                </span>
                {order.rejection_reason && (
                  <span className="muted reason" title={order.rejection_reason}>
                    {order.rejection_reason}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

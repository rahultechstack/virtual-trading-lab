import { useCallback, useEffect, useState } from 'react';

import { EquityCurve } from './EquityCurve';
import { PageShell } from './PageShell';
import { captureSnapshot, fetchSnapshots } from '@/api/portfolio';
import { SNAPSHOT_PAGE_LIMIT as LIMIT } from '@/config/ui';
import { useLivePrice } from '@/hooks/useLivePrice';
import type { PortfolioSnapshot } from '@/types/portfolio';
import {
  formatDateTime,
  formatQuantity,
  formatRupees,
  signClass,
} from '@/utils/format';

type Metric = 'total_value' | 'net_pnl';

const METRICS: ReadonlyArray<{ value: Metric; label: string }> = [
  { value: 'total_value', label: 'Total value' },
  { value: 'net_pnl', label: 'Net P&L' },
];

const SOURCE_TONE: Record<PortfolioSnapshot['source'], string> = {
  TRADE: 'ok',
  PERIODIC: 'degraded',
  MANUAL: 'degraded',
};

/**
 * The equity curve and the snapshots behind it.
 *
 * `TRADE` snapshots land at the exact moment the account changed; `PERIODIC`
 * ones fill in the gaps while a position is open and the price moves.
 */
export function PortfolioHistoryPage() {
  const { tick } = useLivePrice();
  const [snapshots, setSnapshots] = useState<PortfolioSnapshot[]>([]);
  const [metric, setMetric] = useState<Metric>('total_value');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [capturing, setCapturing] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchSnapshots(LIMIT)
      .then((series) => setSnapshots(series.snapshots))
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Failed to load history.'),
      )
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const capture = useCallback(async () => {
    setCapturing(true);
    setError(null);
    try {
      await captureSnapshot(tick?.last_price ?? null);
      load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not capture a snapshot.');
    } finally {
      setCapturing(false);
    }
  }, [tick, load]);

  // Newest first in the table, oldest first in the chart.
  const rows = [...snapshots].reverse();

  return (
    <PageShell
      title="Portfolio History"
      subtitle={
        snapshots.length > 0
          ? `${snapshots.length} snapshots from ${formatDateTime(snapshots[0].captured_at)}`
          : 'No snapshots yet'
      }
      loading={loading}
      error={error}
      onRetry={load}
      actions={
        <>
          {METRICS.map((entry) => (
            <button
              key={entry.value}
              type="button"
              className={`chip ${metric === entry.value ? 'chip--active' : ''}`}
              onClick={() => setMetric(entry.value)}
            >
              {entry.label}
            </button>
          ))}
          <button
            type="button"
            className="chip"
            onClick={() => void capture()}
            disabled={capturing}
          >
            {capturing ? 'Capturing\u2026' : 'Snapshot now'}
          </button>
        </>
      }
    >
      <EquityCurve snapshots={snapshots} metric={metric} />

      {rows.length > 0 && (
        <div className="table-scroll table-scroll--tall">
          <table className="table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Source</th>
                <th className="numeric">Qty</th>
                <th className="numeric">Mark</th>
                <th className="numeric">Cash</th>
                <th className="numeric">Position value</th>
                <th className="numeric">Total value</th>
                <th className="numeric">Realized</th>
                <th className="numeric">Unrealized</th>
                <th className="numeric">Net P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((snapshot) => (
                <tr key={snapshot.id}>
                  <td className="muted">{formatDateTime(snapshot.captured_at)}</td>
                  <td>
                    <span className={`badge badge--${SOURCE_TONE[snapshot.source]}`}>
                      {snapshot.source}
                    </span>
                  </td>
                  <td className="numeric">{formatQuantity(snapshot.quantity)}</td>
                  <td className="numeric muted">{formatRupees(snapshot.mark_price)}</td>
                  <td className="numeric">{formatRupees(snapshot.cash)}</td>
                  <td className="numeric">{formatRupees(snapshot.position_value)}</td>
                  <td className="numeric">{formatRupees(snapshot.total_value)}</td>
                  <td className={`numeric ${signClass(snapshot.realized_pnl)}`}>
                    {formatRupees(snapshot.realized_pnl, { sign: true })}
                  </td>
                  <td className={`numeric ${signClass(snapshot.unrealized_pnl)}`}>
                    {formatRupees(snapshot.unrealized_pnl, { sign: true })}
                  </td>
                  <td className={`numeric ${signClass(snapshot.net_pnl)}`}>
                    {formatRupees(snapshot.net_pnl, { sign: true })}
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

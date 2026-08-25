import { useCallback, useEffect, useState } from 'react';

import { PageShell } from './PageShell';
import { fetchPerformance } from '@/api/portfolio';
import type { Performance, TradeExtreme } from '@/types/portfolio';
import {
  formatDateTime,
  formatQuantity,
  formatRupees,
  signClass,
  toNumber,
} from '@/utils/format';

interface StatProps {
  label: string;
  value: string;
  tone?: string;
  hint?: string;
}

function Stat({ label, value, tone = '', hint }: StatProps) {
  return (
    <div className="stat" title={hint}>
      <span className="stat__label">{label}</span>
      <span className={`stat__value ${tone}`}>{value}</span>
    </div>
  );
}

function ExtremeCard({
  title,
  trade,
  tone,
}: {
  title: string;
  trade: TradeExtreme | null;
  tone: string;
}) {
  return (
    <section className="panel">
      <header className="panel__header">
        <h2 className="panel__title">{title}</h2>
      </header>
      {trade === null ? (
        <p className="muted">None yet.</p>
      ) : (
        <>
          <div className={`stat__value ${tone}`}>
            {formatRupees(trade.net_pnl, { sign: true })}
          </div>
          <dl className="kv kv--tight">
            <dt>Trade</dt>
            <dd>#{trade.trade_id}</dd>
            <dt>Side</dt>
            <dd>{trade.side}</dd>
            <dt>Quantity</dt>
            <dd>{formatQuantity(trade.quantity)}</dd>
            <dt>Fill price</dt>
            <dd>{formatRupees(trade.execution_price)}</dd>
            <dt>Gross</dt>
            <dd>{formatRupees(trade.gross_pnl, { sign: true })}</dd>
            <dt>Charges</dt>
            <dd className="muted">{formatRupees(trade.total_charges)}</dd>
            <dt>When</dt>
            <dd className="muted">{formatDateTime(trade.created_at)}</dd>
          </dl>
        </>
      )}
    </section>
  );
}

/**
 * Aggregate performance.
 *
 * Wins and losses count *closing* fills only -- an opening fill realizes
 * nothing -- and are judged on **net** P&L, so a trade that looked profitable
 * before charges but lost after them is counted as the loss it was.
 */
export function PerformancePage() {
  const [summary, setSummary] = useState<Performance | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchPerformance()
      .then(setSummary)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Failed to load performance.'),
      )
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const winRate = toNumber(summary?.win_rate ?? null);

  return (
    <PageShell
      title="Performance Summary"
      subtitle="Wins and losses count closing fills only, judged after charges"
      loading={loading}
      error={error}
      onRetry={load}
      actions={
        <button type="button" className="chip" onClick={load}>
          Refresh
        </button>
      }
    >
      {summary && (
        <>
          <div className="stat-grid">
            <Stat
              label="Total trades"
              value={formatQuantity(summary.total_trades)}
              hint="Every fill, opening and closing"
            />
            <Stat
              label="Closing trades"
              value={formatQuantity(summary.closing_trades)}
              hint="Only these realize P&L"
            />
            <Stat
              label="Winning trades"
              value={formatQuantity(summary.winning_trades)}
              tone="positive"
            />
            <Stat
              label="Losing trades"
              value={formatQuantity(summary.losing_trades)}
              tone="negative"
            />
            <Stat
              label="Win rate"
              value={winRate === null ? '\u2014' : `${winRate.toFixed(2)}%`}
              tone={
                winRate === null ? '' : winRate >= 50 ? 'positive' : 'negative'
              }
            />
            <Stat
              label="Profit factor"
              value={summary.profit_factor ?? '\u2014'}
              hint="Gross profit divided by gross loss"
            />
          </div>

          <div className="stat-grid stat-grid--pnl">
            <Stat
              label="Total gross P&L"
              value={formatRupees(summary.total_gross_pnl, { sign: true })}
              tone={signClass(summary.total_gross_pnl)}
            />
            <Stat
              label="Total charges"
              value={formatRupees(summary.total_charges)}
              tone="muted"
              hint="Includes charges on opening fills"
            />
            <Stat
              label="Total net P&L"
              value={formatRupees(summary.total_net_pnl, { sign: true })}
              tone={signClass(summary.total_net_pnl)}
            />
          </div>

          <div className="stat-grid">
            <Stat
              label="Average win"
              value={formatRupees(summary.average_win, { sign: true })}
              tone="positive"
            />
            <Stat
              label="Average loss"
              value={formatRupees(summary.average_loss, { sign: true })}
              tone="negative"
            />
            <Stat
              label="Break-even"
              value={formatQuantity(summary.breakeven_trades)}
            />
            <Stat label="Orders placed" value={formatQuantity(summary.total_orders)} />
            <Stat label="Filled" value={formatQuantity(summary.filled_orders)} />
            <Stat
              label="Rejected"
              value={formatQuantity(summary.rejected_orders)}
              tone={summary.rejected_orders > 0 ? 'negative' : ''}
            />
          </div>

          <div className="extremes">
            <ExtremeCard
              title="Largest winning trade"
              trade={summary.largest_winning_trade}
              tone="positive"
            />
            <ExtremeCard
              title="Largest losing trade"
              trade={summary.largest_losing_trade}
              tone="negative"
            />
          </div>
        </>
      )}
    </PageShell>
  );
}

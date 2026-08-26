import { DEFAULT_EXCHANGE, DEFAULT_SYMBOL } from '@/config/instrument';
import { formatPercent, formatRupees, signClass } from '@/utils/format';
import type { ConnectionState, PriceTick, StreamStatus } from '@/types/stream';

const CONNECTION_LABELS: Record<ConnectionState, string> = {
  connecting: 'Connecting',
  live: 'Live',
  reconnecting: 'Reconnecting',
  offline: 'Offline',
};

interface Props {
  tick: PriceTick | null;
  status: StreamStatus | null;
  connection: ConnectionState;
  attempt: number;
  isStale: boolean;
  onReconnect: () => void;
}

/**
 * The instrument banner: symbol, exchange, live price and change.
 *
 * Also carries the provenance badges. A simulated feed, a delayed one or a
 * stale one is called out here rather than left for the user to infer.
 */
export function TerminalHeader({
  tick,
  status,
  connection,
  attempt,
  isStale,
  onReconnect,
}: Props) {
  const change = tick?.change ?? null;
  const tone = signClass(change);

  return (
    <header className="terminal__header">
      <div className="instrument">
        <div className="instrument__id">
          <span className="instrument__symbol">{tick?.symbol ?? DEFAULT_SYMBOL}</span>
          <span className="instrument__exchange">{tick?.exchange ?? DEFAULT_EXCHANGE}</span>
        </div>

        <div className="instrument__price">
          <span className={`instrument__last ${tone}`}>
            {formatRupees(tick?.last_price)}
          </span>
          {change !== null && (
            <span className={`instrument__change ${tone}`}>
              {formatRupees(change, { sign: true })}
              {tick?.change_percent && ` (${formatPercent(tick.change_percent)})`}
            </span>
          )}
        </div>
      </div>

      <div className="instrument__meta">
        {tick?.is_mock && (
          <span className="badge badge--error" title="Prices are simulated">
            SIMULATED
          </span>
        )}
        {tick?.is_delayed && <span className="badge badge--degraded">DELAYED</span>}
        {isStale && connection === 'live' && (
          <span className="badge badge--degraded" title="No recent update">
            STALE
          </span>
        )}

        {status && (
          <span className="muted instrument__source">
            {status.provider} ·{' '}
            {status.mode === 'push'
              ? 'push'
              : `polled ${status.poll_interval_seconds}s`}
          </span>
        )}

        <button
          type="button"
          className={`badge badge--conn badge--${connection}`}
          onClick={onReconnect}
          title="Reconnect now"
        >
          <i className="dot" />
          {CONNECTION_LABELS[connection]}
          {connection === 'reconnecting' && attempt > 0 ? ` (${attempt})` : ''}
        </button>
      </div>
    </header>
  );
}

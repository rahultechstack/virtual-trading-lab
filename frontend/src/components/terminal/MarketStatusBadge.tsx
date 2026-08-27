import { useEffect, useState } from 'react';

import { fetchMarketStatus } from '@/api/markets';
import {
  STATUS_LABELS,
  STATUS_TONE,
  type MarketStatus,
} from '@/types/markets';
import type { StreamSubscription } from '@/types/stream';
import { formatTime } from '@/utils/format';

/**
 * How often to re-ask the backend whether the market is open.
 *
 * A session boundary is a minute-scale event, so a minute is ample. The
 * WebSocket subscription frame already refreshes this instantly on a switch.
 */
const REFRESH_MS = 60_000;

interface Props {
  symbol: string;
  /** The socket's subscription frame, which carries a fresher status. */
  subscription: StreamSubscription | null;
}

/**
 * Whether the selected instrument's market is open.
 *
 * The answer is always the **backend's** — this component never computes a
 * trading schedule, checks a weekday or compares a clock. It renders what
 * `GET /markets/status` returns, refreshed by the subscription frame the
 * WebSocket sends on every instrument switch.
 *
 * For crypto it reads a permanent "Open · 24/7", because that is what the
 * crypto calendar genuinely reports: no next open, no next close.
 */
export function MarketStatusBadge({ symbol, subscription }: Props) {
  const [status, setStatus] = useState<MarketStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const load = () => {
      fetchMarketStatus(symbol, controller.signal)
        .then((next) => {
          if (!cancelled) setStatus(next);
        })
        .catch(() => {
          // A badge is not worth surfacing an error banner for.
        });
    };

    load();
    const timer = window.setInterval(load, REFRESH_MS);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [symbol]);

  // The subscription frame is the freshest word on the instrument currently
  // streaming, so prefer it while it matches what we are showing.
  const live =
    subscription?.symbol === symbol && subscription.market_status
      ? {
          status: subscription.market_status,
          isOpen: subscription.market_open ?? false,
          nextOpen: subscription.next_open ?? null,
          nextClose: subscription.next_close ?? null,
        }
      : status
        ? {
            status: status.status,
            isOpen: status.is_open,
            nextOpen: status.next_open,
            nextClose: status.next_close,
          }
        : null;

  if (live === null) return null;

  const tone = STATUS_TONE[live.status];
  const is24x7 = live.isOpen && live.nextOpen === null && live.nextClose === null;

  // A 24/7 market has no boundary to announce; an open one closes next, a
  // closed one opens next.
  const detail = is24x7
    ? '24/7'
    : live.isOpen
      ? live.nextClose
        ? `closes ${formatTime(live.nextClose)}`
        : null
      : live.nextOpen
        ? `opens ${formatTime(live.nextOpen)}`
        : null;

  return (
    <span
      className={`market-status market-status--${tone}`}
      title={status?.reason ?? undefined}
    >
      <i className="market-status__dot" aria-hidden="true" />
      <span className="market-status__label">{STATUS_LABELS[live.status]}</span>
      {detail && <span className="market-status__detail muted">{detail}</span>}
      {status && !status.enforced && !live.isOpen && (
        // Being closed does not block a paper order. Saying so prevents the
        // badge reading as "you cannot trade".
        <span className="market-status__detail muted">· trading allowed</span>
      )}
    </span>
  );
}

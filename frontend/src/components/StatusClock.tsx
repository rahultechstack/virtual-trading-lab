import { useEffect, useState } from 'react';

import type { PriceTick } from '@/types/stream';
import { formatClockDate, formatClockTime } from '@/utils/format';

interface Props {
  /** Latest tick, used for the "last price update" line. */
  tick: PriceTick | null;
}

/**
 * Fixed bottom-right status clock.
 *
 * Two lines: the wall clock, and when the backend last fetched a price.
 * Both are rendered in exchange-local time (IST), matching the chart axis, so
 * every time shown anywhere in the app refers to the same zone.
 *
 * `tick.server_time` is when the *backend* built the tick — i.e. the moment it
 * actually pulled from the provider. That is the honest "last fetch" figure;
 * `tick.timestamp` is the exchange's own stamp and runs ~13s behind it.
 */
export function StatusClock({ tick }: Props) {
  const [now, setNow] = useState<Date>(() => new Date());

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const fetchedAt = tick?.server_time ? new Date(tick.server_time) : null;
  const valid = fetchedAt !== null && !Number.isNaN(fetchedAt.getTime());
  const ageSeconds = valid
    ? Math.max(0, Math.round((now.getTime() - fetchedAt.getTime()) / 1000))
    : null;

  return (
    <aside className="status-clock" aria-live="off">
      <div className="status-clock__now">
        <span className="status-clock__date">{formatClockDate(now)}</span>
        <span className="status-clock__time">{formatClockTime(now)}</span>
      </div>

      <div className="status-clock__update">
        <span className="status-clock__label">Last price update</span>
        {valid ? (
          <>
            <span className="status-clock__stamp">{formatClockTime(fetchedAt)}</span>
            {ageSeconds !== null && (
              <span className="status-clock__age">{ageSeconds}s ago</span>
            )}
          </>
        ) : (
          <span className="status-clock__stamp muted">waiting…</span>
        )}
      </div>
    </aside>
  );
}

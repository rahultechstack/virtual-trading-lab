import { useEffect, useState } from 'react';

import type { PriceTick } from '@/types/stream';
import { formatClockDate, formatClockTime } from '@/utils/format';

interface Props {
  /** Latest tick, used for the "updated" stamp. */
  tick: PriceTick | null;
}

/**
 * Compact date/time readout for the chart footer.
 *
 * Rendered in exchange-local time (IST), matching the chart axis, so every
 * time shown in the app refers to the same zone.
 *
 * `tick.server_time` is when the *backend* built the tick — the moment it
 * actually pulled from the provider. That is the honest "last fetch" figure;
 * `tick.timestamp` is the exchange's own stamp and runs behind it.
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
    <span className="status-clock">
      <span className="status-clock__date">{formatClockDate(now)}</span>
      <span className="status-clock__time">{formatClockTime(now)}</span>

      <span className="status-clock__sep">·</span>

      <span className="status-clock__label">updated</span>
      {valid ? (
        <>
          <span className="status-clock__stamp">{formatClockTime(fetchedAt)}</span>
          {ageSeconds !== null && (
            <span className="status-clock__age">({ageSeconds}s ago)</span>
          )}
        </>
      ) : (
        <span className="status-clock__stamp">waiting…</span>
      )}
    </span>
  );
}

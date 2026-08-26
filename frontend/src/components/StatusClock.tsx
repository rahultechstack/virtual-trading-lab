import { useEffect, useState } from 'react';

import type { PriceTick } from '@/types/stream';
import { formatClockDate, formatClockTime } from '@/utils/format';

/** A feed older than this is amber rather than green. */
const STALE_AFTER_SECONDS = 15;

interface Props {
  /** Latest tick, used for the "updated" stamp. */
  tick: PriceTick | null;
}

/**
 * Date/time readout for the right of the chart footer.
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
  const isStale = ageSeconds !== null && ageSeconds > STALE_AFTER_SECONDS;

  const dotClass = !valid
    ? 'status-clock__dot status-clock__dot--idle'
    : isStale
      ? 'status-clock__dot status-clock__dot--stale'
      : 'status-clock__dot status-clock__dot--live';

  return (
    <div className="status-clock" title="Exchange local time (IST)">
      <div className="status-clock__block">
        <span className="status-clock__date">{formatClockDate(now)}</span>
        <span className="status-clock__time">{formatClockTime(now)}</span>
      </div>

      <span className="status-clock__divider" aria-hidden="true" />

      <div className="status-clock__block status-clock__block--update">
        <span className="status-clock__label">
          <i className={dotClass} aria-hidden="true" />
          Last update
        </span>
        {valid ? (
          <span className="status-clock__stamp">
            {formatClockTime(fetchedAt)}
            {ageSeconds !== null && (
              <em className="status-clock__age">{ageSeconds}s</em>
            )}
          </span>
        ) : (
          <span className="status-clock__stamp status-clock__stamp--idle">
            waiting…
          </span>
        )}
      </div>
    </div>
  );
}

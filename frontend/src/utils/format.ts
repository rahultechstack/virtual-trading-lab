/**
 * Display formatting.
 *
 * Monetary values arrive from the API as strings carrying Decimal precision.
 * These helpers convert to a number **only at the moment of rendering** -- no
 * arithmetic is ever done on the result, so no precision is lost anywhere it
 * matters.
 */

import { CHART_TIME_ZONE as EXCHANGE_TIME_ZONE } from '@/config/chart';

const EM_DASH = '\u2014';

export function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const numeric = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

/** Rupees with two decimals and Indian digit grouping. */
export function formatMoney(
  value: string | number | null | undefined,
  options: { sign?: boolean } = {},
): string {
  const numeric = toNumber(value);
  if (numeric === null) return EM_DASH;

  const formatted = Math.abs(numeric).toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  if (numeric < 0) return `-${formatted}`;
  return options.sign && numeric > 0 ? `+${formatted}` : formatted;
}

/** Money prefixed with the rupee sign. */
export function formatRupees(
  value: string | number | null | undefined,
  options: { sign?: boolean } = {},
): string {
  const numeric = toNumber(value);
  if (numeric === null) return EM_DASH;
  const body = formatMoney(value, options);
  return body.startsWith('-') ? `-\u20b9${body.slice(1)}` : `\u20b9${body}`;
}

/**
 * Read a quantity for a comparison or a display.
 *
 * Quantities arrive as Decimal strings because crypto sizes are fractional to
 * eight places. Parsing to a number here is safe for what the UI does with it
 * -- testing a sign, comparing against a held size, rendering -- but the
 * string is what gets sent back to the backend, so the ledger never sees a
 * binary float.
 */
export function toQuantity(value: string | number | null | undefined): number {
  return toNumber(value) ?? 0;
}

/**
 * Format a quantity, keeping only the decimals it actually has.
 *
 * 100 renders as "100", not "100.00000000"; 0.001 BTC renders as "0.001". A
 * whole crypto size therefore reads as cleanly as a share count does.
 */
export function formatQuantity(
  value: string | number | null | undefined,
  options: { precision?: number } = {},
): string {
  const numeric = toNumber(value);
  if (numeric === null) return EM_DASH;

  // Trailing zeros carry no information here and make a size hard to read.
  const decimals = decimalsIn(value, options.precision ?? 8);
  return numeric.toLocaleString('en-IN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: decimals,
  });
}

/** How many decimal places a value actually uses, capped at `max`. */
function decimalsIn(value: string | number | null | undefined, max: number): number {
  const text = typeof value === 'string' ? value : String(value ?? '');
  const fraction = text.split('.')[1] ?? '';
  const significant = fraction.replace(/0+$/, '').length;
  return Math.min(significant, max);
}

export function formatPercent(value: string | number | null | undefined): string {
  const numeric = toNumber(value);
  if (numeric === null) return EM_DASH;
  const sign = numeric > 0 ? '+' : '';
  return `${sign}${numeric.toFixed(2)}%`;
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return EM_DASH;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return EM_DASH;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Exchange timezone. NSE and BSE sessions are defined in IST, and the backend
 * already anchors intraday VWAP to this same zone
 * (`app/indicators/library.py:SESSION_TIMEZONE`).
 */

/**
 * Chart axis label for an epoch-seconds timestamp, in exchange-local time.
 *
 * Lightweight Charts renders `UTCTimestamp` values in **UTC** unless a
 * formatter is supplied, which made a 12:42 IST bar read as 07:12 on the axis.
 * The timestamps themselves are correct and stay untouched — only the label is
 * converted, so crosshair readouts, tooltips and the data all stay in step.
 */
export function formatChartTick(
  epochSeconds: number,
  kind: 'date' | 'time',
): string {
  const date = new Date(epochSeconds * 1000);
  if (kind === 'date') {
    return date.toLocaleDateString('en-IN', {
      timeZone: EXCHANGE_TIME_ZONE,
      day: '2-digit',
      month: 'short',
    });
  }
  return date.toLocaleTimeString('en-IN', {
    timeZone: EXCHANGE_TIME_ZONE,
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/** Full crosshair readout for an epoch-seconds timestamp, in exchange-local time. */
export function formatChartTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleString('en-IN', {
    timeZone: EXCHANGE_TIME_ZONE,
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/** Date as `dd/mm/yyyy`, in exchange-local time. */
export function formatClockDate(date: Date): string {
  return date.toLocaleDateString('en-GB', {
    timeZone: EXCHANGE_TIME_ZONE,
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });
}

/** Time as `hh:mm:ss AM/PM`, in exchange-local time. */
export function formatClockTime(date: Date): string {
  return date.toLocaleTimeString('en-US', {
    timeZone: EXCHANGE_TIME_ZONE,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  });
}

/** `positive` / `negative` / `flat`, for colouring a P&L figure. */
export function signClass(value: string | number | null | undefined): string {
  const numeric = toNumber(value);
  if (numeric === null || numeric === 0) return 'flat';
  return numeric > 0 ? 'positive' : 'negative';
}

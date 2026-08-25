/**
 * Display formatting.
 *
 * Monetary values arrive from the API as strings carrying Decimal precision.
 * These helpers convert to a number **only at the moment of rendering** -- no
 * arithmetic is ever done on the result, so no precision is lost anywhere it
 * matters.
 */

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

export function formatQuantity(value: number | null | undefined): string {
  if (value === null || value === undefined) return EM_DASH;
  return value.toLocaleString('en-IN');
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

/** `positive` / `negative` / `flat`, for colouring a P&L figure. */
export function signClass(value: string | number | null | undefined): string {
  const numeric = toNumber(value);
  if (numeric === null || numeric === 0) return 'flat';
  return numeric > 0 ? 'positive' : 'negative';
}

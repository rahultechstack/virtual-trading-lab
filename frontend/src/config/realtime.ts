/**
 * **LIVE-STREAM BEHAVIOUR.**
 *
 * How the browser's WebSocket client behaves — reconnection, heartbeat and
 * when a price is treated as stale. These are *client* concerns; how often the
 * backend polls its upstream provider is `STREAM_POLL_INTERVAL_SECONDS` in
 * `backend/.env`.
 */

/** First reconnect delay after a drop. Doubles on each failed attempt. */
export const INITIAL_BACKOFF_MS = 1_000;

/** Ceiling for the reconnect delay, so a long outage retries steadily. */
export const MAX_BACKOFF_MS = 15_000;

/**
 * Heartbeat interval.
 *
 * Keep this comfortably below any proxy's idle timeout (60s is a common
 * default) or the socket will be closed under you between ticks.
 */
export const PING_INTERVAL_MS = 25_000;

/**
 * How long without a tick before the UI marks the price stale.
 *
 * Should be a few multiples of the backend's poll interval — otherwise a
 * normal gap between polls reads as a fault.
 */
export const STALE_AFTER_MS = 30_000;

/** The same threshold for the status clock, which counts in seconds. */
export const CLOCK_STALE_AFTER_SECONDS = 15;

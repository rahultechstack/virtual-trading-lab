/**
 * **ALL FRONTEND CONFIGURATION.**
 *
 * Four files, by what they govern:
 *
 *   api.ts        backend origin, API prefix, WebSocket URL
 *   realtime.ts   reconnect, heartbeat, staleness
 *   ui.ts         page sizes, refresh cadence, quantity presets
 *   chart.ts      chart palette and time zone
 *   instrument.ts which instrument the UI opens on
 *
 * Import from the specific module (`@/config/api`) in application code — this
 * barrel exists so `CONFIGURATION.md` can point at one place.
 */

export * from './api';
export * from './chart';
export * from './instrument';
export * from './realtime';
export * from './ui';

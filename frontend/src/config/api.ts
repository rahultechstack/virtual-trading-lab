/**
 * **BACKEND CONNECTION.**
 *
 * =========================================================================
 *  THIS IS THE ONE FILE TO EDIT TO POINT THE UI AT A DIFFERENT BACKEND.
 *
 *  Prefer setting these in `frontend/.env` rather than editing the
 *  defaults below, so a deployment needs no code change:
 *
 *    VITE_API_BASE_URL=https://api.example.com
 *    VITE_API_V1_PREFIX=/api/v1
 *    VITE_WS_BASE_URL=wss://api.example.com     # only if the socket differs
 * =========================================================================
 *
 * Vite inlines `import.meta.env.*` at BUILD time, not at runtime, so a
 * production image must be rebuilt after changing these — restarting it is
 * not enough.
 */

/** Origin the backend is served from. No trailing slash. */
export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

/** Path prefix every versioned endpoint sits under. */
export const API_V1_PREFIX: string =
  import.meta.env.VITE_API_V1_PREFIX ?? '/api/v1';

/**
 * Origin the WebSocket is served from.
 *
 * Derived from the HTTP base by swapping the scheme (`https` -> `wss`), so
 * there is normally one thing to configure. `VITE_WS_BASE_URL` overrides it
 * when the socket is served from somewhere else entirely — behind a separate
 * proxy, say.
 */
export const WS_BASE_URL: string =
  import.meta.env.VITE_WS_BASE_URL && import.meta.env.VITE_WS_BASE_URL.length > 0
    ? import.meta.env.VITE_WS_BASE_URL
    : API_BASE_URL.replace(/^http/, 'ws');

/** Absolute URL for an API path, e.g. `/trading/orders`. */
export function apiUrl(path: string): string {
  return `${API_BASE_URL}${API_V1_PREFIX}${path}`;
}

/** Absolute URL for a WebSocket path, e.g. `/stream/prices`. */
export function wsUrl(path: string): string {
  return `${WS_BASE_URL}${API_V1_PREFIX}${path}`;
}

/** The live-price socket. The only WebSocket this app opens. */
export const STREAM_PATH = '/stream/prices';

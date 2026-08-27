/// <reference types="vite/client" />

/**
 * Environment variables this app reads.
 *
 * Declared here so a typo is a compile error rather than a silent `undefined`.
 * Every one is consumed in `src/config/` and nowhere else — see
 * `CONFIGURATION.md`.
 */
interface ImportMetaEnv {
  /** Backend origin, e.g. `http://localhost:8000`. See `config/api.ts`. */
  readonly VITE_API_BASE_URL?: string;
  /** Versioned path prefix, e.g. `/api/v1`. See `config/api.ts`. */
  readonly VITE_API_V1_PREFIX?: string;
  /** WebSocket origin. Blank derives it from the API base. See `config/api.ts`. */
  readonly VITE_WS_BASE_URL?: string;
  /** Ticker this UI labels itself with. See `config/instrument.ts`. */
  readonly VITE_TRADING_SYMBOL?: string;
  /** Exchange code this UI labels itself with. See `config/instrument.ts`. */
  readonly VITE_TRADING_EXCHANGE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

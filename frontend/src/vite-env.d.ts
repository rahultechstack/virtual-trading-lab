/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_API_V1_PREFIX: string;
  readonly VITE_WS_BASE_URL?: string;
  /** Ticker this UI labels itself with. See src/config/instrument.ts. */
  readonly VITE_TRADING_SYMBOL?: string;
  /** Exchange code this UI labels itself with. */
  readonly VITE_TRADING_EXCHANGE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

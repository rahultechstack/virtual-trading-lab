import { useCallback, useEffect, useState } from 'react';

import { AutomaticOrderPanel } from './AutomaticOrderPanel';
import { MarketStatusBadge } from './MarketStatusBadge';
import { StockSelector } from './StockSelector';
import { OrdersPanel } from './OrdersPanel';
import { PositionPanel } from './PositionPanel';
import { PriceChart } from './PriceChart';
import { TerminalHeader } from './TerminalHeader';
import { TradeHistory } from './TradeHistory';
import { TradingPanel } from './TradingPanel';
import { WalletPanel } from './WalletPanel';
import { fetchInstrument } from '@/api/instruments';
import { DEFAULT_EXCHANGE, DEFAULT_SYMBOL } from '@/config/instrument';
import type { Instrument } from '@/types/instruments';
import { useAccount } from '@/hooks/useAccount';
import { useLivePrice } from '@/hooks/useLivePrice';

type Tab = 'orders' | 'trades';

/**
 * A provisional instrument for the very first render.
 *
 * The real record — asset class, step size, trading hours — is fetched from
 * `GET /instruments/{symbol}` immediately. Guessing STOCK here is safe because
 * the default instrument is configured server-side and is an equity; every
 * field that matters is replaced before the user can act on it.
 */
const PROVISIONAL: Instrument = {
  symbol: DEFAULT_SYMBOL,
  company_name: '',
  asset_class: 'STOCK',
  exchange: DEFAULT_EXCHANGE,
  market: '',
  trading_hours: '',
  instrument_type: 'EQUITY',
  quantity_step: '1',
  is_fractional: false,
  quantity_precision: 0,
  data_available: null,
};

/**
 * The trading terminal.
 *
 * Two data paths, deliberately separate:
 *
 * * **WebSocket** carries the live price -- one stream, no polling.
 * * **REST** carries commands and account state, refetched after an order
 *   fills so every panel updates from one consistent set of reads.
 *
 * The selected instrument drives everything downstream: which feed prices it,
 * what sizes are legal, which charges apply and when its market is open. None
 * of that is decided here -- it comes from the backend on the instrument
 * record and the market-status endpoint.
 */
export function Terminal() {
  // The instrument being viewed and traded. Switching it does NOT reload the
  // app: every panel refetches for the new symbol, and the WebSocket
  // re-subscribes on the same connection.
  const [instrument, setInstrument] = useState<Instrument>(PROVISIONAL);
  const symbol = instrument.symbol;

  // Replace the provisional record with the real one, and confirm the feed can
  // actually serve it. Runs on first load and after any switch that handed us
  // a record from the picker (harmless: the response is authoritative either
  // way, and the probe is cached server-side).
  useEffect(() => {
    const controller = new AbortController();
    fetchInstrument(symbol, controller.signal)
      .then((full) => setInstrument((current) =>
        current.symbol === full.symbol ? full : current,
      ))
      .catch(() => {
        // A failed lookup leaves the current record in place; the panels
        // surface their own errors rather than blanking the terminal.
      });
    return () => controller.abort();
  }, [symbol]);

  const {
    tick,
    subscription,
    automaticOrderEvent,
    status,
    connection,
    attempt,
    isStale,
    reconnect,
  } = useLivePrice(symbol);
  const markPrice = tick?.last_price ?? null;

  const {
    wallet,
    position,
    portfolio,
    orders,
    trades,
    loading,
    error,
    needsWallet,
    refresh,
    createWallet,
  } = useAccount(markPrice, symbol);

  const [tab, setTab] = useState<Tab>('orders');
  // Bumped whenever the automatic-order list needs reloading.
  const [automationToken, setAutomationToken] = useState(0);

  // A fill changes the wallet, the position and both histories at once, so
  // everything is reloaded together rather than patched piecemeal.
  const handleFilled = useCallback(() => {
    void refresh();
    // A manual fill can retire or clamp a stop-loss server-side, so the
    // trigger list is reloaded alongside the account panels.
    setAutomationToken((token) => token + 1);
  }, [refresh]);

  // A trigger fired on the backend: position, wallet, P&L and both histories
  // have all moved. Reload everything -- no page refresh needed.
  useEffect(() => {
    if (automaticOrderEvent === null) return;
    void refresh();
    setAutomationToken((token) => token + 1);
  }, [automaticOrderEvent, refresh]);

  return (
    <div className="terminal">
      <div className="terminal__instrument">
        <StockSelector selected={instrument} onSelect={setInstrument} />
        <MarketStatusBadge symbol={symbol} subscription={subscription} />
      </div>

      <TerminalHeader
        tick={tick}
        status={status}
        connection={connection}
        attempt={attempt}
        isStale={isStale}
        onReconnect={reconnect}
      />

      {tick?.is_mock && (
        <p className="banner banner--warning">
          Simulated market data — generated by a random walk, with no
          relationship to the real market.
        </p>
      )}

      {error && (
        <p className="banner banner--error">
          {error}{' '}
          <button type="button" className="link" onClick={() => void refresh()}>
            Retry
          </button>
        </p>
      )}

      <div className="terminal__body">
        <div className="terminal__main">
          <PriceChart
            symbol={symbol}
            exchange={instrument.exchange}
            tick={tick}
          />

          <PositionPanel
            position={position}
            portfolio={portfolio}
            currentPrice={markPrice}
          />

          <section className="panel">
            <header className="panel__header">
              <div className="tabs" role="tablist">
                <button
                  type="button"
                  role="tab"
                  aria-selected={tab === 'orders'}
                  className={`tab ${tab === 'orders' ? 'tab--active' : ''}`}
                  onClick={() => setTab('orders')}
                >
                  Orders{orders.length > 0 ? ` (${orders.length})` : ''}
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={tab === 'trades'}
                  className={`tab ${tab === 'trades' ? 'tab--active' : ''}`}
                  onClick={() => setTab('trades')}
                >
                  Trades{trades.length > 0 ? ` (${trades.length})` : ''}
                </button>
              </div>

              <button
                type="button"
                className="chip"
                onClick={() => void refresh()}
                disabled={loading}
              >
                {loading ? 'Loading…' : 'Refresh'}
              </button>
            </header>

            {tab === 'orders' ? (
              <OrdersPanel orders={orders} />
            ) : (
              <TradeHistory trades={trades} />
            )}
          </section>
        </div>

        <aside className="terminal__side">
          <TradingPanel
            instrument={instrument}
            referencePrice={markPrice}
            position={position}
            disabled={needsWallet}
            onFilled={handleFilled}
          />

          <AutomaticOrderPanel
            instrument={instrument}
            position={position}
            referencePrice={markPrice}
            disabled={needsWallet}
            refreshToken={automationToken}
            onChanged={() => setAutomationToken((token) => token + 1)}
          />

          <WalletPanel
            wallet={wallet}
            portfolio={portfolio}
            needsWallet={needsWallet}
            onCreateWallet={() => void createWallet()}
          />
        </aside>
      </div>

      <footer className="terminal__footer muted">
        Paper trading only · virtual money · no orders reach any exchange
      </footer>
    </div>
  );
}

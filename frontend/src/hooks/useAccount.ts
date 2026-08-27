import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError } from '@/api/client';
import {
  fetchOrders,
  fetchPortfolio,
  fetchPosition,
  fetchTrades,
} from '@/api/trading';
import { fetchWallet, initializeWallet } from '@/api/wallet';
import type { Order, Portfolio, Position, Trade, Wallet } from '@/types/trading';

/**
 * Portfolio revaluation is throttled rather than fired on every tick.
 *
 * Unrealized P&L is computed server-side in Decimal, so it needs a round trip
 * per mark price. Recomputing it in JavaScript floats would be cheaper but
 * would reintroduce exactly the imprecision the backend schema exists to
 * avoid, so the trade is a small delay instead.
 */
const REVALUE_THROTTLE_MS = 3_000;

const HISTORY_LIMIT = 25;

interface AccountState {
  wallet: Wallet | null;
  position: Position | null;
  portfolio: Portfolio | null;
  orders: Order[];
  trades: Trade[];
  loading: boolean;
  error: string | null;
  /** True when the wallet has never been initialised. */
  needsWallet: boolean;
  /** Refetch everything. Call after an order fills. */
  refresh: () => Promise<void>;
  /** Create the wallet, then load the account. */
  createWallet: () => Promise<void>;
}

/**
 * Loads and keeps the account panels in sync.
 *
 * One hook owns wallet, position, portfolio, orders and trades so that a
 * single `refresh()` after an order updates every panel from one consistent
 * set of reads, rather than each panel polling on its own schedule.
 */
export function useAccount(
  markPrice: string | null,
  symbol?: string | null,
): AccountState {
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [position, setPosition] = useState<Position | null>(null);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [needsWallet, setNeedsWallet] = useState(false);

  const activeRef = useRef(true);
  const markPriceRef = useRef<string | null>(markPrice);
  const symbolRef = useRef<string | null>(symbol ?? null);
  const lastRevaluedAtRef = useRef(0);

  markPriceRef.current = markPrice;
  symbolRef.current = symbol ?? null;

  const refresh = useCallback(async () => {
    try {
      const mark = markPriceRef.current;
      const instrument = symbolRef.current;
      const [walletResult, positionResult, portfolioResult, orderResult, tradeResult] =
        await Promise.all([
          fetchWallet().catch((err: unknown) => {
            // A missing wallet is an expected first-run state, not a failure.
            if (err instanceof ApiError && err.isNotFound) return null;
            throw err;
          }),
          fetchPosition(instrument),
          fetchPortfolio(mark, instrument).catch((err: unknown) => {
            if (err instanceof ApiError && err.isNotFound) return null;
            throw err;
          }),
          fetchOrders(HISTORY_LIMIT),
          fetchTrades(HISTORY_LIMIT),
        ]);

      if (!activeRef.current) return;

      setWallet(walletResult);
      setNeedsWallet(walletResult === null);
      setPosition(positionResult);
      setPortfolio(portfolioResult);
      setOrders(orderResult);
      setTrades(tradeResult);
      setError(null);
      lastRevaluedAtRef.current = Date.now();
    } catch (err: unknown) {
      if (!activeRef.current) return;
      setError(err instanceof Error ? err.message : 'Could not load the account.');
    } finally {
      if (activeRef.current) setLoading(false);
    }
  }, []);

  const createWallet = useCallback(async () => {
    setError(null);
    try {
      await initializeWallet();
      await refresh();
    } catch (err: unknown) {
      if (!activeRef.current) return;
      setError(err instanceof Error ? err.message : 'Could not create the wallet.');
    }
  }, [refresh]);

  useEffect(() => {
    activeRef.current = true;
    void refresh();
    return () => {
      activeRef.current = false;
    };
  }, [refresh]);

  // Switching instruments reloads position and portfolio for the new one.
  // Orders, trades and the wallet are account-wide and come back too, from
  // the same consistent set of reads.
  useEffect(() => {
    setLoading(true);
    void refresh();
  }, [symbol, refresh]);

  // Revalue the open position as the price moves, at most once per throttle
  // window so a fast feed does not hammer the API.
  useEffect(() => {
    if (!markPrice || needsWallet) return;
    if (Date.now() - lastRevaluedAtRef.current < REVALUE_THROTTLE_MS) return;

    let cancelled = false;
    lastRevaluedAtRef.current = Date.now();

    fetchPortfolio(markPrice, symbolRef.current)
      .then((result) => {
        if (!cancelled && activeRef.current) setPortfolio(result);
      })
      .catch(() => {
        // A failed revaluation is not worth surfacing; the next tick retries.
      });

    return () => {
      cancelled = true;
    };
  }, [markPrice, needsWallet]);

  return {
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
  };
}

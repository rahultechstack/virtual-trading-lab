import { useCallback, useEffect, useRef, useState } from 'react';

import { wsUrl } from '@/api/client';
import type {
  AutomaticOrderEvent,
  ConnectionState,
  PriceTick,
  StreamError,
  StreamMessage,
  StreamStatus,
  StreamSubscription,
} from '@/types/stream';

/** Reconnect backoff: doubles from 1s, capped, with jitter. */
const INITIAL_BACKOFF_MS = 1_000;
const MAX_BACKOFF_MS = 15_000;

/** Client heartbeat, so idle proxies do not silently drop the socket. */
const PING_INTERVAL_MS = 25_000;

/** A tick older than this is shown as stale rather than as current. */
const STALE_AFTER_MS = 30_000;

interface UseLivePriceResult {
  tick: PriceTick | null;
  /**
   * Most recent automatic-order event pushed by the backend monitor.
   * The backend decides whether a trigger fires; this is purely the
   * notification that it did.
   */
  automaticOrderEvent: AutomaticOrderEvent | null;
  status: StreamStatus | null;
  error: StreamError | null;
  connection: ConnectionState;
  /** How many consecutive reconnect attempts have been made. */
  attempt: number;
  /** True when the last tick is older than the staleness threshold. */
  isStale: boolean;
  /** Which instrument the server confirmed this socket is watching. */
  subscription: StreamSubscription | null;
  /** Force an immediate reconnect. */
  reconnect: () => void;
}

/**
 * Subscribes to the backend price stream over a WebSocket.
 *
 * Reconnection is handled here rather than on the server: the socket is
 * redialled with exponential backoff plus jitter, so a backend restart does
 * not require a page refresh and a fleet of clients does not stampede on
 * recovery.
 */
/**
 * @param symbol Instrument to watch. Changing it re-subscribes on the SAME
 *   socket -- no reconnect, no second connection. Passing null keeps the
 *   server's default instrument.
 */
export function useLivePrice(symbol?: string | null): UseLivePriceResult {
  const [tick, setTick] = useState<PriceTick | null>(null);
  const [automaticOrderEvent, setAutomaticOrderEvent] =
    useState<AutomaticOrderEvent | null>(null);
  const [subscription, setSubscription] = useState<StreamSubscription | null>(
    null,
  );
  const [status, setStatus] = useState<StreamStatus | null>(null);
  const [error, setError] = useState<StreamError | null>(null);
  const [connection, setConnection] = useState<ConnectionState>('connecting');
  const [attempt, setAttempt] = useState(0);
  const [isStale, setIsStale] = useState(false);

  const socketRef = useRef<WebSocket | null>(null);
  const retryTimerRef = useRef<number | null>(null);
  const pingTimerRef = useRef<number | null>(null);
  const backoffRef = useRef(INITIAL_BACKOFF_MS);
  const lastTickAtRef = useRef<number | null>(null);
  // Guards against a reconnect being scheduled after the hook unmounts.
  const activeRef = useRef(true);
  // Read inside socket callbacks, which must not be rebuilt on every
  // symbol change -- that would tear the connection down.
  const symbolRef = useRef<string | null>(symbol ?? null);
  symbolRef.current = symbol ?? null;

  const clearTimers = useCallback(() => {
    if (retryTimerRef.current !== null) {
      window.clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    if (pingTimerRef.current !== null) {
      window.clearInterval(pingTimerRef.current);
      pingTimerRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (!activeRef.current) return;

    // Drop any previous socket before dialling a new one, so a reconnect can
    // never leave two live sockets feeding the same state.
    if (socketRef.current) {
      socketRef.current.onclose = null;
      socketRef.current.close();
      socketRef.current = null;
    }

    let socket: WebSocket;
    try {
      socket = new WebSocket(wsUrl('/stream/prices'));
    } catch {
      setConnection('offline');
      return;
    }
    socketRef.current = socket;

    socket.onopen = () => {
      if (!activeRef.current) return;
      backoffRef.current = INITIAL_BACKOFF_MS;
      setAttempt(0);
      setConnection('live');
      setError(null);

      // Tell the server which instrument this client wants. The server
      // validates it and replies with a `subscription` frame.
      if (symbolRef.current) {
        socket.send(
          JSON.stringify({ type: 'subscribe', symbol: symbolRef.current }),
        );
      }

      pingTimerRef.current = window.setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'ping' }));
        }
      }, PING_INTERVAL_MS);
    };

    socket.onmessage = (event: MessageEvent<string>) => {
      if (!activeRef.current) return;

      let message: StreamMessage;
      try {
        message = JSON.parse(event.data) as StreamMessage;
      } catch {
        return; // Ignore anything that is not valid JSON.
      }

      switch (message.type) {
        case 'tick': {
          // Guard against a tick for the previous instrument arriving
          // in the gap between switching and the server acknowledging.
          const wanted = symbolRef.current;
          if (wanted && message.data.symbol !== wanted) break;
          setTick(message.data);
          setError(null);
          lastTickAtRef.current = Date.now();
          setIsStale(false);
          break;
        }
        case 'subscription':
          setSubscription(message.data);
          break;
        case 'status':
          setStatus(message.data);
          break;
        case 'error':
          setError(message.data);
          break;
        case 'automatic_order':
          setAutomaticOrderEvent(message.data);
          break;
        case 'pong':
          break;
      }
    };

    socket.onerror = () => {
      // `onclose` always follows, and carries the useful information.
    };

    socket.onclose = () => {
      if (!activeRef.current) return;
      clearTimers();
      socketRef.current = null;
      setConnection('reconnecting');

      // Jitter spreads reconnects out so many tabs do not all redial at once.
      const jitter = Math.random() * 0.3 + 0.85;
      const delay = Math.round(backoffRef.current * jitter);
      backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF_MS);

      setAttempt((previous) => previous + 1);
      retryTimerRef.current = window.setTimeout(connect, delay);
    };
  }, [clearTimers]);

  const reconnect = useCallback(() => {
    clearTimers();
    backoffRef.current = INITIAL_BACKOFF_MS;
    setConnection('connecting');
    connect();
  }, [clearTimers, connect]);

  useEffect(() => {
    activeRef.current = true;
    connect();

    return () => {
      activeRef.current = false;
      clearTimers();
      if (socketRef.current) {
        socketRef.current.onclose = null;
        socketRef.current.close();
        socketRef.current = null;
      }
    };
  }, [connect, clearTimers]);

  // Switching instruments re-subscribes on the open socket. Reconnecting
  // would drop and redial for no reason, and would race the backoff timer.
  useEffect(() => {
    const socket = socketRef.current;
    if (!symbol || !socket || socket.readyState !== WebSocket.OPEN) return;
    setTick(null);
    socket.send(JSON.stringify({ type: 'subscribe', symbol }));
  }, [symbol]);

  // Mark the price stale if nothing arrives for a while. The socket can stay
  // open while the upstream feed has quietly stopped producing.
  useEffect(() => {
    const timer = window.setInterval(() => {
      const last = lastTickAtRef.current;
      setIsStale(last !== null && Date.now() - last > STALE_AFTER_MS);
    }, 5_000);
    return () => window.clearInterval(timer);
  }, []);

  return {
    tick,
    automaticOrderEvent,
    subscription,
    status,
    error,
    connection,
    attempt,
    isStale,
    reconnect,
  };
}

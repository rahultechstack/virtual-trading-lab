import { useCallback, useEffect, useState } from 'react';

import { fetchHealth } from '@/api/health';
import type { HealthResponse } from '@/types/health';

export type RequestState = 'idle' | 'loading' | 'success' | 'error';

interface UseHealthResult {
  state: RequestState;
  data: HealthResponse | null;
  error: string | null;
  refresh: () => void;
}

/**
 * Fetches backend health on mount and on demand.
 * Deliberately dependency-free — a data-fetching library is introduced only
 * when the trading UI actually needs caching and invalidation.
 */
export function useHealth(): UseHealthResult {
  const [state, setState] = useState<RequestState>('idle');
  const [data, setData] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    setState('loading');
    setError(null);

    fetchHealth(controller.signal)
      .then((result) => {
        if (!active) return;
        setData(result);
        setState('success');
      })
      .catch((err: unknown) => {
        if (!active || controller.signal.aborted) return;
        setData(null);
        setError(err instanceof Error ? err.message : 'Unknown error.');
        setState('error');
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [nonce]);

  return { state, data, error, refresh };
}

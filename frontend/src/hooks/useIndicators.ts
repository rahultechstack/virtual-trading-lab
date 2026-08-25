import { useCallback, useEffect, useMemo, useState } from 'react';

import { fetchIndicators } from '@/api/indicators';
import type { Interval } from '@/types/marketData';
import { INDICATOR_PRESETS, type Indicator } from '@/types/indicators';

const STORAGE_KEY = 'vtrader.indicators';

function loadEnabled(): string[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    // Drop ids that no longer exist, so a renamed preset cannot wedge the UI.
    const known = new Set(INDICATOR_PRESETS.map((preset) => preset.id));
    return parsed.filter((id): id is string => typeof id === 'string' && known.has(id));
  } catch {
    return [];
  }
}

interface UseIndicatorsResult {
  enabled: string[];
  toggle: (id: string) => void;
  clear: () => void;
  indicators: Indicator[];
  loading: boolean;
  error: string | null;
}

/**
 * Fetches the enabled indicators for the current timeframe.
 *
 * The selection is remembered in localStorage, so a reload does not clear the
 * chart. Values are recomputed whenever the timeframe or the selection
 * changes -- never derived in the browser, always from real candle data on
 * the server.
 */
export function useIndicators(
  interval: Interval,
  limit: number,
): UseIndicatorsResult {
  const [enabled, setEnabled] = useState<string[]>(loadEnabled);
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const specs = useMemo(
    () =>
      INDICATOR_PRESETS.filter((preset) => enabled.includes(preset.id)).map(
        (preset) => preset.spec,
      ),
    [enabled],
  );

  const toggle = useCallback((id: string) => {
    setEnabled((current) => {
      const next = current.includes(id)
        ? current.filter((entry) => entry !== id)
        : [...current, id];
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        // A private window can refuse storage; the toggle still works.
      }
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    setEnabled([]);
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Ignore.
    }
  }, []);

  useEffect(() => {
    if (specs.length === 0) {
      setIndicators([]);
      setError(null);
      return;
    }

    const controller = new AbortController();
    let cancelled = false;

    setLoading(true);
    setError(null);

    fetchIndicators(interval, limit, specs, controller.signal)
      .then((result) => {
        if (cancelled) return;
        setIndicators(result.indicators);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled || controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : 'Could not load indicators.');
        setLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [interval, limit, specs]);

  return { enabled, toggle, clear, indicators, loading, error };
}

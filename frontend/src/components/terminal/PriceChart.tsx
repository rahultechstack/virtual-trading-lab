import {
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { OscillatorPane } from './OscillatorPane';
import { StatusClock } from '@/components/StatusClock';
import { fetchCandles } from '@/api/marketData';
import { useIndicators } from '@/hooks/useIndicators';
import { formatChartTick, formatChartTime } from '@/utils/format';
import { TIMEFRAMES, type Candle, type Interval } from '@/types/marketData';
import { INDICATOR_PRESETS, type Indicator } from '@/types/indicators';
import type { PriceTick } from '@/types/stream';

const UP = '#2ea86a';
const DOWN = '#d9534f';
const GRID = '#232833';
const TEXT = '#949aa6';

/** Bollinger sub-series are drawn thinner than a standalone moving average. */
const BAND_LABELS = new Set(['Upper', 'Lower']);

interface Props {
  symbol: string;
  exchange: string;
  tick: PriceTick | null;
}

function toSeconds(iso: string): UTCTimestamp {
  return Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;
}

function toCandlestick(candle: Candle): CandlestickData {
  return {
    time: toSeconds(candle.timestamp),
    open: Number(candle.open),
    high: Number(candle.high),
    low: Number(candle.low),
    close: Number(candle.close),
  };
}

function toVolume(candle: Candle): HistogramData {
  const rising = Number(candle.close) >= Number(candle.open);
  return {
    time: toSeconds(candle.timestamp),
    value: candle.volume,
    color: rising ? 'rgba(46, 168, 106, 0.4)' : 'rgba(217, 83, 79, 0.4)',
  };
}

function colorFor(indicator: Indicator): string {
  return (
    INDICATOR_PRESETS.find((preset) => preset.spec.startsWith(indicator.type))
      ?.color ?? '#4c8dff'
  );
}

/**
 * Candlestick chart with volume, indicator overlays and oscillator panes.
 *
 * The chart instance is created once and kept in refs; only its *data* is
 * replaced when the timeframe changes, so pan and zoom survive.
 *
 * Live ticks mutate the most recent bar in place — `series.update()` with the
 * same timestamp — so the forming candle grows the way it does on a real
 * terminal, without refetching history.
 *
 * Indicators are computed server-side from the same candles drawn here, so
 * study and price can never disagree. Oscillators live in their own charts
 * below (Lightweight Charts v4 has no panes) with time scales synchronised.
 */
export function PriceChart({ symbol, exchange, tick }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const overlayRefs = useRef<ISeriesApi<'Line'>[]>([]);
  /** The bar currently being formed, mutated by live ticks. */
  const lastBarRef = useRef<CandlestickData | null>(null);
  /** Every chart whose time scale must move together. */
  const syncedChartsRef = useRef<Set<IChartApi>>(new Set());

  const [interval, setInterval] = useState<Interval>('5m');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [barCount, setBarCount] = useState(0);

  const timeframe = useMemo(
    () => TIMEFRAMES.find((entry) => entry.interval === interval) ?? TIMEFRAMES[1],
    [interval],
  );

  const {
    enabled,
    toggle,
    clear,
    indicators,
    loading: indicatorsLoading,
    error: indicatorError,
  } = useIndicators(timeframe.interval, timeframe.limit, symbol);

  const overlays = indicators.filter((indicator) => indicator.pane === 'price');
  const oscillators = indicators.filter((indicator) => indicator.pane === 'separate');

  // -- chart registration for time-scale sync ---------------------------
  const registerChart = useCallback((chart: IChartApi) => {
    syncedChartsRef.current.add(chart);
  }, []);

  const unregisterChart = useCallback((chart: IChartApi) => {
    syncedChartsRef.current.delete(chart);
  }, []);

  // -- create the main chart once ---------------------------------------
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { color: 'transparent' },
        textColor: TEXT,
        fontSize: 11,
      },
      grid: { vertLines: { color: GRID }, horzLines: { color: GRID } },
      rightPriceScale: {
        borderColor: GRID,
        scaleMargins: { top: 0.08, bottom: 0.26 },
      },
      timeScale: {
        borderColor: GRID,
        timeVisible: true,
        secondsVisible: false,
        // Axis labels in exchange-local time. Without this Lightweight
        // Charts prints UTC, so an IST session reads 5h30m early.
        // tickMarkType >= 3 is Time / TimeWithSeconds; below that it is a date.
        tickMarkFormatter: (time: unknown, tickMarkType: number) =>
          typeof time === 'number'
            ? formatChartTick(time, tickMarkType >= 3 ? 'time' : 'date')
            : '',
      },
      localization: {
        // Crosshair / tooltip readout, same timezone as the axis.
        timeFormatter: (time: unknown) =>
          typeof time === 'number' ? formatChartTime(time) : '',
      },
      crosshair: {
        vertLine: { color: TEXT, labelBackgroundColor: '#2a2f3a' },
        horzLine: { color: TEXT, labelBackgroundColor: '#2a2f3a' },
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: UP,
      downColor: DOWN,
      borderUpColor: UP,
      borderDownColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    });

    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    registerChart(chart);

    return () => {
      unregisterChart(chart);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      overlayRefs.current = [];
      lastBarRef.current = null;
    };
  }, [registerChart, unregisterChart]);

  // -- keep every time scale in step -------------------------------------
  useEffect(() => {
    const charts = [...syncedChartsRef.current];
    if (charts.length < 2) return;

    // A guard, because applying a range fires the same event on the target.
    let applying = false;

    const subscriptions = charts.map((chart) => {
      const handler = (range: unknown) => {
        if (applying || !range) return;
        applying = true;
        for (const other of charts) {
          if (other === chart) continue;
          try {
            other.timeScale().setVisibleLogicalRange(range as never);
          } catch {
            // A chart disposed mid-pan; nothing to do.
          }
        }
        applying = false;
      };
      chart.timeScale().subscribeVisibleLogicalRangeChange(handler);
      return { chart, handler };
    });

    return () => {
      for (const { chart, handler } of subscriptions) {
        try {
          chart.timeScale().unsubscribeVisibleLogicalRangeChange(handler);
        } catch {
          // Already disposed.
        }
      }
    };
    // Re-subscribe whenever the set of oscillator panes changes.
  }, [oscillators.length]);

  // -- load history whenever the timeframe changes -----------------------
  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    setLoading(true);
    setError(null);

    fetchCandles(timeframe.interval, timeframe.limit, symbol, controller.signal)
      .then((series) => {
        if (cancelled) return;
        const candles = series.candles;

        candleSeriesRef.current?.setData(candles.map(toCandlestick));
        volumeSeriesRef.current?.setData(candles.map(toVolume));
        lastBarRef.current =
          candles.length > 0 ? toCandlestick(candles[candles.length - 1]) : null;

        setBarCount(candles.length);
        chartRef.current?.timeScale().fitContent();
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled || controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : 'Could not load candles.');
        setLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
    // Refetched on instrument change too: the chart is per-symbol.
  }, [timeframe, symbol]);

  // -- draw the price-pane overlays --------------------------------------
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    const created: ISeriesApi<'Line'>[] = [];

    for (const indicator of overlays) {
      const base = colorFor(indicator);
      for (const series of indicator.series) {
        const isBand = BAND_LABELS.has(series.label);
        const line = chart.addLineSeries({
          color: base,
          lineWidth: isBand ? 1 : 2,
          lineStyle: isBand ? 2 : 0, // dashed envelopes, solid averages
          priceLineVisible: false,
          lastValueVisible: !isBand,
          crosshairMarkerVisible: false,
          priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
        });
        line.setData(
          series.points.map<LineData>((point) => ({
            time: toSeconds(point.timestamp),
            value: Number(point.value),
          })),
        );
        created.push(line);
      }
    }

    overlayRefs.current = created;

    return () => {
      for (const line of created) {
        try {
          chart.removeSeries(line);
        } catch {
          // The chart may already be disposed.
        }
      }
      overlayRefs.current = [];
    };
  }, [overlays]);

  // -- fold live ticks into the forming bar ------------------------------
  useEffect(() => {
    const series = candleSeriesRef.current;
    const bar = lastBarRef.current;
    if (!tick || !series || !bar) return;

    const price = Number(tick.last_price);
    if (!Number.isFinite(price)) return;

    const updated: CandlestickData = {
      time: bar.time,
      open: bar.open,
      high: Math.max(bar.high, price),
      low: Math.min(bar.low, price),
      close: price,
    };

    lastBarRef.current = updated;
    series.update(updated);
  }, [tick]);

  const overlayPresets = INDICATOR_PRESETS.filter((p) => p.pane === 'price');
  const oscillatorPresets = INDICATOR_PRESETS.filter((p) => p.pane === 'separate');

  return (
    <section className="panel chart">
      <header className="panel__header">
        <h2 className="panel__title">
          {symbol}
          <span className="muted panel__subtitle">{exchange} · candles</span>
        </h2>

        <div className="chart__timeframes" role="group" aria-label="Timeframe">
          {TIMEFRAMES.map((entry) => (
            <button
              key={entry.interval}
              type="button"
              className={`chip ${entry.interval === interval ? 'chip--active' : ''}`}
              onClick={() => setInterval(entry.interval)}
              aria-pressed={entry.interval === interval}
            >
              {entry.label}
            </button>
          ))}
        </div>
      </header>

      <div className="indicator-bar">
        <span className="indicator-bar__label">Indicators</span>

        <div className="indicator-bar__group">
          {overlayPresets.map((preset) => (
            <button
              key={preset.id}
              type="button"
              className={`chip chip--indicator ${
                enabled.includes(preset.id) ? 'chip--active' : ''
              }`}
              onClick={() => toggle(preset.id)}
              aria-pressed={enabled.includes(preset.id)}
            >
              <i className="swatch" style={{ background: preset.color }} />
              {preset.label}
            </button>
          ))}
        </div>

        <div className="indicator-bar__group">
          {oscillatorPresets.map((preset) => (
            <button
              key={preset.id}
              type="button"
              className={`chip chip--indicator ${
                enabled.includes(preset.id) ? 'chip--active' : ''
              }`}
              onClick={() => toggle(preset.id)}
              aria-pressed={enabled.includes(preset.id)}
            >
              {preset.label}
            </button>
          ))}
        </div>

        {enabled.length > 0 && (
          <button type="button" className="chip" onClick={clear}>
            Clear
          </button>
        )}
      </div>

      <div className="chart__canvas" ref={containerRef} />

      {oscillators.map((indicator) => (
        <OscillatorPane
          key={indicator.key}
          indicator={indicator}
          onChartReady={registerChart}
          onChartDestroy={unregisterChart}
        />
      ))}

      <footer className="chart__footer muted">
        {error ? (
          <span className="negative">{error}</span>
        ) : loading ? (
          <span>Loading candles…</span>
        ) : (
          <span>
            {barCount} bars · {timeframe.label}
            {tick ? ' · live' : ''}
            {indicatorsLoading && ' · computing indicators…'}
            {indicatorError && (
              <span className="negative"> · {indicatorError}</span>
            )}
          </span>
        )}

        <StatusClock tick={tick} />
      </footer>
    </section>
  );
}

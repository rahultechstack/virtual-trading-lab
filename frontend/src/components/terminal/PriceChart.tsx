import {
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useEffect, useMemo, useRef, useState } from 'react';

import { fetchCandles } from '@/api/marketData';
import { TIMEFRAMES, type Candle, type Interval } from '@/types/marketData';
import type { PriceTick } from '@/types/stream';

const UP = '#2ea86a';
const DOWN = '#d9534f';
const GRID = '#232833';
const TEXT = '#949aa6';

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

/**
 * Candlestick and volume chart.
 *
 * The chart instance is created once and kept in refs; only its *data* is
 * replaced when the timeframe changes. Rebuilding the chart on every render
 * would lose the user's pan and zoom.
 *
 * Live ticks mutate the most recent bar in place — `series.update()` with the
 * same timestamp — so the forming candle grows the way it does on a real
 * terminal, without refetching history.
 */
export function PriceChart({ symbol, exchange, tick }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  /** The bar currently being formed, mutated by live ticks. */
  const lastBarRef = useRef<CandlestickData | null>(null);

  const [interval, setInterval] = useState<Interval>('5m');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [barCount, setBarCount] = useState(0);

  const timeframe = useMemo(
    () => TIMEFRAMES.find((entry) => entry.interval === interval) ?? TIMEFRAMES[1],
    [interval],
  );

  // -- create the chart once --------------------------------------------
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
      grid: {
        vertLines: { color: GRID },
        horzLines: { color: GRID },
      },
      rightPriceScale: {
        borderColor: GRID,
        scaleMargins: { top: 0.08, bottom: 0.26 },
      },
      timeScale: {
        borderColor: GRID,
        timeVisible: true,
        secondsVisible: false,
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
      // Its own scale, pinned to the bottom quarter so it sits under price.
      priceScaleId: 'volume',
    });
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    return () => {
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      lastBarRef.current = null;
    };
  }, []);

  // -- load history whenever the timeframe changes -----------------------
  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    setLoading(true);
    setError(null);

    fetchCandles(timeframe.interval, timeframe.limit, controller.signal)
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
  }, [timeframe]);

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

      <div className="chart__canvas" ref={containerRef} />

      <footer className="chart__footer muted">
        {error ? (
          <span className="negative">{error}</span>
        ) : loading ? (
          <span>Loading candles…</span>
        ) : (
          <span>
            {barCount} bars · {timeframe.label}
            {tick ? ' · live' : ''}
          </span>
        )}
      </footer>
    </section>
  );
}

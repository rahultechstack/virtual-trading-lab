import {
  createChart,
  type AreaData,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useEffect, useMemo, useRef } from 'react';

import type { PortfolioSnapshot } from '@/types/portfolio';
import { formatChartTick, formatChartTime } from '@/utils/format';

import {
  DOWN_COLOR as DOWN,
  GRID_COLOR as GRID,
  TEXT_COLOR as TEXT,
  UP_COLOR as UP,
} from '@/config/chart';

interface Props {
  snapshots: PortfolioSnapshot[];
  /** Which figure to plot. */
  metric: 'total_value' | 'net_pnl';
}

/**
 * The equity curve.
 *
 * Snapshots can share a timestamp to the second — a trade snapshot and a
 * periodic one can land together — and Lightweight Charts requires strictly
 * ascending times, so duplicates are collapsed to the last value at each
 * second rather than dropped or nudged.
 */
export function EquityCurve({ snapshots, metric }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Area'> | null>(null);

  const points = useMemo<AreaData[]>(() => {
    const byTime = new Map<number, number>();
    for (const snapshot of snapshots) {
      const seconds = Math.floor(new Date(snapshot.captured_at).getTime() / 1000);
      const value = Number(snapshot[metric]);
      if (Number.isFinite(seconds) && Number.isFinite(value)) {
        byTime.set(seconds, value);
      }
    }
    return [...byTime.entries()]
      .sort(([a], [b]) => a - b)
      .map(([time, value]) => ({ time: time as UTCTimestamp, value }));
  }, [snapshots, metric]);

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
      rightPriceScale: { borderColor: GRID },
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

    const series = chart.addAreaSeries({
      lineWidth: 2,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    });

    chartRef.current = chart;
    seriesRef.current = series;

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;

    // Colour by direction over the window: green when it ended above where it
    // started, red otherwise.
    const rising =
      points.length < 2 || points[points.length - 1].value >= points[0].value;
    const tone = rising ? UP : DOWN;

    series.applyOptions({
      lineColor: tone,
      topColor: rising ? 'rgba(46, 168, 106, 0.28)' : 'rgba(217, 83, 79, 0.28)',
      bottomColor: 'rgba(0, 0, 0, 0)',
    });
    series.setData(points);
    chartRef.current?.timeScale().fitContent();
  }, [points]);

  return (
    <div className="equity-curve">
      <div className="equity-curve__canvas" ref={containerRef} />
      {points.length === 0 && (
        <p className="muted equity-curve__empty">
          No snapshots yet. Place a trade, or wait for the next periodic
          capture.
        </p>
      )}
    </div>
  );
}

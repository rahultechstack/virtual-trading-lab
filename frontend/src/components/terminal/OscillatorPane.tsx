import {
  createChart,
  type HistogramData,
  type IChartApi,
  type LineData,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useEffect, useRef } from 'react';

import type { Indicator, IndicatorSeries } from '@/types/indicators';
import { formatChartTick, formatChartTime } from '@/utils/format';

const GRID = '#232833';
const TEXT = '#949aa6';

/** Distinct colours for the sub-series of a multi-line oscillator. */
const SERIES_COLORS: Record<string, string> = {
  MACD: '#4c8dff',
  Signal: '#f59e0b',
  Histogram: '#64748b',
};

const DEFAULT_COLOR = '#4c8dff';

interface Props {
  indicator: Indicator;
  /** Registers the chart so the parent can keep every time scale in step. */
  onChartReady: (chart: IChartApi) => void;
  onChartDestroy: (chart: IChartApi) => void;
}

function toLineData(series: IndicatorSeries): LineData[] {
  return series.points.map((point) => ({
    time: Math.floor(new Date(point.timestamp).getTime() / 1000) as UTCTimestamp,
    value: Number(point.value),
  }));
}

function toHistogramData(series: IndicatorSeries): HistogramData[] {
  return series.points.map((point) => {
    const value = Number(point.value);
    return {
      time: Math.floor(new Date(point.timestamp).getTime() / 1000) as UTCTimestamp,
      value,
      // Colour by sign, which is how a MACD histogram is read.
      color: value >= 0 ? 'rgba(46, 168, 106, 0.6)' : 'rgba(217, 83, 79, 0.6)',
    };
  });
}

/**
 * A separate pane for an oscillator.
 *
 * RSI and MACD have their own scales and cannot share the price axis.
 * Lightweight Charts v4 has no multi-pane support, so each oscillator gets its
 * own chart instance; the parent synchronises the time scales so panning the
 * price drags these with it.
 */
export function OscillatorPane({ indicator, onChartReady, onChartDestroy }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);

  // Created once. Data updates happen in the effect below, so a data change
  // never tears down and rebuilds the chart.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { color: 'transparent' },
        textColor: TEXT,
        fontSize: 10,
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
      handleScroll: true,
      handleScale: true,
    });

    chartRef.current = chart;
    onChartReady(chart);

    return () => {
      onChartDestroy(chart);
      chart.remove();
      chartRef.current = null;
    };
  }, [onChartReady, onChartDestroy]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    // Rebuild the series when the indicator's shape changes. Series have no
    // "clear all" in v4, so they are tracked and removed explicitly.
    const created = indicator.series.map((series) => {
      const color = SERIES_COLORS[series.label] ?? DEFAULT_COLOR;

      if (series.style === 'histogram') {
        const histogram = chart.addHistogramSeries({
          priceFormat: { type: 'price', precision: 4, minMove: 0.0001 },
        });
        histogram.setData(toHistogramData(series));
        return histogram;
      }

      const line = chart.addLineSeries({
        color,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      });
      line.setData(toLineData(series));
      return line;
    });

    // A bounded oscillator reads better pinned to its own range.
    if (indicator.scale_min !== null && indicator.scale_max !== null) {
      chart.priceScale('right').applyOptions({ autoScale: false });
      created[0]?.applyOptions({
        autoscaleInfoProvider: () => ({
          priceRange: {
            minValue: Number(indicator.scale_min),
            maxValue: Number(indicator.scale_max),
          },
        }),
      });
    }

    return () => {
      for (const series of created) {
        try {
          chart.removeSeries(series);
        } catch {
          // The chart may already be disposed; nothing to clean up.
        }
      }
    };
  }, [indicator]);

  return (
    <section className="oscillator">
      <header className="oscillator__header">
        <span className="oscillator__label">{indicator.label}</span>
        {indicator.insufficient_data && (
          <span className="muted oscillator__note">
            needs {indicator.warmup + 1} bars
          </span>
        )}
      </header>
      <div className="oscillator__canvas" ref={containerRef} />
    </section>
  );
}

/**
 * **CHART APPEARANCE.**
 *
 * One palette for every chart — the price chart, the oscillator pane and the
 * equity curve — so a colour change is a single edit rather than three.
 *
 * These are deliberately plain constants, not CSS variables: TradingView's
 * Lightweight Charts renders to a canvas and takes colours as JS values, so it
 * cannot read a stylesheet.
 */

/** Rising candle / positive series. */
export const UP_COLOR = '#2ea86a';

/** Falling candle / negative series. */
export const DOWN_COLOR = '#d9534f';

/** Grid lines and axis borders. */
export const GRID_COLOR = '#232833';

/** Axis labels and legends. */
export const TEXT_COLOR = '#949aa6';

/**
 * Palette indicators are drawn in.
 *
 * Named by role rather than by indicator, so re-theming is one edit here
 * instead of hunting colours through the preset list and the oscillator pane.
 * Colours are assigned to a preset explicitly (never by index) so an indicator
 * keeps its colour no matter which others are enabled.
 */
export const INDICATOR_COLORS = {
  primary: '#4c8dff',
  violet: '#a855f7',
  amber: '#f59e0b',
  slate: '#64748b',
  teal: '#14b8a6',
} as const;

/** Default line colour for an indicator with no colour of its own. */
export const DEFAULT_SERIES_COLOR = INDICATOR_COLORS.primary;

/**
 * Timezone the chart's time axis is rendered in.
 *
 * Lightweight Charts renders a UTC timestamp in UTC unless told otherwise, so
 * without this the axis would read 07:12 for a 12:42 IST bar. Match this to
 * the exchange you mostly watch.
 */
export const CHART_TIME_ZONE = 'Asia/Kolkata';

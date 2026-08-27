import { useEffect, useMemo, useState } from 'react';

import { placeOrder } from '@/api/trading';
import type { Instrument } from '@/types/instruments';
import type { OrderResult, OrderSide, Position } from '@/types/trading';
import { formatQuantity, formatRupees, toQuantity } from '@/utils/format';

/** Quick sizes for a whole-unit instrument, e.g. an NSE equity. */
const WHOLE_QUANTITIES = ['1', '10', '50', '100'];

/**
 * Quick sizes for a fractional instrument.
 *
 * Deliberately expressed as *fractions of one unit* rather than a rupee value:
 * one BTC and one DOGE differ by seven orders of magnitude, so any fixed rupee
 * ladder would be useless for one of them.
 */
const FRACTIONAL_QUANTITIES = ['0.001', '0.01', '0.1', '1'];

const SIDES: ReadonlyArray<{
  side: OrderSide;
  label: string;
  tone: 'buy' | 'sell';
  hint: string;
}> = [
  { side: 'BUY', label: 'Buy', tone: 'buy', hint: 'Open or add to a long. Covers a short first if one is open.' },
  { side: 'SELL', label: 'Sell', tone: 'sell', hint: 'Close a long. Cannot exceed the position.' },
  { side: 'SHORT_SELL', label: 'Short Sell', tone: 'sell', hint: 'Open or add to a short. Closes a long first if one is open.' },
  { side: 'BUY_TO_COVER', label: 'Buy to Cover', tone: 'buy', hint: 'Close a short. Cannot exceed the position.' },
];

interface Props {
  /** Instrument being traded. Decides symbol, step size and quick sizes. */
  instrument: Instrument | null;
  referencePrice: string | null;
  position: Position | null;
  disabled?: boolean;
  onFilled: (result: OrderResult) => void;
}

/**
 * Order entry.
 *
 * The live price is sent as the **reference** price; the backend derives the
 * actual fill from it via the spread and slippage models, so the price shown
 * here is deliberately not promised as the execution price.
 *
 * Quantity is held as a **string** and sent as one. Nothing here assumes a
 * whole number: what counts as a legal size comes from the instrument's
 * `quantity_step`, and the backend validates it again regardless.
 */
export function TradingPanel({
  instrument,
  referencePrice,
  position,
  disabled = false,
  onFilled,
}: Props) {
  const symbol = instrument?.symbol ?? null;
  const isFractional = instrument?.is_fractional ?? false;

  const [quantity, setQuantity] = useState('10');
  const [pending, setPending] = useState<OrderSide | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastFill, setLastFill] = useState<OrderResult | null>(null);

  const quickSizes = isFractional ? FRACTIONAL_QUANTITIES : WHOLE_QUANTITIES;

  // Switching between a share and a coin makes the old size meaningless --
  // 10 BTC is not a practice trade. Reset to a sensible default for the class.
  useEffect(() => {
    setQuantity(isFractional ? '0.01' : '10');
    setLastFill(null);
    setError(null);
  }, [isFractional, symbol]);

  const invalidQuantity = useMemo(() => {
    const numeric = Number(quantity);
    if (!Number.isFinite(numeric) || numeric <= 0) return true;
    // A whole-unit instrument rejects fractions; the backend enforces the same
    // rule, this only spares the round trip.
    return !isFractional && !Number.isInteger(numeric);
  }, [quantity, isFractional]);

  const noPrice = referencePrice === null;
  const blocked = disabled || noPrice || invalidQuantity || pending !== null;

  const notional = useMemo(() => {
    const price = Number(referencePrice);
    const size = Number(quantity);
    if (!Number.isFinite(price) || !Number.isFinite(size) || size <= 0) return null;
    return price * size;
  }, [referencePrice, quantity]);

  async function submit(side: OrderSide) {
    if (blocked || referencePrice === null) return;

    setPending(side);
    setError(null);

    try {
      const result = await placeOrder({
        side,
        // Sent as a string so the exact size reaches the ledger.
        quantity,
        reference_price: referencePrice,
        ...(symbol ? { symbol } : {}),
      });
      setLastFill(result);
      onFilled(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'The order was rejected.');
      setLastFill(null);
    } finally {
      setPending(null);
    }
  }

  return (
    <section className="panel">
      <header className="panel__header">
        <h2 className="panel__title">Order</h2>
        <span className="muted panel__subtitle">
          {symbol ?? 'Market'}
          {instrument ? ` · ${instrument.exchange}` : ''}
        </span>
      </header>

      <label className="field">
        <span className="field__label">
          Quantity
          {isFractional && <span className="muted"> · fractional</span>}
        </span>
        <input
          className="field__input"
          type="number"
          min={0}
          // The instrument's own increment, so the spinner steps by something
          // meaningful for a coin as well as for a share.
          step={instrument?.quantity_step ?? 1}
          inputMode="decimal"
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
          disabled={disabled}
        />
      </label>

      <div className="quick-quantities">
        {quickSizes.map((value) => (
          <button
            key={value}
            type="button"
            className={`chip ${quantity === value ? 'chip--active' : ''}`}
            onClick={() => setQuantity(value)}
            disabled={disabled}
          >
            {value}
          </button>
        ))}
      </div>

      <dl className="kv kv--tight">
        <dt>Reference</dt>
        <dd>{formatRupees(referencePrice)}</dd>
        <dt>Order value</dt>
        <dd>{notional === null ? '—' : formatRupees(notional)}</dd>
        <dt>Position</dt>
        <dd>{formatQuantity(position?.quantity ?? 0)}</dd>
      </dl>

      <div className="order-buttons">
        {SIDES.map(({ side, label, tone, hint }) => (
          <button
            key={side}
            type="button"
            className={`order-button order-button--${tone}`}
            onClick={() => void submit(side)}
            disabled={blocked}
            title={hint}
          >
            {pending === side ? 'Placing…' : label}
          </button>
        ))}
      </div>

      {invalidQuantity && (
        <p className="form-note negative">
          {isFractional
            ? 'Quantity must be a positive number.'
            : `${symbol ?? 'This instrument'} trades in whole units, so the quantity must be a positive whole number.`}
        </p>
      )}
      {noPrice && !invalidQuantity && (
        <p className="form-note muted">Waiting for a live price before trading.</p>
      )}

      {error && (
        <div className="alert alert--compact">
          <strong>Order rejected</strong>
          <p>{error}</p>
        </div>
      )}

      {lastFill && !error && (
        <div className="fill-receipt">
          <div className="fill-receipt__head">
            <strong>Filled</strong>
            <span className="muted">
              {formatQuantity(lastFill.trade.quantity)} @{' '}
              {formatRupees(lastFill.trade.execution_price)}
            </span>
          </div>
          <dl className="kv kv--tight">
            <dt>Charges</dt>
            <dd>{formatRupees(lastFill.total_charges)}</dd>
            {toQuantity(lastFill.trade.tds) > 0 && (
              <>
                <dt>of which TDS</dt>
                <dd>{formatRupees(lastFill.trade.tds)}</dd>
              </>
            )}
            <dt>Net P&amp;L</dt>
            <dd className={Number(lastFill.net_pnl) >= 0 ? 'positive' : 'negative'}>
              {formatRupees(lastFill.net_pnl, { sign: true })}
            </dd>
          </dl>
        </div>
      )}
    </section>
  );
}

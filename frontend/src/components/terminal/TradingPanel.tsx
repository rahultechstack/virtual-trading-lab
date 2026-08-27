import { useState } from 'react';

import { placeOrder } from '@/api/trading';
import type { OrderResult, OrderSide, Position } from '@/types/trading';
import { formatRupees } from '@/utils/format';

const QUICK_QUANTITIES = [1, 10, 50, 100];

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
  /** Instrument being traded. Sent with every order. */
  symbol: string | null;
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
 */
export function TradingPanel({
  symbol,
  referencePrice,
  position,
  disabled = false,
  onFilled,
}: Props) {
  const [quantity, setQuantity] = useState(10);
  const [pending, setPending] = useState<OrderSide | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastFill, setLastFill] = useState<OrderResult | null>(null);

  const noPrice = referencePrice === null;
  const invalidQuantity = !Number.isInteger(quantity) || quantity <= 0;
  const blocked = disabled || noPrice || invalidQuantity || pending !== null;

  async function submit(side: OrderSide) {
    if (blocked || referencePrice === null) return;

    setPending(side);
    setError(null);

    try {
      const result = await placeOrder({
        side,
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
        <span className="muted panel__subtitle">{symbol ?? 'Market'}</span>
      </header>

      <label className="field">
        <span className="field__label">Quantity</span>
        <input
          className="field__input"
          type="number"
          min={1}
          step={1}
          value={quantity}
          onChange={(event) => setQuantity(Number(event.target.value))}
          disabled={disabled}
        />
      </label>

      <div className="quick-quantities">
        {QUICK_QUANTITIES.map((value) => (
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
        <dt>Position</dt>
        <dd>{position ? position.quantity : 0}</dd>
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
        <p className="form-note negative">Quantity must be a positive whole number.</p>
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
              {lastFill.trade.quantity} @ {formatRupees(lastFill.trade.execution_price)}
            </span>
          </div>
          <dl className="kv kv--tight">
            <dt>Charges</dt>
            <dd>{formatRupees(lastFill.total_charges)}</dd>
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

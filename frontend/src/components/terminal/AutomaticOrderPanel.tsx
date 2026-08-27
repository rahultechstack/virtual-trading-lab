import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  cancelAutomaticOrder,
  createAutomaticOrder,
  fetchActiveAutomaticOrders,
} from '@/api/automaticOrders';
import {
  CONDITION_LABELS,
  STATUS_TONE,
  TYPE_LABELS,
  type AutomaticOrder,
  type AutomaticOrderType,
  type TriggerCondition,
} from '@/types/automaticOrders';
import type { Instrument } from '@/types/instruments';
import { SIDE_LABELS, type OrderSide, type Position } from '@/types/trading';
import {
  formatQuantity,
  formatRupees,
  formatTime,
  toQuantity,
} from '@/utils/format';

const TYPES: AutomaticOrderType[] = ['STOP_LOSS', 'PRICE_TRIGGER'];
const CONDITIONS: TriggerCondition[] = ['LTE', 'GTE'];
const ACTIONS: OrderSide[] = ['BUY', 'SELL', 'SHORT_SELL', 'BUY_TO_COVER'];

interface Props {
  /** Instrument the trigger is created against. Decides the legal step size. */
  instrument: Instrument | null;
  position: Position | null;
  /** Live price, sent so the backend can reject a stop that fires instantly. */
  referencePrice: string | null;
  disabled?: boolean;
  /** Bumped by the parent when a trigger fires, to reload the list. */
  refreshToken: number;
  /** Called after a create/cancel so the parent can refresh account panels. */
  onChanged: () => void;
}

/**
 * Stop-loss and price-trigger entry, plus the list of active triggers.
 *
 * For a stop-loss the condition and action are *derived from the open
 * position* and locked, because only one combination is valid: a long is
 * stopped out by SELL on <=, a short by BUY_TO_COVER on >=.
 *
 * This is a convenience, not a rule. The backend re-derives and re-validates
 * the same thing, and it alone decides whether a trigger fires -- the frontend
 * never evaluates a price against a trigger.
 *
 * A crypto trigger works identically, with a fractional quantity. It also
 * stays armed around the clock: the backend keeps polling an instrument that
 * has an active trigger even with no browser open, so a stop set on Friday can
 * fire over the weekend.
 */
export function AutomaticOrderPanel({
  instrument,
  position,
  referencePrice,
  disabled = false,
  refreshToken,
  onChanged,
}: Props) {
  const [orderType, setOrderType] = useState<AutomaticOrderType>('STOP_LOSS');
  const [condition, setCondition] = useState<TriggerCondition>('LTE');
  const [action, setAction] = useState<OrderSide>('SELL');
  const [triggerPrice, setTriggerPrice] = useState('');
  // A Decimal string, like every quantity crossing the API.
  const [quantity, setQuantity] = useState('100');

  const [orders, setOrders] = useState<AutomaticOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const symbol = instrument?.symbol ?? null;
  const isFractional = instrument?.is_fractional ?? false;
  const quantityHeld = toQuantity(position?.quantity);
  const isStopLoss = orderType === 'STOP_LOSS';
  const isFlat = quantityHeld === 0;

  // The only valid stop-loss shape for the current position.
  const derived = useMemo(() => {
    if (quantityHeld > 0) return { condition: 'LTE' as const, action: 'SELL' as const };
    if (quantityHeld < 0)
      return { condition: 'GTE' as const, action: 'BUY_TO_COVER' as const };
    return null;
  }, [quantityHeld]);

  useEffect(() => {
    if (!isStopLoss || derived === null) return;
    setCondition(derived.condition);
    setAction(derived.action);
    // Protect the whole position by default. Taken from the position string so
    // a fractional crypto size survives exactly.
    setQuantity(String(position?.quantity ?? 0).replace('-', ''));
  }, [isStopLoss, derived, quantityHeld, position]);

  const load = useCallback(() => {
    const controller = new AbortController();
    setLoading(true);
    fetchActiveAutomaticOrders(controller.signal)
      .then((rows) => {
        setOrders(rows);
        setError(null);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : 'Could not load triggers.');
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  useEffect(() => load(), [load, refreshToken]);

  const trigger = Number(triggerPrice);
  const invalidTrigger = !Number.isFinite(trigger) || trigger <= 0;
  const size = Number(quantity);
  const invalidQuantity =
    !Number.isFinite(size) ||
    size <= 0 ||
    // Whole units only, unless the instrument says otherwise.
    (!isFractional && !Number.isInteger(size));
  const stopWithoutPosition = isStopLoss && isFlat;
  const blocked =
    disabled || pending || invalidTrigger || invalidQuantity || stopWithoutPosition;

  async function submit() {
    if (blocked) return;
    setPending(true);
    setError(null);
    setNotice(null);
    try {
      const created = await createAutomaticOrder({
        order_type: orderType,
        trigger_price: triggerPrice,
        trigger_condition: condition,
        action,
        quantity,
        reference_price: referencePrice,
        ...(symbol ? { symbol } : {}),
      });
      setNotice(
        `${TYPE_LABELS[created.order_type]} armed on ${created.symbol}: ` +
          `${SIDE_LABELS[created.action]} ${formatQuantity(created.quantity)} at ` +
          `${CONDITION_LABELS[created.trigger_condition]} ` +
          `${formatRupees(created.trigger_price)}`,
      );
      setTriggerPrice('');
      load();
      onChanged();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not create the trigger.');
    } finally {
      setPending(false);
    }
  }

  async function cancel(id: number) {
    setError(null);
    setNotice(null);
    try {
      await cancelAutomaticOrder(id);
      load();
      onChanged();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not cancel the trigger.');
    }
  }

  return (
    <section className="panel">
      <header className="panel__header">
        <h2 className="panel__title">Automatic Order</h2>
        <span className="muted panel__subtitle">
          {orders.length > 0 ? `${orders.length} active` : 'none active'}
        </span>
      </header>

      <div className="auto-order__form">
        <label className="field">
          <span className="field__label">Type</span>
          <select
            className="field__input"
            value={orderType}
            onChange={(event) => setOrderType(event.target.value as AutomaticOrderType)}
            disabled={disabled}
          >
            {TYPES.map((value) => (
              <option key={value} value={value}>
                {TYPE_LABELS[value]}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span className="field__label">Condition</span>
          <select
            className="field__input"
            value={condition}
            onChange={(event) => setCondition(event.target.value as TriggerCondition)}
            disabled={disabled || (isStopLoss && derived !== null)}
          >
            {CONDITIONS.map((value) => (
              <option key={value} value={value}>
                {CONDITION_LABELS[value]}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span className="field__label">Trigger</span>
          <input
            className="field__input"
            type="number"
            min={0}
            step="0.05"
            inputMode="decimal"
            placeholder={referencePrice ?? '0.00'}
            value={triggerPrice}
            onChange={(event) => setTriggerPrice(event.target.value)}
            disabled={disabled}
          />
        </label>

        <label className="field">
          <span className="field__label">Action</span>
          <select
            className="field__input"
            value={action}
            onChange={(event) => setAction(event.target.value as OrderSide)}
            disabled={disabled || (isStopLoss && derived !== null)}
          >
            {ACTIONS.map((value) => (
              <option key={value} value={value}>
                {SIDE_LABELS[value]}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span className="field__label">Quantity</span>
          <input
            className="field__input"
            type="number"
            min={0}
            step={instrument?.quantity_step ?? 1}
            inputMode="decimal"
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
            disabled={disabled}
          />
        </label>

        <button
          type="button"
          className="button-primary auto-order__create"
          onClick={() => void submit()}
          disabled={blocked}
        >
          {pending ? 'Creating…' : 'Create'}
        </button>
      </div>

      {isStopLoss && derived !== null && (
        <p className="form-note muted">
          Stop-loss on a {quantityHeld > 0 ? 'long' : 'short'} of{' '}
          {formatQuantity(Math.abs(quantityHeld))}: closes with{' '}
          {SIDE_LABELS[derived.action]} when price {CONDITION_LABELS[derived.condition]}{' '}
          trigger. The backend enforces this.
        </p>
      )}
      {stopWithoutPosition && (
        <p className="form-note negative">
          A stop-loss needs an open position. Use a Price Trigger instead.
        </p>
      )}
      {invalidTrigger && triggerPrice !== '' && (
        <p className="form-note negative">Trigger price must be a positive number.</p>
      )}
      {invalidQuantity && !isFractional && (
        <p className="form-note negative">
          {symbol ?? 'This instrument'} trades in whole units, so the quantity
          must be a positive whole number.
        </p>
      )}

      {error && (
        <div className="alert alert--compact">
          <strong>Rejected</strong>
          <p>{error}</p>
        </div>
      )}
      {notice && !error && <p className="form-note positive">{notice}</p>}

      <div className="auto-order__list">
        {loading ? (
          <p className="muted table-empty">Loading…</p>
        ) : orders.length === 0 ? (
          <p className="muted table-empty">No active automatic orders.</p>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Type</th>
                  <th>Condition</th>
                  <th className="numeric">Trigger</th>
                  <th>Action</th>
                  <th className="numeric">Qty</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {orders.map((order) => (
                  <tr key={order.id}>
                    <td>
                      <strong>{order.symbol}</strong>
                    </td>
                    <td>{TYPE_LABELS[order.order_type]}</td>
                    <td className="muted">
                      {CONDITION_LABELS[order.trigger_condition]}
                    </td>
                    <td className="numeric">{formatRupees(order.trigger_price)}</td>
                    <td>{SIDE_LABELS[order.action]}</td>
                    <td className="numeric">{formatQuantity(order.quantity)}</td>
                    <td>
                      <span className={`badge badge--${STATUS_TONE[order.status]}`}>
                        {order.status}
                      </span>
                    </td>
                    <td className="muted">{formatTime(order.created_at)}</td>
                    <td>
                      <button
                        type="button"
                        className="chip"
                        onClick={() => void cancel(order.id)}
                      >
                        Cancel
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

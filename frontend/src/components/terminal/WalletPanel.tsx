import type { Portfolio, Wallet } from '@/types/trading';
import { formatRupees, signClass } from '@/utils/format';

interface Props {
  wallet: Wallet | null;
  portfolio: Portfolio | null;
  needsWallet: boolean;
  onCreateWallet: () => void;
}

/**
 * Account value.
 *
 * Realized P&L is shown **gross and net** because the two differ by the
 * charges paid, and a terminal that only showed the gross figure would
 * flatter every result.
 */
export function WalletPanel({ wallet, portfolio, needsWallet, onCreateWallet }: Props) {
  if (needsWallet) {
    return (
      <section className="panel">
        <header className="panel__header">
          <h2 className="panel__title">Wallet</h2>
        </header>
        <p className="muted">No wallet yet.</p>
        <button type="button" className="button-primary" onClick={onCreateWallet}>
          Create wallet
        </button>
      </section>
    );
  }

  return (
    <section className="panel">
      <header className="panel__header">
        <h2 className="panel__title">Wallet</h2>
        <span className="muted panel__subtitle">{wallet?.currency ?? 'INR'}</span>
      </header>

      <div className="metric">
        <span className="metric__label">Available cash</span>
        <span className="metric__value">{formatRupees(portfolio?.cash_balance ?? wallet?.cash_balance)}</span>
      </div>

      <dl className="kv kv--tight">
        <dt>Portfolio value</dt>
        <dd>{formatRupees(portfolio?.total_equity)}</dd>

        <dt>Position value</dt>
        <dd>{formatRupees(portfolio?.position_value)}</dd>

        <dt>Realized (gross)</dt>
        <dd className={signClass(portfolio?.realized_pnl)}>
          {formatRupees(portfolio?.realized_pnl, { sign: true })}
        </dd>

        <dt>Charges paid</dt>
        <dd className="muted">{formatRupees(portfolio?.total_charges)}</dd>

        <dt>Realized (net)</dt>
        <dd className={signClass(portfolio?.net_realized_pnl)}>
          {formatRupees(portfolio?.net_realized_pnl, { sign: true })}
        </dd>

        <dt>Unrealized</dt>
        <dd className={signClass(portfolio?.unrealized_pnl)}>
          {formatRupees(portfolio?.unrealized_pnl, { sign: true })}
        </dd>
      </dl>

      <div className="metric metric--total">
        <span className="metric__label">Total P&amp;L (net)</span>
        <span className={`metric__value ${signClass(portfolio?.net_total_pnl)}`}>
          {formatRupees(portfolio?.net_total_pnl, { sign: true })}
        </span>
      </div>
    </section>
  );
}

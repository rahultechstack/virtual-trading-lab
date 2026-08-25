"""Cash and portfolio valuation.

**Cash model.** Cash moves with the fill, and charges always come out of it:

* a buy debits ``quantity x price`` **plus** charges;
* a sell credits ``quantity x price`` **minus** charges.

The execution price already embeds the spread and slippage, so those are not
deducted again here -- they are recorded separately on the trade so the damage
stays visible.

That single rule covers all four sides and produces correct realized P&L for
both directions. Worked through:

* Long: buy 100 @ 1400 (-140,000), sell 100 @ 1450 (+145,000) -> +5,000 gross.
* Short: short 100 @ 1450 (+145,000), cover 100 @ 1400 (-140,000) -> +5,000 gross.

Net P&L is that gross figure less the charges on both legs.

**Known gap.** Short proceeds are credited as spendable cash and no margin is
reserved against the open short, so short size is not bounded by account
equity the way a real broker would bound it. Margin and leverage remain out of
scope; brokerage, statutory charges, slippage and spread are handled by
``FeeCalculator``, ``SlippageModel`` and ``SpreadModel``.

Debits are checked before they are applied, so the wallet's non-negative
balance constraint is enforced by the engine rather than tripped at COMMIT.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.core.exceptions import InsufficientFundsError
from app.models.wallet import Wallet
from app.repositories.wallet_repository import WalletRepository
from app.trading.execution import Fill
from app.trading.pnl import PnLCalculator, to_money


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Account state at a point in time.

    ``mark_price`` is supplied by the caller; the engine never reaches out to a
    market-data provider itself, which keeps it independent of that layer.
    """

    cash_balance: Decimal
    initial_balance: Decimal
    quantity: int
    average_price: Decimal
    #: Realized P&L from price movement, before charges.
    realized_pnl: Decimal
    #: Charges paid across every fill so far.
    total_charges: Decimal
    #: realized_pnl minus total_charges.
    net_realized_pnl: Decimal
    unrealized_pnl: Decimal
    position_value: Decimal
    total_equity: Decimal
    #: Gross realized plus unrealized.
    total_pnl: Decimal
    #: Net realized plus unrealized -- the honest number.
    net_total_pnl: Decimal
    mark_price: Decimal | None
    currency: str


class PortfolioManager:
    """Applies the cash side of a fill and values the account."""

    def __init__(self, wallet_repository: WalletRepository) -> None:
        self._wallets = wallet_repository

    # -- cash ------------------------------------------------------------

    @staticmethod
    def cash_delta(fill: Fill) -> Decimal:
        """Signed cash movement for a fill.

        Negative for buys, positive for sells, and charges always subtract:
        they are a cost whichever way the trade goes.
        """
        traded = fill.notional * Decimal(-fill.side.direction)
        return to_money(traded - fill.total_charges)

    @staticmethod
    def assert_affordable(wallet: Wallet, fill: Fill) -> None:
        """Reject a debit the wallet cannot cover.

        Charges are part of what must be afforded, so an order that only just
        fits on notional alone can still be rejected. Checked up front so a
        failed order raises a domain error instead of violating the wallet's
        non-negative CHECK constraint at commit time.
        """
        delta = PortfolioManager.cash_delta(fill)
        if delta >= 0:
            return
        required = -delta
        if wallet.cash_balance < required:
            charges = fill.total_charges
            detail = f" (including {charges} of charges)" if charges else ""
            raise InsufficientFundsError(
                f"Order needs {required}{detail} but the wallet holds "
                f"{wallet.cash_balance}."
            )

    @staticmethod
    def apply_cash(wallet: Wallet, fill: Fill) -> Wallet:
        """Move cash for a fill that has already been checked."""
        wallet.cash_balance = to_money(
            wallet.cash_balance + PortfolioManager.cash_delta(fill)
        )
        return wallet

    # -- valuation -------------------------------------------------------

    @staticmethod
    def snapshot(
        *,
        wallet: Wallet,
        quantity: int,
        average_price: Decimal,
        realized_pnl: Decimal,
        total_charges: Decimal = Decimal("0.00"),
        net_realized_pnl: Decimal | None = None,
        mark_price: Decimal | None = None,
    ) -> PortfolioSnapshot:
        """Value the account.

        Without a ``mark_price`` the open position cannot be valued, so
        unrealized P&L and position value report zero and equity falls back to
        cash plus realized P&L. Callers that need live valuation pass a price
        in from the market-data layer.
        """
        if mark_price is None or quantity == 0:
            unrealized = Decimal("0.00")
            position_value = Decimal("0.00")
        else:
            unrealized = PnLCalculator.unrealized_pnl(
                quantity=quantity, average_price=average_price, mark_price=mark_price
            )
            position_value = PnLCalculator.position_value(
                quantity=quantity, mark_price=mark_price
            )

        total_equity = to_money(wallet.cash_balance + position_value)
        net_realized = (
            net_realized_pnl
            if net_realized_pnl is not None
            else to_money(realized_pnl - total_charges)
        )

        return PortfolioSnapshot(
            cash_balance=wallet.cash_balance,
            initial_balance=wallet.initial_balance,
            quantity=quantity,
            average_price=average_price,
            realized_pnl=realized_pnl,
            total_charges=total_charges,
            net_realized_pnl=net_realized,
            unrealized_pnl=unrealized,
            position_value=position_value,
            total_equity=total_equity,
            total_pnl=to_money(realized_pnl + unrealized),
            net_total_pnl=to_money(net_realized + unrealized),
            mark_price=mark_price,
            currency=wallet.currency,
        )

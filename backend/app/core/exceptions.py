"""Domain exceptions.

Raised by the service layer, translated to HTTP responses by handlers
registered in ``app.main``. Services stay free of HTTP concerns.
"""


class DomainError(Exception):
    """Base class for expected, business-rule failures."""

    status_code: int = 400
    code: str = "domain_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class WalletNotFoundError(DomainError):
    status_code = 404
    code = "wallet_not_found"

    def __init__(
        self,
        message: str = "Wallet has not been initialised. POST /wallet/initialize first.",
    ) -> None:
        super().__init__(message)


class MarketDataError(DomainError):
    """Base class for market-data failures."""

    status_code = 502
    code = "market_data_error"


class MarketDataUnavailableError(MarketDataError):
    """The upstream provider was unreachable, rate-limited or returned junk."""

    status_code = 503
    code = "market_data_unavailable"


class UnsupportedSymbolError(MarketDataError):
    """The platform trades one instrument; anything else is rejected."""

    status_code = 400
    code = "unsupported_symbol"


class UnsupportedIntervalError(MarketDataError):
    """The configured provider does not serve the requested candle interval."""

    status_code = 400
    code = "unsupported_interval"


class LiveDataNotSupportedError(MarketDataError):
    """The configured provider has no streaming feed.

    Raised rather than silently degrading to polling, so a caller expecting a
    push feed finds out immediately.
    """

    status_code = 501
    code = "live_data_not_supported"


class AutomaticOrderError(DomainError):
    """Base class for automatic-order failures."""

    status_code = 400
    code = "automatic_order_error"


class InvalidAutomaticOrderError(AutomaticOrderError):
    """The trigger is malformed, or contradicts the position it protects."""

    code = "invalid_automatic_order"


class AutomaticOrderNotFoundError(AutomaticOrderError):
    """No automatic order with that id."""

    status_code = 404
    code = "automatic_order_not_found"


class TradingError(DomainError):
    """Base class for order-rejection reasons."""

    status_code = 400
    code = "trading_error"


class InvalidOrderError(TradingError):
    """The order is malformed: bad quantity, price or symbol."""

    code = "invalid_order"


class InvalidQuantityError(InvalidOrderError):
    """The quantity does not fit the instrument's tradable increment.

    A stock trades in whole shares, so ``0.5`` is refused. Crypto trades
    fractionally down to the instrument's ``quantity_step``, so a size finer
    than that is refused too. The rule comes from the instrument, never from a
    hard-coded assumption that quantities are integers.
    """

    code = "invalid_quantity"


class MarketClosedError(TradingError):
    """The instrument's market is not open for trading right now.

    Only raised when ``ENFORCE_MARKET_HOURS`` is on. Crypto never raises it:
    its calendar is open every hour of every day.
    """

    code = "market_closed"


class InsufficientFundsError(TradingError):
    """The wallet cannot cover the cash the order requires."""

    code = "insufficient_funds"


class InvalidPositionOperationError(TradingError):
    """The order contradicts the position it is being applied to.

    Raised when a closing-only side would do more than close: selling more
    than is held, or covering more than is short. Opening the opposite
    direction must be stated explicitly with SHORT_SELL or BUY.
    """

    code = "invalid_position_operation"

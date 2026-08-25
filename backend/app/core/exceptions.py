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

"""HTTP-level tests for the crypto asset class.

Everything here goes through the ASGI app, so it exercises the contract a
frontend actually sees: JSON shapes, Decimal-as-string quantities, the
asset-class filter and the market-status endpoint.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient

D = Decimal

INSTRUMENTS = "/api/v1/instruments"
MARKETS = "/api/v1/markets"
TRADING = "/api/v1/trading"
WALLET = "/api/v1/wallet"
AUTOMATIC = "/api/v1/automatic-orders"

BTC_PRICE = "7600000.00"
STOCK_PRICE = "1400.00"


@pytest.fixture
async def funded(client: AsyncClient) -> None:
    """A wallet with enough cash to buy a slice of a Bitcoin."""
    await client.post(f"{WALLET}/initialize", json={"initial_balance": "10000000.00"})


# ==========================================================================
# Instrument discovery
# ==========================================================================


async def test_the_universe_contains_both_stocks_and_crypto(client: AsyncClient):
    response = await client.get(INSTRUMENTS, params={"limit": 500})
    assert response.status_code == 200

    classes = {row["asset_class"] for row in response.json()}
    assert classes == {"STOCK", "CRYPTO"}


async def test_the_asset_class_filter_narrows_to_crypto(client: AsyncClient):
    response = await client.get(
        INSTRUMENTS, params={"asset_class": "CRYPTO", "limit": 500}
    )
    rows = response.json()

    assert rows, "the crypto catalogue must not be empty"
    assert all(row["asset_class"] == "CRYPTO" for row in rows)
    assert {"BTC", "ETH"} <= {row["symbol"] for row in rows}


async def test_the_asset_class_filter_narrows_to_stocks(client: AsyncClient):
    response = await client.get(
        INSTRUMENTS, params={"asset_class": "STOCK", "limit": 500}
    )
    rows = response.json()

    assert all(row["asset_class"] == "STOCK" for row in rows)
    assert "BTC" not in {row["symbol"] for row in rows}


async def test_searching_by_asset_name_finds_the_coin(client: AsyncClient):
    """The brief's example: searching "bitcoin" must return BTC."""
    response = await client.get(INSTRUMENTS, params={"search": "bitcoin"})
    rows = response.json()

    assert rows[0]["symbol"] == "BTC"
    assert rows[0]["company_name"] == "Bitcoin"
    assert rows[0]["asset_class"] == "CRYPTO"


async def test_searching_by_symbol_still_finds_the_stock(client: AsyncClient):
    response = await client.get(INSTRUMENTS, params={"search": "TCS"})
    assert response.json()[0]["symbol"] == "TCS"


async def test_an_instrument_reports_its_step_size_and_trading_hours(
    client: AsyncClient,
):
    response = await client.get(INSTRUMENTS, params={"search": "BTC"})
    btc = response.json()[0]

    assert btc["quantity_step"] == "0.00000001"
    assert btc["is_fractional"] is True
    assert btc["quantity_precision"] == 8
    assert btc["trading_hours"] == "24/7"
    assert btc["exchange"] == "CRYPTO"


async def test_a_stock_reports_whole_units_and_session_hours(client: AsyncClient):
    response = await client.get(INSTRUMENTS, params={"search": "RELIANCE"})
    stock = response.json()[0]

    assert stock["quantity_step"] == "1"
    assert stock["is_fractional"] is False
    assert stock["quantity_precision"] == 0
    assert "IST" in stock["trading_hours"]


# ==========================================================================
# Market status
# ==========================================================================


async def test_a_coins_market_is_always_open_with_no_boundaries(client: AsyncClient):
    response = await client.get(f"{MARKETS}/status", params={"symbol": "BTC"})
    assert response.status_code == 200

    body = response.json()
    assert body["is_open"] is True
    assert body["is_24x7"] is True
    assert body["status"] == "OPEN"
    # A continuous market has no next open or close -- null, not a guess.
    assert body["next_open"] is None
    assert body["next_close"] is None
    assert body["calendar"] == "crypto"


async def test_a_stocks_market_reports_the_nse_calendar(client: AsyncClient):
    response = await client.get(f"{MARKETS}/status", params={"symbol": "RELIANCE"})
    body = response.json()

    assert body["calendar"] == "nse"
    assert body["is_24x7"] is False
    assert body["timezone"] == "Asia/Kolkata"
    assert body["status"] in {"OPEN", "PRE_OPEN", "CLOSED", "WEEKEND", "HOLIDAY"}


async def test_market_status_reports_whether_closure_actually_blocks_trading(
    client: AsyncClient,
):
    body = (await client.get(f"{MARKETS}/status", params={"symbol": "RELIANCE"})).json()
    # Off by default: a closed market is informational in this paper lab.
    assert body["enforced"] is False


async def test_market_status_rejects_an_unsupported_symbol(client: AsyncClient):
    response = await client.get(f"{MARKETS}/status", params={"symbol": "AAPL"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_symbol"


async def test_every_asset_class_is_reported_in_one_call(client: AsyncClient):
    response = await client.get(f"{MARKETS}/statuses")
    rows = response.json()

    by_class = {row["asset_class"]: row for row in rows}
    assert set(by_class) == {"STOCK", "CRYPTO"}
    assert by_class["CRYPTO"]["is_open"] is True


# ==========================================================================
# Trading a coin over HTTP
# ==========================================================================


async def test_buying_a_fraction_of_a_bitcoin_over_http(client: AsyncClient, funded):
    response = await client.post(
        f"{TRADING}/orders",
        json={
            "side": "BUY",
            "quantity": "0.001",
            "reference_price": BTC_PRICE,
            "symbol": "BTC",
        },
    )
    assert response.status_code == 201

    body = response.json()
    # Quantities cross the wire as Decimal strings, like every other number.
    assert D(body["order"]["quantity"]) == D("0.001")
    assert D(body["position"]["quantity"]) == D("0.001")
    assert body["order"]["asset_class"] == "CRYPTO"
    assert body["order"]["exchange"] == "CRYPTO"


async def test_a_fractional_order_on_a_stock_is_refused_over_http(
    client: AsyncClient, funded
):
    response = await client.post(
        f"{TRADING}/orders",
        json={
            "side": "BUY",
            "quantity": "0.5",
            "reference_price": STOCK_PRICE,
            "symbol": "RELIANCE",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_quantity"


async def test_a_sub_satoshi_order_is_refused_over_http(client: AsyncClient, funded):
    response = await client.post(
        f"{TRADING}/orders",
        json={
            "side": "BUY",
            "quantity": "0.000000001",
            "reference_price": BTC_PRICE,
            "symbol": "BTC",
        },
    )
    assert response.status_code == 400


async def test_the_full_crypto_round_trip_over_http(client: AsyncClient, funded):
    for side, price in (
        ("BUY", BTC_PRICE),
        ("SELL", "7700000.00"),
        ("SHORT_SELL", "7700000.00"),
        ("BUY_TO_COVER", "7500000.00"),
    ):
        response = await client.post(
            f"{TRADING}/orders",
            json={
                "side": side,
                "quantity": "0.001",
                "reference_price": price,
                "symbol": "BTC",
            },
        )
        assert response.status_code == 201, (side, response.text)

    position = (
        await client.get(f"{TRADING}/position", params={"symbol": "BTC"})
    ).json()
    assert D(position["quantity"]) == 0


async def test_a_crypto_trade_reports_no_securities_charges(
    client: AsyncClient, funded
):
    await client.post(
        f"{TRADING}/orders",
        json={
            "side": "BUY",
            "quantity": "0.001",
            "reference_price": BTC_PRICE,
            "symbol": "BTC",
        },
    )
    trade = (await client.get(f"{TRADING}/trades")).json()[0]

    assert trade["asset_class"] == "CRYPTO"
    assert D(trade["stt"]) == 0
    assert D(trade["stamp_duty"]) == 0
    assert D(trade["sebi_charges"]) == 0


# ==========================================================================
# Execution-cost preview is asset-aware
# ==========================================================================


async def test_the_cost_preview_uses_the_crypto_schedule_for_a_coin(
    client: AsyncClient,
):
    response = await client.get(
        f"{TRADING}/execution-cost",
        params={
            "side": "SELL",
            "quantity": "0.01",
            "reference_price": BTC_PRICE,
            "symbol": "BTC",
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert body["asset_class"] == "CRYPTO"
    assert D(body["charges"]["stt"]) == 0
    # TDS is withheld on a disposal, and is the marker the crypto schedule ran.
    assert D(body["charges"]["tds"]) > 0


async def test_the_cost_preview_still_uses_the_equity_schedule_for_a_stock(
    client: AsyncClient,
):
    response = await client.get(
        f"{TRADING}/execution-cost",
        params={"side": "SELL", "quantity": "100", "reference_price": STOCK_PRICE},
    )
    body = response.json()

    assert body["asset_class"] == "STOCK"
    assert D(body["charges"]["tds"]) == 0
    assert D(body["charges"]["stt"]) > 0


# ==========================================================================
# Portfolio across both asset classes
# ==========================================================================


async def test_the_portfolio_summary_splits_value_by_asset_class(
    client: AsyncClient, funded
):
    await client.post(
        f"{TRADING}/orders",
        json={
            "side": "BUY",
            "quantity": "100",
            "reference_price": STOCK_PRICE,
            "symbol": "RELIANCE",
        },
    )
    await client.post(
        f"{TRADING}/orders",
        json={
            "side": "BUY",
            "quantity": "0.001",
            "reference_price": BTC_PRICE,
            "symbol": "BTC",
        },
    )

    response = await client.get(
        f"{TRADING}/portfolio/summary",
        params={"marks": f"RELIANCE:{STOCK_PRICE},BTC:{BTC_PRICE}"},
    )
    body = response.json()

    split = body["value_by_asset_class"]
    assert D(split["STOCK"]) == D("140000.00")
    assert D(split["CRYPTO"]) == D("7600.00")

    symbols = {row["symbol"]: row for row in body["positions"]}
    assert symbols["BTC"]["asset_class"] == "CRYPTO"
    assert symbols["RELIANCE"]["asset_class"] == "STOCK"


# ==========================================================================
# Automatic orders on a coin, over HTTP
# ==========================================================================


async def test_a_fractional_crypto_stop_loss_is_created_over_http(
    client: AsyncClient, funded
):
    await client.post(
        f"{TRADING}/orders",
        json={
            "side": "BUY",
            "quantity": "0.001",
            "reference_price": BTC_PRICE,
            "symbol": "BTC",
        },
    )

    response = await client.post(
        AUTOMATIC,
        json={
            "order_type": "STOP_LOSS",
            "trigger_price": "7000000.00",
            "trigger_condition": "LTE",
            "action": "SELL",
            "quantity": "0.001",
            "symbol": "BTC",
            "reference_price": BTC_PRICE,
        },
    )
    assert response.status_code == 201

    body = response.json()
    assert D(body["quantity"]) == D("0.001")
    assert body["asset_class"] == "CRYPTO"
    assert body["exchange"] == "CRYPTO"


async def test_a_crypto_stop_loss_on_the_wrong_side_is_still_rejected(
    client: AsyncClient, funded
):
    """The directional rule is asset-agnostic: a long stops out downwards."""
    await client.post(
        f"{TRADING}/orders",
        json={
            "side": "BUY",
            "quantity": "0.001",
            "reference_price": BTC_PRICE,
            "symbol": "BTC",
        },
    )
    response = await client.post(
        AUTOMATIC,
        json={
            "order_type": "STOP_LOSS",
            "trigger_price": "8000000.00",
            "trigger_condition": "GTE",
            "action": "BUY_TO_COVER",
            "quantity": "0.001",
            "symbol": "BTC",
            "reference_price": BTC_PRICE,
        },
    )
    assert response.status_code == 400


# ==========================================================================
# Provider routing through the API
# ==========================================================================


async def test_a_coin_is_priced_by_the_crypto_feed_not_the_equity_feed(
    client: AsyncClient,
):
    """Regression: BTC was reaching the equity feed and coming back in USD.

    The equity provider resolves a bare "BTC" to an unrelated US-listed
    security, so the endpoint returned roughly 35 dollars for Bitcoin. The API
    layer must build the market-data service WITHOUT pinning a provider, so
    each instrument is served by the feed routed for its asset class.
    """
    from app.api.v1.endpoints.market_data import get_market_data_service
    from app.market_data.registry import get_provider

    service = get_market_data_service(get_provider())

    from app.market_data.instruments import resolve_instrument

    assert service.provider_for(resolve_instrument("BTC")).capabilities.name == (
        "yahoo_crypto"
    )
    assert service.provider_for(resolve_instrument("RELIANCE")).capabilities.name == (
        "yahoo"
    )


async def test_an_explicitly_supplied_provider_still_serves_every_asset_class():
    """The seam tests rely on: an injected fake is never bypassed by routing."""
    from app.api.v1.endpoints.market_data import get_market_data_service
    from app.market_data.instruments import resolve_instrument

    class _Fake:
        capabilities = None

    service = get_market_data_service(_Fake())
    assert service.provider_for(resolve_instrument("BTC")) is service._provider


async def test_provider_capabilities_are_reported_per_asset_class(
    client: AsyncClient,
):
    equity = (await client.get("/api/v1/market-data/provider")).json()
    crypto = (
        await client.get("/api/v1/market-data/provider", params={"symbol": "BTC"})
    ).json()

    assert equity["name"] != crypto["name"]
    assert crypto["name"] == "yahoo_crypto"

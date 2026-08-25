"""Captured Yahoo Finance response shapes.

Trimmed from real ``/v8/finance/chart/RELIANCE.NS`` responses so the parsing
tests exercise the actual payload structure -- including its quirks -- without
touching the network.
"""

from typing import Any

#: Response to interval=1d&range=1d, used for quotes.
QUOTE_PAYLOAD: dict[str, Any] = {
    "chart": {
        "result": [
            {
                "meta": {
                    "currency": "INR",
                    "symbol": "RELIANCE.NS",
                    "exchangeName": "NSI",
                    "fullExchangeName": "NSE",
                    "instrumentType": "EQUITY",
                    "regularMarketPrice": 1314.3,
                    "regularMarketTime": 1787650652,
                    "regularMarketDayHigh": 1319.9,
                    "regularMarketDayLow": 1301.05,
                    "regularMarketVolume": 6346700,
                    # NOTE: for interval=1d Yahoo omits "previousClose" and
                    # only sends "chartPreviousClose". It also has no
                    # day-open field at all -- that lives in the bar series.
                    "chartPreviousClose": 1309.8,
                    "exchangeTimezoneName": "Asia/Kolkata",
                    # NOTE: no "bid" / "ask" keys. Yahoo's chart endpoint does
                    # not carry order-book depth.
                },
                "timestamp": [1787629500],
                "indicators": {
                    "quote": [
                        {
                            "open": [1304.3],
                            "high": [1319.9],
                            "low": [1301.05],
                            "close": [1314.3],
                            "volume": [6346700],
                        }
                    ]
                },
            }
        ],
        "error": None,
    }
}

#: Daily candles, including a null row of the kind Yahoo emits for holidays.
CANDLES_PAYLOAD: dict[str, Any] = {
    "chart": {
        "result": [
            {
                "meta": {"currency": "INR", "symbol": "RELIANCE.NS"},
                "timestamp": [1787097600, 1787184000, 1787270400, 1787356800],
                "indicators": {
                    "quote": [
                        {
                            "open": [1290.5, 1301.0, None, 1308.25],
                            "high": [1304.5999755859375, 1312.4, None, 1322.0],
                            "low": [1288.0, 1298.6, None, 1305.1],
                            "close": [1301.0, 1307.75, None, 1319.4],
                            "volume": [4210000, 3980500, None, 5120300],
                        }
                    ]
                },
            }
        ],
        "error": None,
    }
}

#: What Yahoo returns for an unknown ticker.
UNKNOWN_SYMBOL_PAYLOAD: dict[str, Any] = {
    "chart": {
        "result": None,
        "error": {
            "code": "Not Found",
            "description": "No data found, symbol may be delisted",
        },
    }
}

#: A well-formed envelope carrying no price.
EMPTY_META_PAYLOAD: dict[str, Any] = {
    "chart": {
        "result": [{"meta": {"currency": "INR"}, "timestamp": [], "indicators": {}}],
        "error": None,
    }
}

"""Alpha Vantage adapter: fetches daily closing stock prices.

Plain HTTP + JSON parsing code — no AI. Alpha Vantage's free tier is rate
limited and returns errors as 200-status JSON bodies rather than HTTP error
codes, so a real failure here (rate limit hit, invalid symbol) needs to be
detected explicitly and raised as a clear, actionable error rather than
surfacing as a confusing KeyError three layers down.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import requests

API_URL = "https://www.alphavantage.co/query"
REQUEST_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class DailyClose:
    """One trading day's closing price.

    Attributes:
        trade_date: The trading date.
        close: The closing price.
    """

    trade_date: date
    close: float


class AlphaVantageError(RuntimeError):
    """Raised when Alpha Vantage returns an error/rate-limit message, or a
    response shape without the expected time series data."""


def get_daily_closes(
    ticker: str, api_key: str, outputsize: str = "compact"
) -> list[DailyClose]:
    """Fetch a ticker's recent daily closing prices from Alpha Vantage.

    Args:
        ticker: Stock ticker symbol.
        api_key: Alpha Vantage API key.
        outputsize: "compact" (last ~100 trading days) or "full" (full
            history). Compact is enough to find the two most recent closes.

    Returns:
        Daily closes, sorted most recent first.

    Raises:
        AlphaVantageError: If Alpha Vantage returns an error/rate-limit
            message, or a response without the expected time series data.
        requests.HTTPError: If the HTTP request itself fails.
    """
    response = requests.get(
        API_URL,
        params={
            "function": "TIME_SERIES_DAILY",
            "symbol": ticker,
            "outputsize": outputsize,
            "apikey": api_key,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()

    time_series = payload.get("Time Series (Daily)")
    if time_series is None:
        message = (
            payload.get("Note")
            or payload.get("Error Message")
            or payload.get("Information")
            or f"unexpected response shape: {payload!r}"
        )
        raise AlphaVantageError(
            f"Alpha Vantage request for {ticker!r} failed: {message}"
        )

    closes = [
        DailyClose(
            trade_date=date.fromisoformat(day), close=float(values["4. close"])
        )
        for day, values in time_series.items()
    ]
    closes.sort(key=lambda c: c.trade_date, reverse=True)
    return closes


def get_latest_two_closes(ticker: str, api_key: str) -> tuple[DailyClose, DailyClose]:
    """Fetch the two most recent trading-day closes for a ticker.

    Used by the trigger job to compute a percent change between the last
    two actual trading days — correctly skipping weekends/holidays, unlike
    naively comparing to calendar "yesterday".

    Args:
        ticker: Stock ticker symbol.
        api_key: Alpha Vantage API key.

    Returns:
        A (latest, previous) tuple of DailyClose, most recent first.

    Raises:
        AlphaVantageError: If fewer than two trading days of data are
            available, or the underlying request fails (see get_daily_closes).
    """
    closes = get_daily_closes(ticker, api_key)
    if len(closes) < 2:
        raise AlphaVantageError(
            f"Alpha Vantage returned fewer than 2 trading days of data for {ticker!r}"
        )
    return closes[0], closes[1]

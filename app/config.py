"""Application configuration: environment variables and the watched-company list.

Loads settings from `.env` (via python-dotenv) and `config/watchlist.yaml`,
and exposes them as typed, validated objects for the rest of the app to use.
This module is the single place external configuration boundaries are
crossed — nothing else in the app should call `os.environ` or open the
watchlist file directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WATCHLIST_PATH = PROJECT_ROOT / "config" / "watchlist.yaml"

_REQUIRED_ENV_VARS = (
    "DATABASE_URL",
    "ALPHA_VANTAGE_API_KEY",
    "OPENAI_API_KEY",
    "RESEND_API_KEY",
    "ALERT_EMAIL_TO",
    "ALERT_EMAIL_FROM",
    "SEC_USER_AGENT",
)


@dataclass(frozen=True)
class Settings:
    """Typed application settings loaded from environment variables.

    Attributes:
        database_url: Neon Postgres connection string (pgvector enabled).
        alpha_vantage_api_key: API key for Alpha Vantage price data.
        openai_api_key: API key for OpenAI embeddings and chat completions.
        resend_api_key: API key for sending email via Resend.
        alert_email_to: Recipient address for trigger explanation emails.
        alert_email_from: Verified sender address for trigger explanation emails.
        sec_user_agent: Identifying User-Agent string required by SEC EDGAR.
        price_move_threshold_pct: Minimum absolute daily price move, in
            percent, that counts as a trigger.
        openai_chat_model: OpenAI model used for the explanation step.
        openai_embedding_model: OpenAI model used to generate embeddings.
    """

    database_url: str
    alpha_vantage_api_key: str
    openai_api_key: str
    resend_api_key: str
    alert_email_to: str
    alert_email_from: str
    sec_user_agent: str
    price_move_threshold_pct: float
    openai_chat_model: str
    openai_embedding_model: str


def get_settings() -> Settings:
    """Load and validate application settings from environment variables.

    Reads `.env` (if present) into the process environment, then builds a
    `Settings` instance. Collects every missing required variable before
    raising, so a misconfigured `.env` can be fixed in one pass instead of
    one failure at a time.

    Returns:
        A populated, validated `Settings` instance.

    Raises:
        RuntimeError: If any required environment variable is unset or empty.
    """
    load_dotenv()

    missing = [name for name in _REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): " + ", ".join(missing)
        )

    return Settings(
        database_url=os.environ["DATABASE_URL"],
        alpha_vantage_api_key=os.environ["ALPHA_VANTAGE_API_KEY"],
        openai_api_key=os.environ["OPENAI_API_KEY"],
        resend_api_key=os.environ["RESEND_API_KEY"],
        alert_email_to=os.environ["ALERT_EMAIL_TO"],
        alert_email_from=os.environ["ALERT_EMAIL_FROM"],
        sec_user_agent=os.environ["SEC_USER_AGENT"],
        price_move_threshold_pct=float(
            os.environ.get("PRICE_MOVE_THRESHOLD_PCT", "5")
        ),
        openai_chat_model=os.environ.get("OPENAI_CHAT_MODEL", "gpt-5.6-luna"),
        openai_embedding_model=os.environ.get(
            "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
        ),
    )


def load_watchlist(path: Path = DEFAULT_WATCHLIST_PATH) -> list[str]:
    """Load the list of watched ticker symbols from a watchlist YAML file.

    Args:
        path: Path to the watchlist YAML file. Defaults to
            `config/watchlist.yaml` in the project root.

    Returns:
        A list of uppercase ticker symbols, in the order they appear in the
        file.

    Raises:
        RuntimeError: If the file is missing, empty, or malformed (not a
            mapping with a `companies` list of `{ticker: ...}` entries).
    """
    if not path.exists():
        raise RuntimeError(f"Watchlist file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "companies" not in data:
        raise RuntimeError(
            f"Watchlist file {path} must be a mapping with a 'companies' key"
        )

    tickers: list[str] = []
    for entry in data["companies"]:
        if not isinstance(entry, dict) or "ticker" not in entry:
            raise RuntimeError(f"Invalid watchlist entry in {path}: {entry!r}")
        tickers.append(str(entry["ticker"]).upper())

    if not tickers:
        raise RuntimeError(f"Watchlist file {path} contains no companies")

    return tickers

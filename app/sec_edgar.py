"""SEC EDGAR adapter: resolves company CIKs, lists recent filings, and
fetches filing documents as plain text.

Plain HTTP + parsing code — no AI. Every request includes an identifying
User-Agent, as SEC EDGAR requires and will rate-limit or block requests
without one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL_TEMPLATE = "https://data.sec.gov/submissions/CIK{cik}.json"
RELEVANT_FORM_TYPES = frozenset({"10-K", "10-Q"})

DEFAULT_CACHE_PATH = (
    Path(__file__).resolve().parent.parent / ".cache" / "company_tickers.json"
)
DEFAULT_CACHE_MAX_AGE = timedelta(days=7)

REQUEST_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class CompanyInfo:
    """A company's identity as known to SEC EDGAR.

    Attributes:
        ticker: Stock ticker symbol, uppercased.
        name: Company name as registered with SEC.
        cik: Zero-padded 10-digit SEC Central Index Key.
    """

    ticker: str
    name: str
    cik: str


@dataclass(frozen=True)
class FilingInfo:
    """One filing listed in a company's SEC submissions history.

    Attributes:
        accession_number: SEC's globally unique identifier for this filing.
        form_type: Filing form type, e.g. "10-K" or "10-Q".
        filing_date: Date the filing was submitted to SEC.
        primary_doc_url: URL of the filing's primary document.
    """

    accession_number: str
    form_type: str
    filing_date: date
    primary_doc_url: str


def _fetch_ticker_map(
    user_agent: str,
    cache_path: Path = DEFAULT_CACHE_PATH,
    max_age: timedelta = DEFAULT_CACHE_MAX_AGE,
) -> dict:
    """Fetch SEC's full ticker-to-CIK mapping, using a local cache when fresh.

    Args:
        user_agent: Identifying User-Agent string required by SEC.
        cache_path: Where to read/write the cached mapping.
        max_age: How old the cache may be before it's considered stale.

    Returns:
        The raw parsed JSON from SEC's company_tickers.json (a dict keyed
        by arbitrary indices, each value containing "cik_str", "ticker",
        and "title").
    """
    if cache_path.exists():
        age = datetime.now(UTC) - datetime.fromtimestamp(
            cache_path.stat().st_mtime, tz=UTC
        )
        if age < max_age:
            return json.loads(cache_path.read_text(encoding="utf-8"))

    response = requests.get(
        TICKER_MAP_URL,
        headers={"User-Agent": user_agent},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data), encoding="utf-8")
    return data


def resolve_cik(
    ticker: str,
    user_agent: str,
    cache_path: Path = DEFAULT_CACHE_PATH,
) -> CompanyInfo:
    """Resolve a ticker symbol to its SEC CIK and registered company name.

    Args:
        ticker: Stock ticker symbol to look up (case-insensitive).
        user_agent: Identifying User-Agent string required by SEC.
        cache_path: Where to read/write the cached ticker-to-CIK mapping.

    Returns:
        The matching CompanyInfo.

    Raises:
        ValueError: If the ticker isn't found in SEC's mapping.
    """
    ticker_map = _fetch_ticker_map(user_agent, cache_path)
    ticker_upper = ticker.upper()

    for entry in ticker_map.values():
        if entry["ticker"].upper() == ticker_upper:
            cik = str(entry["cik_str"]).zfill(10)
            return CompanyInfo(ticker=ticker_upper, name=entry["title"], cik=cik)

    raise ValueError(f"Ticker {ticker!r} not found in SEC's company_tickers.json")


def list_recent_filings(cik: str, user_agent: str) -> list[FilingInfo]:
    """List a company's recent 10-K/10-Q filings from SEC EDGAR.

    Args:
        cik: Zero-padded 10-digit SEC Central Index Key.
        user_agent: Identifying User-Agent string required by SEC.

    Returns:
        10-K/10-Q filings from the company's recent submissions, in the
        order SEC returns them (most recent first).
    """
    url = SUBMISSIONS_URL_TEMPLATE.format(cik=cik)
    response = requests.get(
        url, headers={"User-Agent": user_agent}, timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    recent = response.json()["filings"]["recent"]

    filings = []
    for i, form_type in enumerate(recent["form"]):
        if form_type not in RELEVANT_FORM_TYPES:
            continue

        accession_number = recent["accessionNumber"][i]
        accession_no_dashes = accession_number.replace("-", "")
        primary_doc_url = (
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{accession_no_dashes}/{recent['primaryDocument'][i]}"
        )
        filings.append(
            FilingInfo(
                accession_number=accession_number,
                form_type=form_type,
                filing_date=date.fromisoformat(recent["filingDate"][i]),
                primary_doc_url=primary_doc_url,
            )
        )

    return filings


def fetch_filing_document(url: str, user_agent: str) -> str:
    """Fetch a filing's primary document and return it as plain text.

    HTML is stripped via BeautifulSoup so downstream text processing (e.g.
    risk_factors.py's section extraction) works on plain text regardless of
    whether SEC served HTML or plain text for this filing.

    Args:
        url: The filing document's URL (from FilingInfo.primary_doc_url).
        user_agent: Identifying User-Agent string required by SEC.

    Returns:
        The document's text content, with HTML tags stripped if present.
    """
    response = requests.get(
        url, headers={"User-Agent": user_agent}, timeout=REQUEST_TIMEOUT_SECONDS * 2
    )
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "")
    if "html" in content_type.lower() or url.lower().endswith((".htm", ".html")):
        soup = BeautifulSoup(response.text, "html.parser")
        return soup.get_text(separator="\n")
    return response.text

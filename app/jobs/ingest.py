"""Daily ingestion job: pulls new SEC filings for each watched company,
extracts their Risk Factors text, chunks it, embeds it, and stores it.

CLI entrypoint: `python -m app.jobs.ingest`. Intended to run once daily,
before the trigger job (see app/scheduler.py), so any filing that dropped
today is already searchable before that day's price move is checked.
"""

from __future__ import annotations

import logging
import sys

import psycopg
from openai import OpenAI

from app import db
from app.chunking import split_into_chunks
from app.config import get_settings, load_watchlist
from app.embeddings import embed_texts
from app.risk_factors import extract_risk_factors
from app.sec_edgar import fetch_filing_document, list_recent_filings, resolve_cik

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

RISK_FACTORS_SECTION = "risk_factors"


def ingest_company(
    conn: psycopg.Connection,
    client: OpenAI,
    ticker: str,
    sec_user_agent: str,
    embedding_model: str,
) -> None:
    """Ingest all new filings for one watched company.

    Resolves the company's CIK, lists its recent 10-K/10-Q filings, skips
    any already ingested, and for each new one: fetches the document,
    extracts the Risk Factors section, chunks it, embeds each chunk, and
    stores everything. A filing with no extractable Risk Factors section is
    logged and skipped, not treated as an error — see risk_factors.py.

    Args:
        conn: Open database connection.
        client: An initialized OpenAI client.
        ticker: Ticker symbol to ingest.
        sec_user_agent: Identifying User-Agent required by SEC EDGAR.
        embedding_model: OpenAI embedding model name.
    """
    company_info = resolve_cik(ticker, sec_user_agent)
    company_id = db.get_or_create_company(
        conn, company_info.ticker, company_info.name, company_info.cik
    )
    logger.info(
        "Resolved %s -> %s (CIK %s)", ticker, company_info.name, company_info.cik
    )

    filings = list_recent_filings(company_info.cik, sec_user_agent)
    new_filings = [
        filing for filing in filings if not db.filing_exists(conn, filing.accession_number)
    ]
    logger.info("%s: %d filings found, %d new", ticker, len(filings), len(new_filings))

    for filing in new_filings:
        document_text = fetch_filing_document(filing.primary_doc_url, sec_user_agent)
        risk_text = extract_risk_factors(document_text)

        if risk_text is None:
            logger.warning(
                "%s: no Risk Factors section found in %s filed %s (%s) — skipping",
                ticker,
                filing.form_type,
                filing.filing_date,
                filing.accession_number,
            )
            continue

        chunks = split_into_chunks(risk_text)
        chunk_embeddings = embed_texts(chunks, client, embedding_model)

        filing_id = db.insert_filing(
            conn,
            company_id,
            filing.accession_number,
            filing.form_type,
            filing.filing_date,
            filing.primary_doc_url,
        )
        for index, (chunk_text, embedding) in enumerate(zip(chunks, chunk_embeddings)):
            db.insert_filing_chunk(
                conn,
                filing_id,
                company_id,
                RISK_FACTORS_SECTION,
                index,
                chunk_text,
                embedding,
            )

        logger.info(
            "%s: ingested %s filed %s (%s) as %d chunks",
            ticker,
            filing.form_type,
            filing.filing_date,
            filing.accession_number,
            len(chunks),
        )


def main() -> None:
    """Run the ingestion job for every company in the watchlist.

    Each company is processed independently: an error ingesting one company
    is logged and the job moves on to the next, but the process exits
    non-zero if any company failed, so a cron/scheduler failure hook can
    surface it instead of it failing silently.
    """
    settings = get_settings()
    tickers = load_watchlist()
    client = OpenAI(api_key=settings.openai_api_key)

    failed_tickers: list[str] = []
    with db.get_connection(settings.database_url) as conn:
        for ticker in tickers:
            try:
                ingest_company(
                    conn,
                    client,
                    ticker,
                    settings.sec_user_agent,
                    settings.openai_embedding_model,
                )
            except Exception:
                logger.exception("%s: ingestion failed", ticker)
                failed_tickers.append(ticker)

    if failed_tickers:
        logger.error("Ingestion finished with failures: %s", failed_tickers)
        sys.exit(1)

    logger.info("Ingestion finished successfully for all %d companies", len(tickers))


if __name__ == "__main__":
    main()

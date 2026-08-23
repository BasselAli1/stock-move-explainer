"""Daily trigger job: checks each watched company's price move, and on a
qualifying drop, retrieves relevant filing text, asks an LLM to explain the
move, and emails the result.

CLI entrypoint: `python -m app.jobs.check_triggers`. Intended to run once
daily, after the ingestion job (see app/scheduler.py), so any filing that
dropped today is already searchable before today's price move is checked.
"""

from __future__ import annotations

import logging
import sys
import time

import psycopg
from openai import OpenAI

from app import db
from app.alpha_vantage import get_latest_two_closes
from app.config import Settings, get_settings, load_watchlist
from app.email_sender import send_trigger_email
from app.explain import explain_price_move
from app.retrieval import find_relevant_chunks
from app.trigger import build_search_query, compute_pct_change, is_triggering_drop

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Alpha Vantage's free tier allows only 1 request/second; a fixed pause
# between companies keeps this job comfortably under that limit.
ALPHA_VANTAGE_PACING_SECONDS = 1.5


def check_company(
    conn: psycopg.Connection,
    client: OpenAI,
    ticker: str,
    settings: Settings,
) -> None:
    """Check one watched company's latest price move and act on a trigger.

    Fetches the two most recent daily closes, computes the percent change,
    and records the check (skipping if today was already checked). If the
    move is a qualifying drop (see `trigger.is_triggering_drop`), retrieves
    relevant filing chunks, asks the LLM for a grounded explanation, emails
    the result, and records the trigger event.

    Args:
        conn: Open database connection.
        client: An initialized OpenAI client.
        ticker: Ticker symbol to check.
        settings: Application settings.

    Raises:
        RuntimeError: If no company row exists for this ticker yet — the
            ingestion job must run at least once before the trigger job can
            search anything for it.
    """
    company = db.get_company_by_ticker(conn, ticker)
    if company is None:
        raise RuntimeError(
            f"{ticker!r} has no companies row yet — run the ingestion job first"
        )
    company_id, company_name = company["id"], company["name"]

    latest, previous = get_latest_two_closes(ticker, settings.alpha_vantage_api_key)
    pct_change = compute_pct_change(previous.close, latest.close)

    existing_check = db.get_price_check(conn, company_id, latest.trade_date)
    if existing_check is not None:
        logger.info(
            "%s: %s already checked (pct_change=%.2f%%) — skipping",
            ticker,
            latest.trade_date,
            existing_check["pct_change"],
        )
        return

    triggered = is_triggering_drop(pct_change, settings.price_move_threshold_pct)
    price_check_id = db.insert_price_check(
        conn,
        company_id,
        latest.trade_date,
        previous.close,
        latest.close,
        pct_change,
        triggered,
    )
    logger.info(
        "%s: %.2f -> %.2f (%.2f%%)%s",
        ticker,
        previous.close,
        latest.close,
        pct_change,
        " [TRIGGERED]" if triggered else "",
    )

    if not triggered:
        return

    chunks = find_relevant_chunks(
        conn, client, settings.openai_embedding_model, company_id, company_name
    )
    if not chunks:
        logger.warning(
            "%s: triggered but no filing chunks available (has ingestion run yet?)",
            ticker,
        )

    explanation = explain_price_move(
        client,
        settings.openai_chat_model,
        company_name,
        latest.trade_date,
        previous.close,
        latest.close,
        pct_change,
        chunks,
    )

    email_id = send_trigger_email(
        settings.resend_api_key,
        settings.alert_email_to,
        settings.alert_email_from,
        company_name,
        latest.trade_date,
        previous.close,
        latest.close,
        pct_change,
        explanation,
        chunks,
    )

    db.insert_trigger_event(
        conn,
        company_id,
        price_check_id,
        query_text=build_search_query(company_name),
        explanation=explanation.explanation,
        connection_found=explanation.connection_found,
    )

    logger.info(
        "%s: trigger email sent (id=%s, connection_found=%s)",
        ticker,
        email_id,
        explanation.connection_found,
    )


def run_once() -> list[str]:
    """Run the trigger check once for every company in the watchlist.

    Each company is processed independently: an error checking one company
    is logged and the job moves on to the next, rather than one bad company
    aborting the whole run. Does not raise for a per-company failure and
    does not exit the process — callers decide what a failure should mean
    (a CLI run exits non-zero via `main`; a long-running scheduler just
    logs and waits for tomorrow's run, see app/scheduler.py). A short pause
    is inserted between companies' Alpha Vantage calls to stay under its 1
    request/second free-tier limit.

    Returns:
        Tickers whose check failed this run (empty if all succeeded).
    """
    settings = get_settings()
    tickers = load_watchlist()
    client = OpenAI(api_key=settings.openai_api_key)

    failed_tickers: list[str] = []
    with db.get_connection(settings.database_url) as conn:
        for index, ticker in enumerate(tickers):
            if index > 0:
                time.sleep(ALPHA_VANTAGE_PACING_SECONDS)
            try:
                check_company(conn, client, ticker, settings)
            except Exception:
                logger.exception("%s: trigger check failed", ticker)
                failed_tickers.append(ticker)

    if failed_tickers:
        logger.error("Trigger check finished with failures: %s", failed_tickers)
    else:
        logger.info(
            "Trigger check finished successfully for all %d companies", len(tickers)
        )

    return failed_tickers


def main() -> None:
    """CLI entrypoint: run the trigger check once, exiting non-zero on any
    company failure so a cron/scheduler failure hook can surface it instead
    of it failing silently.
    """
    if run_once():
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Data access layer: connection management and raw SQL for all five tables.

The only module that talks to Postgres directly — jobs and retrieval logic
go through the functions here rather than writing their own SQL. No ORM:
the schema (five small tables, see db/schema.sql) is simple enough that
plain parameterized queries stay readable, and an ORM would add a layer of
indirection this project doesn't need.
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from datetime import date

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row


@contextmanager
def get_connection(database_url: str) -> Generator[psycopg.Connection, None, None]:
    """Open a psycopg connection configured for this app's runtime use.

    Autocommit is enabled so each insert commits immediately, rather than
    the whole caller's work being one giant transaction. Jobs process one
    company/filing at a time and should keep already-saved work even if a
    later item fails — see the "Logging & failure signal" section of the
    plan. The pgvector adapter is also registered here, so Python lists can
    be passed directly as `vector` values in queries.

    Args:
        database_url: Postgres connection string.

    Yields:
        A ready-to-use connection. Closed automatically on exit.
    """
    with psycopg.connect(database_url, autocommit=True) as conn:
        register_vector(conn)
        yield conn


def get_or_create_company(
    conn: psycopg.Connection, ticker: str, name: str, cik: str
) -> int:
    """Insert a company if it doesn't exist yet, or refresh its name/cik if it does.

    Args:
        conn: Open database connection.
        ticker: Stock ticker symbol (unique key).
        name: Company name, as resolved from SEC.
        cik: SEC Central Index Key, as resolved from SEC.

    Returns:
        The company's `id`, whether newly inserted or already present.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO companies (ticker, name, cik)
            VALUES (%s, %s, %s)
            ON CONFLICT (ticker) DO UPDATE SET name = EXCLUDED.name, cik = EXCLUDED.cik
            RETURNING id
            """,
            (ticker, name, cik),
        )
        return cur.fetchone()[0]


def get_company_by_ticker(conn: psycopg.Connection, ticker: str) -> dict | None:
    """Look up an already-ingested company by ticker.

    Used by the trigger job, which expects the ingestion job to have
    already created the company row — unlike ingestion, the trigger job
    doesn't create companies itself, since a company with no ingested
    filings has nothing to search on a trigger.

    Args:
        conn: Open database connection.
        ticker: Ticker symbol to look up.

    Returns:
        A dict with the company's `id` and `name`, or None if no company
        with this ticker has been ingested yet.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, name FROM companies WHERE ticker = %s", (ticker,))
        return cur.fetchone()


def filing_exists(conn: psycopg.Connection, accession_number: str) -> bool:
    """Check whether a filing has already been ingested.

    Args:
        conn: Open database connection.
        accession_number: SEC accession number to look up.

    Returns:
        True if a filings row with this accession_number already exists.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM filings WHERE accession_number = %s)",
            (accession_number,),
        )
        return cur.fetchone()[0]


def insert_filing(
    conn: psycopg.Connection,
    company_id: int,
    accession_number: str,
    form_type: str,
    filing_date: date,
    primary_doc_url: str,
) -> int:
    """Record a newly-ingested SEC filing.

    Args:
        conn: Open database connection.
        company_id: Company the filing belongs to.
        accession_number: SEC accession number (globally unique).
        form_type: Filing form type, e.g. "10-K" or "10-Q".
        filing_date: Date the filing was submitted to SEC.
        primary_doc_url: URL of the filing's primary document.

    Returns:
        The new filings row's `id`.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO filings
                (company_id, accession_number, form_type, filing_date, primary_doc_url)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (company_id, accession_number, form_type, filing_date, primary_doc_url),
        )
        return cur.fetchone()[0]


def insert_filing_chunk(
    conn: psycopg.Connection,
    filing_id: int,
    company_id: int,
    section: str,
    chunk_index: int,
    content: str,
    embedding: Sequence[float],
) -> int:
    """Store one embedded chunk of filing text.

    Args:
        conn: Open database connection.
        filing_id: Filing the chunk was cut from.
        company_id: Denormalized company id, for fast per-company search.
        section: Which section of the filing this chunk came from, e.g.
            "risk_factors".
        chunk_index: Position of this chunk within its section (0-based).
        content: The chunk's raw text.
        embedding: The chunk's embedding vector.

    Returns:
        The new filing_chunks row's `id`.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO filing_chunks
                (filing_id, company_id, section, chunk_index, content, embedding)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (filing_id, company_id, section, chunk_index, content, list(embedding)),
        )
        return cur.fetchone()[0]


def search_similar_chunks(
    conn: psycopg.Connection,
    company_id: int,
    query_embedding: Sequence[float],
    limit: int = 5,
) -> list[dict]:
    """Find the filing chunks most similar to a query embedding, for one company.

    Args:
        conn: Open database connection.
        company_id: Restrict the search to chunks belonging to this company.
        query_embedding: The embedding vector to compare against.
        limit: Maximum number of chunks to return.

    Returns:
        A list of dicts (nearest first), each with the chunk's content and
        its source filing's citation metadata: `content`, `chunk_index`,
        `form_type`, `filing_date`, `primary_doc_url`, and `distance`
        (cosine distance — lower means more similar).
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT
                fc.content,
                fc.chunk_index,
                f.form_type,
                f.filing_date,
                f.primary_doc_url,
                fc.embedding <=> %(query_embedding)s::vector AS distance
            FROM filing_chunks fc
            JOIN filings f ON f.id = fc.filing_id
            WHERE fc.company_id = %(company_id)s
            ORDER BY fc.embedding <=> %(query_embedding)s::vector
            LIMIT %(limit)s
            """,
            {
                "query_embedding": list(query_embedding),
                "company_id": company_id,
                "limit": limit,
            },
        )
        return cur.fetchall()


def get_price_check(
    conn: psycopg.Connection, company_id: int, check_date: date
) -> dict | None:
    """Look up an existing price check for a company on a given date.

    Used to make the trigger job idempotent — if a check already exists for
    today, the job should skip reprocessing rather than send a duplicate
    email.

    Args:
        conn: Open database connection.
        company_id: Company to look up.
        check_date: Trading date to look up.

    Returns:
        A dict of the existing row's fields, or None if no check has been
        recorded for that company/date yet.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, prev_close, curr_close, pct_change, triggered
            FROM price_checks
            WHERE company_id = %s AND check_date = %s
            """,
            (company_id, check_date),
        )
        return cur.fetchone()


def insert_price_check(
    conn: psycopg.Connection,
    company_id: int,
    check_date: date,
    prev_close: float,
    curr_close: float,
    pct_change: float,
    triggered: bool,
) -> int:
    """Record a daily price check for a company.

    Args:
        conn: Open database connection.
        company_id: Company the check is for.
        check_date: Trading date the closes correspond to.
        prev_close: Previous trading day's closing price.
        curr_close: Current trading day's closing price.
        pct_change: Percent change from prev_close to curr_close.
        triggered: Whether the move exceeded the configured threshold.

    Returns:
        The new price_checks row's `id`.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO price_checks
                (company_id, check_date, prev_close, curr_close, pct_change, triggered)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (company_id, check_date, prev_close, curr_close, pct_change, triggered),
        )
        return cur.fetchone()[0]


def insert_trigger_event(
    conn: psycopg.Connection,
    company_id: int,
    price_check_id: int,
    query_text: str,
    explanation: str,
    connection_found: bool,
) -> int:
    """Record that a trigger fired and what was searched/explained/sent.

    Args:
        conn: Open database connection.
        company_id: Company the trigger fired for.
        price_check_id: The price_checks row that caused this trigger.
        query_text: The fixed search query used for retrieval.
        explanation: The LLM's plain-language explanation.
        connection_found: Whether the LLM found a grounded connection.

    Returns:
        The new trigger_events row's `id`.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO trigger_events
                (company_id, price_check_id, query_text, explanation, connection_found)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (company_id, price_check_id, query_text, explanation, connection_found),
        )
        return cur.fetchone()[0]

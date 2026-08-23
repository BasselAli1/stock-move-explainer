"""Retrieval: finds a company's filing chunks most relevant to a price move.

Combines the fixed search query (`app.trigger.build_search_query`), the
embedding adapter (`app.embeddings`), and the pgvector similarity search
(`app.db.search_similar_chunks`) into the single step the trigger job calls.
No AI beyond the embedding call — the query itself is fixed, code-written
text (per SPEC.md), and ranking is a database operation, not a model call.
"""

from __future__ import annotations

import psycopg
from openai import OpenAI

from app.db import search_similar_chunks
from app.embeddings import embed_text
from app.trigger import build_search_query

DEFAULT_TOP_K = 5


def find_relevant_chunks(
    conn: psycopg.Connection,
    client: OpenAI,
    embedding_model: str,
    company_id: int,
    company_name: str,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict]:
    """Find the filing chunks most relevant to a triggered price move.

    Builds the fixed search query for this company, embeds it, and runs a
    pgvector similarity search scoped to the company's own filing chunks.

    Args:
        conn: Open database connection.
        client: An initialized OpenAI client.
        embedding_model: Embedding model name, e.g. "text-embedding-3-small".
        company_id: Company whose filing chunks to search.
        company_name: Company name, used to build the search query.
        top_k: Maximum number of chunks to return.

    Returns:
        The top matching chunks (nearest first), as returned by
        `db.search_similar_chunks` — each a dict with `content`,
        `chunk_index`, `form_type`, `filing_date`, `primary_doc_url`, and
        `distance`.
    """
    query = build_search_query(company_name)
    query_embedding = embed_text(query, client, embedding_model)
    return search_similar_chunks(conn, company_id, query_embedding, limit=top_k)

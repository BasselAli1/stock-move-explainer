-- Stock Move Explainer — database schema.
--
-- Five tables: companies (the watchlist), filings + filing_chunks (SEC
-- filing text and its embeddings), and price_checks + trigger_events (daily
-- price-move detection and what was sent when a trigger fired).
--
-- Requires the pgvector extension (available on Neon by default).
-- Apply with: python scripts/init_db.py

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE companies (
    id         BIGSERIAL PRIMARY KEY,
    ticker     TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    cik        TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE companies IS
    'Watched companies. One row per ticker; name and cik are resolved from '
    'SEC''s company_tickers.json, not hand-entered.';

CREATE TABLE filings (
    id                BIGSERIAL PRIMARY KEY,
    company_id        BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    accession_number  TEXT NOT NULL UNIQUE,
    form_type         TEXT NOT NULL,
    filing_date       DATE NOT NULL,
    primary_doc_url   TEXT NOT NULL,
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE filings IS
    'SEC filings (10-K/10-Q) already processed by the ingestion job. '
    'accession_number is globally unique per SEC and is the dedup key that '
    'stops a filing from being re-ingested.';

CREATE INDEX filings_company_id_idx ON filings(company_id);

CREATE TABLE filing_chunks (
    id          BIGSERIAL PRIMARY KEY,
    filing_id   BIGINT NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    company_id  BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    section     TEXT NOT NULL,
    chunk_index INT NOT NULL,
    content     TEXT NOT NULL,
    embedding   VECTOR(1536) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE filing_chunks IS
    'Chunked, embedded Risk Factors text from filings. company_id is '
    'denormalized from filings so trigger-time similarity search can scope '
    'to one company without a join. embedding uses OpenAI '
    'text-embedding-3-small (1536 dimensions).';

CREATE INDEX filing_chunks_company_id_idx ON filing_chunks(company_id);

-- HNSW index for cosine-similarity search (pgvector's <=> operator).
CREATE INDEX filing_chunks_embedding_hnsw_idx
    ON filing_chunks
    USING hnsw (embedding vector_cosine_ops);

CREATE TABLE price_checks (
    id          BIGSERIAL PRIMARY KEY,
    company_id  BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    check_date  DATE NOT NULL,
    prev_close  NUMERIC(12, 4) NOT NULL,
    curr_close  NUMERIC(12, 4) NOT NULL,
    pct_change  NUMERIC(8, 4) NOT NULL,
    triggered   BOOLEAN NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (company_id, check_date)
);

COMMENT ON TABLE price_checks IS
    'One row per company per trading day the trigger job ran. The unique '
    '(company_id, check_date) constraint makes the job idempotent — a rerun '
    'on the same day is a no-op instead of double-processing.';

CREATE INDEX price_checks_company_id_idx ON price_checks(company_id);

CREATE TABLE trigger_events (
    id                BIGSERIAL PRIMARY KEY,
    company_id        BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    price_check_id    BIGINT NOT NULL REFERENCES price_checks(id) ON DELETE CASCADE,
    query_text        TEXT NOT NULL,
    explanation       TEXT NOT NULL,
    connection_found  BOOLEAN NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE trigger_events IS
    'Audit trail of triggered price moves: the search query used, the '
    'LLM''s explanation, whether it found a grounded connection, and when '
    'the alert email was sent.';

CREATE INDEX trigger_events_company_id_idx ON trigger_events(company_id);

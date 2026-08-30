# Stock Move Explainer

[![CI](https://github.com/BasselAli1/stock-move-explainer/actions/workflows/ci.yml/badge.svg)](https://github.com/BasselAli1/stock-move-explainer/actions/workflows/ci.yml)

Watches a small list of public companies. When one's stock price drops more
than a set threshold in a day, the app searches that company's own SEC
filings for related risk language and emails a plain-language explanation
grounded only in real filing text, with the exact source passage included
so the explanation is checkable, not just a claim.

Full spec and the design decisions made while building it: [SPEC.md](SPEC.md).

## Architecture

A layered pipeline: no web framework, no ORM. Four layers, each depending
only on the ones below it:

1. **Adapters** (`app/sec_edgar.py`, `app/alpha_vantage.py`,
   `app/embeddings.py`, `app/explain.py`, `app/email_sender.py`): one thin
   module per external service.
2. **Domain logic** (`app/risk_factors.py`, `app/chunking.py`,
   `app/trigger.py`): pure functions, no network or DB calls.
3. **Data access** (`app/db.py`): the only module that talks to Postgres
   directly.
4. **Orchestration** (`app/jobs/ingest.py`, `app/jobs/check_triggers.py`):
   wires the above into the two daily jobs. `app/scheduler.py` optionally
   runs both on a schedule.

Database schema and how the tables connect: [db/ERD.md](db/ERD.md) and
[db/example_data.md](db/example_data.md).

## Setup

**Prerequisites:** Python 3.11+, [uv](https://docs.astral.sh/uv/), a
[Neon](https://neon.tech) Postgres project (pgvector enabled), and API keys
for Alpha Vantage, OpenAI, and Resend.

1. Create the virtual environment and install dependencies:

   ```
   uv venv
   uv pip install -e ".[dev]"
   ```

2. Copy `.env.example` to `.env` and fill in:
   - `DATABASE_URL`: your Neon connection string.
   - `ALPHA_VANTAGE_API_KEY`, `OPENAI_API_KEY`, `RESEND_API_KEY`.
   - `SEC_USER_AGENT`: an identifying string SEC requires on every
     request, e.g. `"Your Name you@example.com"` (not an API key, SEC
     doesn't issue those).
   - `ALERT_EMAIL_TO` / `ALERT_EMAIL_FROM`: where alerts are sent from/to.
     `ALERT_EMAIL_FROM` must be on a domain verified with Resend, or their
     sandbox sender `onboarding@resend.dev` (which can only send to the
     email your Resend account itself signed up with).

3. Apply the database schema:

   ```
   .venv/bin/python scripts/init_db.py
   ```

4. Edit `config/watchlist.yaml` to set which tickers to watch. Company
   name and CIK are resolved automatically from SEC, no need to look them
   up.

## Running the jobs

```
.venv/bin/python -m app.jobs.ingest            # pull new filings, embed, store
.venv/bin/python -m app.jobs.check_triggers    # check prices, email on a qualifying drop
```

Both are idempotent: rerunning either the same day is safe (already-seen
filings and already-checked days are skipped, not reprocessed).

**Scheduling** (pick one):

- System cron, e.g.:
  ```
  0 6  * * * cd /path/to/stocks && .venv/bin/python -m app.jobs.ingest
  0 17 * * * cd /path/to/stocks && .venv/bin/python -m app.jobs.check_triggers
  ```
- Or the bundled scheduler, a single long-running process (same schedule,
  no cron needed):
  ```
  .venv/bin/python -m app.scheduler
  ```

## Testing

```
.venv/bin/pytest tests/              # unit tests, no credentials needed
.venv/bin/python evals/run_evals.py  # grounding eval, real OpenAI calls
```

Unit tests cover the pure domain-logic functions and run in CI on every
push (`.github/workflows/ci.yml`). The grounding eval sanity-checks the
one LLM call in the system (`app/explain.py`) against hand-written cases.
It costs real API calls, so it's run manually, not in CI.

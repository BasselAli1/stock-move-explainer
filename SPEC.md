# Project: Stock Move Explainer

An app that watches a small list of public companies. When a stock's price
jumps a lot in a day, the app searches that company's past SEC filings for
related language, then emails a plain-language explanation, grounded only
in real filing text.

## Data sources (two real APIs)

- **SEC EDGAR** — company filings (10-K, 10-Q), specifically the "Risk
  Factors" section
- **Alpha Vantage** — daily stock price data

## Ingestion (background job)

- Runs daily, not weekly, since filings don't come out on a fixed schedule
- Checks EDGAR for any new filing for each watched company
- If a new filing is found, pull the Risk Factors section, split into
  chunks, generate embeddings, store in a vector database (Postgres with
  pgvector)

## Trigger (event check, also daily)

- Pull yesterday's and today's closing price per company from Alpha Vantage
- If the price moved more than a set threshold (example 5 percent), mark
  it as a trigger

## On trigger

- Build a fixed, code-written search query (no LLM needed here), example:
  "reasons for stock volatility, risk factors, {company name}"
- Turn that query into an embedding using an embedding model (not a full
  LLM)
- Run a similarity search against the stored filing chunks for that
  company, take the top few matches
- Send only those matched chunks, plus the price move, to an LLM, and ask
  it to explain the move using only that retrieved text, and say "no clear
  connection found" if nothing fits
- Send the result by email, including which exact filing passage it used,
  so the explanation is checkable, not just a claim

## Where AI is actually needed, and where it's not

- Exact keyword or ID lookups: no AI, plain code
- Turning filing text and the search query into embeddings: embedding
  model, not a full LLM
- Explaining a fuzzy, unlabeled connection between a price move and filing
  language in plain English: this is the one place a real LLM adds value

## Stack

- Postgres + pgvector for storage and search
- A scheduler (cron or APScheduler) for the daily jobs
- Any embedding model (OpenAI text-embedding-3-small or an open-source
  alternative)
- Any LLM for the final explanation step
- Email via Resend, SendGrid, or plain SMTP

---

## Decisions made during planning and implementation

The spec above left several choices open; these were decided in
conversation with the project owner and are reflected in the code, not just
here:

- **Language/stack**: Python, with Neon Postgres (pgvector enabled) instead
  of local Docker Postgres, OpenAI for both embeddings
  (`text-embedding-3-small`) and the explanation step (`gpt-5.6-luna`), and
  Resend for email. No FastAPI/web layer — this is a headless background-job
  app, matching the spec as written.
- **Architecture**: a layered pipeline (adapters → domain logic → data
  access → orchestration), not a web framework or ORM — see the plan file
  and each module's own docstring for the reasoning.
- **Trigger direction — drops only, not jumps**: the price-move trigger only
  fires on a decline of at least the threshold, not a rise. Risk Factors
  text exclusively describes things that could hurt a company — there's no
  equivalent "positive catalysts" section — so it has nothing plausible to
  ground an explanation for an upward jump. Triggering on jumps would
  almost always just produce "no clear connection found," wasting an LLM
  call on a case the data source structurally can't answer. See
  `app/trigger.py`'s `is_triggering_drop`.
- **Query relevance is inherently approximate**: the fixed search query
  carries no information about what actually caused a given move (that
  isn't knowable from code without a news data source, which is out of
  scope). Retrieval surfaces a company's own most volatility-framed risk
  language, not necessarily today's real cause — the LLM explanation step,
  with permission to say "no clear connection found," is the actual
  correctness backstop, not the similarity ranking.

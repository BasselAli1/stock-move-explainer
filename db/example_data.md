# Example Data

One sample row per table, showing the shape of the data and how the rows
connect via foreign keys. Illustrative only (not real filing/price data) —
see `db/ERD.md` for how these tables relate.

## companies (1 row)

- id: 1
- ticker: AAPL
- name: Apple Inc.
- cik: 0000320193
- created_at: 2024-08-02 09:00:00+00

## filings (1 row)

- id: 1
- company_id: 1
- accession_number: 0000320193-24-000123
- form_type: 10-Q
- filing_date: 2024-08-02
- primary_doc_url: https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240629.htm
- ingested_at: 2024-08-02 09:05:00+00

## filing_chunks (1 row)

- id: 1
- filing_id: 1
- company_id: 1
- section: risk_factors
- chunk_index: 0
- content: "The Company's business, reputation, results of operations and
  financial condition have been and could in the future be materially
  adversely affected by ... slower growth or recession, which could reduce
  consumer spending on the Company's products."
- embedding: (1536-dim vector, omitted)
- created_at: 2024-08-02 09:06:00+00

## price_checks (1 row)

- id: 1
- company_id: 1
- check_date: 2024-08-02
- prev_close: 220.00
- curr_close: 205.50
- pct_change: -6.59
- triggered: true
- created_at: 2024-08-02 17:00:00+00

## trigger_events (1 row)

- id: 1
- company_id: 1
- price_check_id: 1
- query_text: "reasons for stock volatility, risk factors, Apple Inc."
- explanation: "The 6.6% drop may relate to macroeconomic pressure the
  company flagged in its most recent 10-Q: ... No stronger match was found
  among the retrieved passages."
- connection_found: true
- created_at: 2024-08-02 17:01:00+00

## How the rows connect

Every foreign key below holds the value `1`, because this example has exactly
one row per table — all pointing back to the same company.

| Foreign key                      | Points to      | Why                                                              |
|-----------------------------------|-----------------|-------------------------------------------------------------------|
| `filings.company_id`              | `companies.id`  | this filing belongs to Apple                                     |
| `filing_chunks.filing_id`         | `filings.id`    | this chunk was cut from the 10-Q                                 |
| `filing_chunks.company_id`        | `companies.id`  | denormalized copy, so chunk search can filter by company directly |
| `price_checks.company_id`         | `companies.id`  | this price check is for Apple                                    |
| `trigger_events.price_check_id`   | `price_checks.id` | this email was triggered by that price check                  |
| `trigger_events.company_id`       | `companies.id`  | denormalized copy, same reasoning as `filing_chunks.company_id`   |

Chain from a single filing to the alert it eventually caused:

```
companies (id=1)
  -> filings (company_id=1, id=1)
       -> filing_chunks (filing_id=1)
  -> price_checks (company_id=1, id=1)
       -> trigger_events (price_check_id=1)
```

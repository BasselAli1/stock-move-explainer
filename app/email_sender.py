"""Email adapter: formats and sends the trigger alert via Resend.

The email is the final, user-facing deliverable of the whole pipeline: the
LLM's explanation, plus the full text of every retrieved filing chunk with
its source citation — included regardless of what the LLM chose to cite,
so the explanation is checkable by the reader, not just a claim (per
SPEC.md).
"""

from __future__ import annotations

from datetime import date
from html import escape

import resend

from app.explain import Explanation


def _is_cited(chunk_content: str, cited_passages: list[str]) -> bool:
    """Check whether any of the model's cited passages appear in a chunk.

    Args:
        chunk_content: The full text of one retrieved filing chunk.
        cited_passages: Exact quotes the model claimed to rely on.

    Returns:
        True if at least one cited passage is a substring of chunk_content.
    """
    return any(passage in chunk_content for passage in cited_passages if passage)


def build_email_html(
    company_name: str,
    check_date: date,
    prev_close: float,
    curr_close: float,
    pct_change: float,
    explanation: Explanation,
    chunks: list[dict],
) -> str:
    """Build the trigger alert email body as HTML.

    Args:
        company_name: The company's name.
        check_date: The trading date the price move occurred on.
        prev_close: Previous trading day's closing price.
        curr_close: Current trading day's closing price.
        pct_change: Percent change from prev_close to curr_close (always
            negative — the trigger only fires on drops).
        explanation: The LLM's grounded explanation.
        chunks: The candidate filing chunks that were retrieved and sent to
            the LLM, each with `content`, `form_type`, `filing_date`, and
            `primary_doc_url`.

    Returns:
        A self-contained HTML email body. All filing/LLM-derived text is
        HTML-escaped before being embedded, since it originates outside
        this app's control.
    """
    passage_items = []
    for chunk in chunks:
        cited = _is_cited(chunk["content"], explanation.cited_passages)
        badge = (
            '<strong style="color: #1a7f37;">[Cited in explanation]</strong> '
            if cited
            else ""
        )
        passage_items.append(
            "<li>"
            f"{badge}From a {escape(chunk['form_type'])} filed "
            f"{chunk['filing_date'].isoformat()} "
            f'(<a href="{escape(chunk["primary_doc_url"])}">source filing</a>):'
            f"<blockquote>{escape(chunk['content'])}</blockquote>"
            "</li>"
        )

    return f"""
<h2>Stock Move Alert: {escape(company_name)}</h2>
<p>
  <strong>Date:</strong> {check_date.isoformat()}<br>
  <strong>Previous close:</strong> ${prev_close:.2f}<br>
  <strong>Current close:</strong> ${curr_close:.2f}<br>
  <strong>Change:</strong> {pct_change:.2f}%
</p>

<h3>Explanation</h3>
<p>{escape(explanation.explanation)}</p>

<h3>Source passages retrieved from SEC filings</h3>
<p>
  These are the exact excerpts the system searched to produce the
  explanation above, so you can verify it yourself rather than taking it
  on faith.
</p>
<ol>
{''.join(passage_items)}
</ol>
""".strip()


def send_trigger_email(
    resend_api_key: str,
    to_email: str,
    from_email: str,
    company_name: str,
    check_date: date,
    prev_close: float,
    curr_close: float,
    pct_change: float,
    explanation: Explanation,
    chunks: list[dict],
) -> str:
    """Send the trigger alert email via Resend.

    Args:
        resend_api_key: Resend API key.
        to_email: Recipient address.
        from_email: Verified sender address.
        company_name: The company's name.
        check_date: The trading date the price move occurred on.
        prev_close: Previous trading day's closing price.
        curr_close: Current trading day's closing price.
        pct_change: Percent change from prev_close to curr_close.
        explanation: The LLM's grounded explanation.
        chunks: The candidate filing chunks that were retrieved and sent to
            the LLM.

    Returns:
        The Resend-assigned email id, for logging/troubleshooting.

    Raises:
        resend.exceptions.ResendError: If the send request fails.
    """
    resend.api_key = resend_api_key

    subject = f"{company_name} dropped {abs(pct_change):.1f}% — Stock Move Explainer"
    html = build_email_html(
        company_name,
        check_date,
        prev_close,
        curr_close,
        pct_change,
        explanation,
        chunks,
    )

    result = resend.Emails.send(
        {
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "html": html,
        }
    )
    return result["id"]

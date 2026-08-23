"""Trigger detection: pure price-move math and the fixed search query.

Pure number/text-in, number/text-out domain logic — no network, no AI. This
is where "did the price move enough to count as a trigger" is decided, and
where the search query sent to retrieval is built. No LLM is used for
either: the threshold check is arithmetic, and the search query is a fixed,
code-written string per the spec.
"""

from __future__ import annotations


def compute_pct_change(prev_close: float, curr_close: float) -> float:
    """Compute the percent change between two consecutive closing prices.

    Args:
        prev_close: The earlier trading day's closing price.
        curr_close: The later trading day's closing price.

    Returns:
        The percent change from prev_close to curr_close (negative for a
        drop, positive for a rise).

    Raises:
        ValueError: If prev_close is not positive (a percent change against
            a zero or negative price is undefined).
    """
    if prev_close <= 0:
        raise ValueError(f"prev_close must be positive, got {prev_close!r}")
    return (curr_close - prev_close) / prev_close * 100


def is_triggering_drop(pct_change: float, threshold_pct: float) -> bool:
    """Decide whether a price move counts as a trigger.

    Only drops count as triggers — Risk Factors text describes things that
    could hurt a company, not things that could help it, so it has nothing
    plausible to say about an upward jump. See the plan's Trigger job
    section for the full reasoning behind this decision.

    Args:
        pct_change: Percent change from the previous close to the current
            close, as returned by `compute_pct_change`.
        threshold_pct: Minimum absolute move, in percent, that counts as a
            trigger (e.g. 5 for a 5% threshold).

    Returns:
        True if `pct_change` is a drop of at least `threshold_pct`.
    """
    return pct_change <= -threshold_pct


def build_search_query(company_name: str) -> str:
    """Build the fixed search query used to retrieve relevant filing chunks.

    Deliberately simple and code-written, not LLM-generated — see the
    spec's "where AI is/isn't needed" section. The query intentionally
    carries no information about what actually caused the move (that isn't
    knowable from code); it exists to bias retrieval toward a company's own
    most volatility/stock-price-framed risk language.

    Args:
        company_name: The company's name, as resolved from SEC.

    Returns:
        The fixed search query string for this company.
    """
    return f"reasons for stock volatility, risk factors, {company_name}"

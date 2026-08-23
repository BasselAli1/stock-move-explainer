"""Tests for app.trigger.build_search_query.

The query is deliberately fixed and code-written, not LLM-generated (see
SPEC.md's "where AI is/isn't needed" section) — these tests exist mainly to
pin down its exact wording so a future edit can't silently change it.
"""

from app.trigger import build_search_query


def test_query_matches_the_exact_spec_wording():
    """The query format must match SPEC.md's example verbatim, with the
    company name substituted in."""
    assert (
        build_search_query("Apple Inc.")
        == "reasons for stock volatility, risk factors, Apple Inc."
    )


def test_query_includes_the_given_company_name_unmodified():
    """The company name is inserted as-is, including punctuation."""
    query = build_search_query("AT&T Inc.")
    assert "AT&T Inc." in query


def test_query_is_identical_for_the_same_company_every_call():
    """The query is a pure function of the company name — no randomness or
    hidden state, so it's safe to call repeatedly (see the embeddings.py
    caching discussion in SPEC.md/conversation history: this determinism is
    exactly why re-embedding it each time is redundant, not risky)."""
    assert build_search_query("NVIDIA CORP") == build_search_query("NVIDIA CORP")

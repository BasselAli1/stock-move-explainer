"""Tests for app.risk_factors.extract_risk_factors.

Several of these cases encode real bugs found while ingesting actual SEC
filings this project watches (see git history / SPEC.md) — they exist so
those specific failures can never silently come back.
"""

from app.risk_factors import extract_risk_factors


def test_returns_none_when_no_heading_present():
    """A document with no "Item 1A. Risk Factors" heading at all yields None."""
    text = "Item 1. Business\n\nWe make widgets.\n\nItem 2. Properties\n\nWe own a factory."
    assert extract_risk_factors(text) is None


def test_prefers_real_section_over_table_of_contents_entry():
    """The short Table of Contents line must lose to the real, longer section."""
    real_content = "Our business faces many risks. " * 20
    text = (
        "TABLE OF CONTENTS\n"
        "Item 1A. Risk Factors 14\n"
        "Item 1B. Unresolved Staff Comments 20\n"
        "\n"
        "PART I\n"
        "Item 1A. Risk Factors\n"
        f"{real_content}\n"
        "Item 1B. Unresolved Staff Comments\n"
        "We have none.\n"
    )
    result = extract_risk_factors(text)
    assert result is not None
    assert "Our business faces many risks." in result
    assert "Unresolved Staff Comments" not in result
    assert "TABLE OF CONTENTS" not in result


def test_returns_none_when_only_a_toc_entry_is_found():
    """A lone short ToC-sized match, with nothing longer, is rejected as noise."""
    text = "Item 1A. Risk Factors 14\nItem 1B. Unresolved Staff Comments 20\n"
    assert extract_risk_factors(text) is None


def test_accepts_a_short_but_genuine_referral_section():
    """A real 10-Q "no material changes" referral is short but still genuine."""
    referral = (
        "There have been no material changes to the risk factors disclosed "
        "in Part I, Item 1A, \"Risk Factors,\" of the Annual Report on Form 10-K."
    )
    text = f"Item 1A. Risk Factors\n{referral}\nItem 2. Unregistered Sales\nNone.\n"
    result = extract_risk_factors(text)
    assert result is not None
    assert "no material changes" in result


def test_tolerates_a_heading_word_split_by_a_page_break_artifact():
    """Regression test: MSFT's real 10-K had 'RISK' itself split across a
    stray newline where a page-header element was stripped mid-word
    ("...ITEM 1A. RIS\\nK FACTORS...")."""
    real_content = "Our operations face various risks and uncertainties. " * 10
    text = (
        "Item 1A. Risk Factors 14\n"
        "Item 1B. Unresolved Staff Comments 20\n"
        "\n"
        "ITEM 1A. RIS\nK FACTORS\n"
        f"{real_content}\n"
        "Item 1B. Unresolved Staff Comments\n"
        "None.\n"
    )
    result = extract_risk_factors(text)
    assert result is not None
    assert "Our operations face various risks" in result


def test_skips_repeated_same_number_running_header_when_finding_the_end():
    """Regression test: MSFT's real 10-K repeats a running "Item 1A" page
    header throughout the section itself; the end boundary must skip those
    and stop only at a genuinely different item number."""
    text = (
        "Item 1A. Risk Factors 14\n"
        "Item 1B. Unresolved Staff Comments 90\n"
        "\n"
        "Item 1A. Risk Factors\n"
        "First risk paragraph with real detail here. " * 5 + "\n"
        "\n14\n\nPART I\nItem 1A\n\n"
        "Second risk paragraph, on the next page, also with real detail. " * 5 + "\n"
        "\n15\n\nPART I\nItem 1A\n\n"
        "Third risk paragraph, on yet another page. " * 5 + "\n"
        "Item 1B. Unresolved Staff Comments\n"
        "None.\n"
    )
    result = extract_risk_factors(text)
    assert result is not None
    assert "First risk paragraph" in result
    assert "Second risk paragraph" in result
    assert "Third risk paragraph" in result
    assert "Unresolved Staff Comments" not in result


def test_ignores_inline_cross_references_to_item_1a():
    """A mid-sentence reference like "as discussed in Item 1A above" must
    not be mistaken for a heading, since it doesn't start a line."""
    real_content = "Our operations face various risks and uncertainties. " * 10
    text = (
        "Item 1A. Risk Factors 14\n"
        "Item 1B. Unresolved Staff Comments 20\n"
        "\n"
        "Item 1A. Risk Factors\n"
        f"{real_content}\n"
        "As discussed in Item 1A above, our results may vary.\n"
        "Item 1B. Unresolved Staff Comments\n"
        "None.\n"
    )
    result = extract_risk_factors(text)
    assert result is not None
    assert "As discussed in Item 1A above" in result


def test_stops_at_a_different_item_number_not_just_any_heading_word():
    """The end boundary is generic (any "Item N"), not hardcoded to "Item 1B" —
    confirms a 10-Q-style "Item 2" boundary is also respected."""
    real_content = "Risks related to our quarterly results. " * 10
    text = (
        "Item 1A. Risk Factors 14\n"
        "Item 2. Unregistered Sales 20\n"
        "\n"
        "Item 1A. Risk Factors\n"
        f"{real_content}\n"
        "Item 2. Unregistered Sales of Equity Securities\n"
        "None.\n"
    )
    result = extract_risk_factors(text)
    assert result is not None
    assert "quarterly results" in result
    assert "Unregistered Sales" not in result

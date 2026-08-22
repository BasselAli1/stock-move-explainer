"""Risk Factors section extraction: pure text-in, text-out domain logic.

Given a filing's full plain text, finds the "Item 1A. Risk Factors" section
using heading-pattern matching, not page numbers or document structure —
SEC filings are unpaginated HTML with no standardized internal structure,
but every 10-K/10-Q must contain this caption verbatim, so matching on the
heading text is the portable approach across filers. No AI: this is exact
text search.
"""

from __future__ import annotations

import re

# Matches the "Item 1A. Risk Factors" heading in its various real-world
# spellings: optional periods/dashes/colons and whitespace between "1A"
# and "Risk Factors", case-insensitive. Anchored to the start of a line so
# it matches actual headings, not inline cross-references like "as
# discussed in Item 1A above" appearing mid-sentence elsewhere in the text.
_START_PATTERN = re.compile(
    r"^[ \t]*item\s+1a\.{0,2}\s*[-:.]?\s*risk\s+factors", re.IGNORECASE | re.MULTILINE
)

# Matches any "Item N" heading, used to find where the next section begins
# after Risk Factors. Deliberately generic (not "Item 1B" specifically)
# since 10-Ks and 10-Qs number the section following Risk Factors
# differently. Also anchored to line-start, for the same reason as above —
# without it, an in-body reference like "see Item 7A of this report" would
# be mistaken for the next section's heading and truncate the real section
# far too early.
_NEXT_ITEM_PATTERN = re.compile(r"^[ \t]*item\s+\d+[a-z]?\b", re.IGNORECASE | re.MULTILINE)

# A Table of Contents entry pointing to Risk Factors is one short line
# (heading plus a page number); the real section is at minimum a full
# sentence, even in a 10-Q that just says "no material changes." Below
# this length, treat a candidate match as ToC noise, not the real section.
_MIN_SECTION_LENGTH = 100


def extract_risk_factors(filing_text: str) -> str | None:
    """Extract the "Item 1A. Risk Factors" section from a filing's plain text.

    Filings typically mention "Item 1A. Risk Factors" twice: once in a
    Table of Contents entry (a single short line) and once as the real
    section heading (followed by prose — anywhere from one sentence, in a
    10-Q with no material changes, to many paragraphs). This function finds
    every place the heading appears, pairs each with the next "Item N"
    heading after it to get a candidate span, and returns the longest
    candidate — which is reliably the real section, since a ToC-to-ToC gap
    is always short by comparison.

    Args:
        filing_text: The filing's full plain text (HTML already stripped).

    Returns:
        The extracted section text, whitespace-normalized, or None if no
        candidate at least `_MIN_SECTION_LENGTH` characters long was found.
    """
    best_section: str | None = None
    best_length = 0

    for start_match in _START_PATTERN.finditer(filing_text):
        section_start = start_match.end()

        end_match = _NEXT_ITEM_PATTERN.search(filing_text, pos=section_start)
        section_end = end_match.start() if end_match else len(filing_text)

        candidate = filing_text[section_start:section_end]
        if len(candidate) > best_length:
            best_section = candidate
            best_length = len(candidate)

    if best_section is None or best_length < _MIN_SECTION_LENGTH:
        return None

    return _normalize_whitespace(best_section)


def _normalize_whitespace(text: str) -> str:
    """Collapse repeated blank lines/spaces left over from HTML stripping.

    Args:
        text: Raw extracted section text.

    Returns:
        The text with runs of whitespace collapsed to single spaces/blank
        lines, and leading/trailing whitespace removed.
    """
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()

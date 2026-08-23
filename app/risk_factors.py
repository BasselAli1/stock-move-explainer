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


def _loose(word: str) -> str:
    """Build a regex fragment matching `word` with optional whitespace
    tolerated between any two of its letters.

    Some filers' HTML puts a page-number/running-header element (e.g. a
    repeated "PART I / Item 1A" footer) between two adjacent inline text
    nodes with no space in the source markup. Once stripped to plain text
    (see sec_edgar.fetch_filing_document), that boundary becomes a bare
    newline wherever it happened to fall — including, in one real filing
    this was found against, in the middle of the word "RISK" itself
    ("...ITEM 1A. RIS\nK FACTORS..."). A literal `r"risk"` would never
    match that. This only needs to be used for the fixed heading vocabulary
    ("item", "risk", "factors"), not body prose, so the added looseness is
    narrowly scoped.

    Args:
        word: The literal word to build a tolerant pattern for.

    Returns:
        A regex fragment matching `word`'s letters in order, each
        optionally separated by whitespace.
    """
    return r"\s*".join(word)


_ITEM = _loose("item")
_RISK = _loose("risk")
_FACTORS = _loose("factors")

# Matches the "Item 1A. Risk Factors" heading in its various real-world
# spellings: optional periods/dashes/colons and whitespace between "1A"
# and "Risk Factors", case-insensitive, and (via _loose) tolerant of a
# stray newline landing inside one of these words. Anchored to the start
# of a line so it matches actual headings, not inline cross-references
# like "as discussed in Item 1A above" appearing mid-sentence elsewhere in
# the text.
_START_PATTERN = re.compile(
    rf"^[ \t]*{_ITEM}\s+1\s*a\.{{0,2}}\s*[-:.]?\s*{_RISK}\s+{_FACTORS}",
    re.IGNORECASE | re.MULTILINE,
)

# Matches any "Item N" heading, capturing its number/letter, used to find
# where the next section begins after Risk Factors. Deliberately generic
# (not "Item 1B" specifically) since 10-Ks and 10-Qs number the section
# following Risk Factors differently. Also anchored to line-start, for the
# same reason as the pattern above — without it, an in-body reference like
# "see Item 7A of this report" would be mistaken for the next section's
# heading and truncate the real section far too early. The line-start
# anchor plus the requirement that a bare number immediately follows keeps
# this narrow despite the loosened "item".
#
# Matching on ANY item number isn't quite enough, though: multi-page
# filings often repeat a running "Item 1A" header/footer on every page
# within the Risk Factors section itself (a "you are here" marker), which
# would otherwise be mistaken for the boundary of a *different* section on
# its very first repeat. The captured group lets extract_risk_factors skip
# repeats of "1A" and stop only at a genuinely different item number.
_ITEM_HEADING_PATTERN = re.compile(
    rf"^[ \t]*{_ITEM}\s+(\d+[a-z]?)\b", re.IGNORECASE | re.MULTILINE
)

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
    every place the heading appears, pairs each with the next *differently
    numbered* "Item N" heading after it (skipping over repeated "Item 1A"
    running headers within the section itself) to get a candidate span, and
    returns the longest candidate — which is reliably the real section,
    since a ToC-to-ToC gap is always short by comparison.

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

        section_end = len(filing_text)
        for heading_match in _ITEM_HEADING_PATTERN.finditer(filing_text, pos=section_start):
            if heading_match.group(1).lower() != "1a":
                section_end = heading_match.start()
                break

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

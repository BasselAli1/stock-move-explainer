"""Tests for app.chunking.split_into_chunks."""

import pytest

from app.chunking import _ENCODING, split_into_chunks


def test_empty_text_returns_no_chunks():
    """Empty input produces an empty list, not a list with one empty chunk."""
    assert split_into_chunks("") == []


def test_whitespace_only_text_returns_no_chunks():
    """Text that's only blank lines has no real paragraphs to chunk."""
    assert split_into_chunks("   \n\n  \n\n   ") == []


def test_single_short_paragraph_becomes_one_chunk():
    """A paragraph well under the chunk size stays as a single chunk."""
    text = "This is a short risk factor paragraph."
    chunks = split_into_chunks(text)
    assert chunks == [text]


def test_multiple_small_paragraphs_are_packed_together():
    """Several short paragraphs that fit within the size limit merge into
    one chunk instead of each becoming its own tiny chunk."""
    text = "First short paragraph.\n\nSecond short paragraph.\n\nThird short paragraph."
    chunks = split_into_chunks(text, chunk_size_tokens=300, overlap_tokens=50)
    assert len(chunks) == 1
    assert "First short paragraph." in chunks[0]
    assert "Third short paragraph." in chunks[0]


def test_long_text_splits_into_multiple_chunks_within_size_limit():
    """Text well over the chunk size limit produces more than one chunk,
    each within the requested token budget."""
    paragraphs = [f"This is risk paragraph number {i} with some detail. " * 5 for i in range(20)]
    text = "\n\n".join(paragraphs)
    chunks = split_into_chunks(text, chunk_size_tokens=100, overlap_tokens=20)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(_ENCODING.encode(chunk)) <= 100


def test_consecutive_chunks_share_overlapping_text():
    """Each chunk after the first repeats some of the previous chunk's
    trailing text, so a sentence near a boundary isn't orphaned from its
    context in either chunk.

    Compares the actual returned strings, not re-encoded token IDs: BPE
    tokenizers aren't guaranteed to round-trip through decode-then-re-encode
    identically (a merge can span what were originally two separately
    encoded pieces), so token-ID equality on the *output* isn't a real
    contract of this function — the shared text is.
    """
    paragraphs = [f"This is risk paragraph number {i} with some detail. " * 5 for i in range(20)]
    text = "\n\n".join(paragraphs)
    chunks = split_into_chunks(text, chunk_size_tokens=100, overlap_tokens=20)
    assert len(chunks) >= 2

    tail_of_first = chunks[0][-60:]
    assert tail_of_first in chunks[1]


def test_oversized_single_paragraph_is_force_split():
    """A single paragraph with no blank lines, larger than the chunk size,
    still gets split rather than becoming one oversized chunk."""
    text = "word " * 1000
    chunks = split_into_chunks(text, chunk_size_tokens=300, overlap_tokens=50)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(_ENCODING.encode(chunk)) <= 300


def test_overlap_not_smaller_than_chunk_size_raises():
    """overlap_tokens must be strictly smaller than chunk_size_tokens, or
    the sliding window would never advance."""
    with pytest.raises(ValueError):
        split_into_chunks("some text", chunk_size_tokens=10, overlap_tokens=10)

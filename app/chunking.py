"""Chunking: splits extracted filing text into embeddable pieces.

Pure text-in, text-out domain logic — no network, no AI. A filing's Risk
Factors section is too long to embed as one vector usefully (see the
ingestion job plan), so this module splits it into token-bounded,
paragraph-aware pieces small enough for an embedding model to represent
meaningfully, with a small overlap so a sentence near a chunk boundary
doesn't lose its surrounding context in either piece.
"""

from __future__ import annotations

import tiktoken

# Target chunk size and overlap, in tokens rather than characters — token
# count is what the embedding model actually bills and limits on, so sizing
# by tokens (via tiktoken) is more accurate than sizing by character count.
CHUNK_SIZE_TOKENS = 300
CHUNK_OVERLAP_TOKENS = 50

_ENCODING = tiktoken.get_encoding("cl100k_base")


def split_into_chunks(
    text: str,
    chunk_size_tokens: int = CHUNK_SIZE_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
) -> list[str]:
    """Split text into token-bounded chunks, preferring to break on paragraphs.

    Paragraphs (split on blank lines) are packed into a chunk until adding
    the next one would exceed `chunk_size_tokens`, at which point the chunk
    is flushed and a new one starts — seeded with the last `overlap_tokens`
    tokens of the chunk just flushed, so a sentence split across the
    boundary keeps some context in both chunks. A paragraph that alone
    exceeds `chunk_size_tokens` is force-split on raw token boundaries
    (there's no better break point for a single overlong paragraph); this
    does not carry overlap into the paragraph that follows it.

    Args:
        text: The text to split (already whitespace-normalized).
        chunk_size_tokens: Maximum tokens per chunk.
        overlap_tokens: How many trailing tokens of each chunk to repeat at
            the start of the next chunk. Must be smaller than
            `chunk_size_tokens`.

    Returns:
        A list of chunk strings, in order. Empty input returns an empty list.

    Raises:
        ValueError: If `overlap_tokens` is not smaller than `chunk_size_tokens`.
    """
    if overlap_tokens >= chunk_size_tokens:
        raise ValueError("overlap_tokens must be smaller than chunk_size_tokens")

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current_tokens: list[int] = []

    for paragraph in paragraphs:
        paragraph_tokens = _ENCODING.encode(paragraph)

        # A single paragraph too big for one chunk gets force-split on raw
        # token boundaries. Flush whatever was pending first; this oversized
        # paragraph's windows don't carry overlap into what follows it.
        if len(paragraph_tokens) > chunk_size_tokens:
            if current_tokens:
                chunks.append(_ENCODING.decode(current_tokens))
                current_tokens = []
            step = chunk_size_tokens - overlap_tokens
            for start in range(0, len(paragraph_tokens), step):
                piece = paragraph_tokens[start : start + chunk_size_tokens]
                chunks.append(_ENCODING.decode(piece))
            continue

        if (
            current_tokens
            and len(current_tokens) + len(paragraph_tokens) > chunk_size_tokens
        ):
            chunks.append(_ENCODING.decode(current_tokens))
            current_tokens = (
                current_tokens[-overlap_tokens:] if overlap_tokens > 0 else []
            )

        current_tokens.extend(paragraph_tokens)

    if current_tokens:
        chunks.append(_ENCODING.decode(current_tokens))

    return chunks

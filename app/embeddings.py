"""OpenAI embeddings adapter: turns text into vectors for storage and search.

The only place the embedding model (not a full LLM) is called — used both
to embed filing chunks at ingestion time and to embed the fixed search
query at trigger time, so both sides of the similarity search live in the
same vector space.
"""

from __future__ import annotations

from openai import OpenAI

# OpenAI accepts many inputs per embeddings request but still enforces a
# request size limit; batching in groups well under it means a filing's
# full set of chunks can always be embedded without ever hitting that limit.
MAX_BATCH_SIZE = 100


def embed_texts(texts: list[str], client: OpenAI, model: str) -> list[list[float]]:
    """Embed a batch of texts, returned in the same order they were given.

    Args:
        texts: Texts to embed (e.g. a filing's chunk contents).
        client: An initialized OpenAI client.
        model: Embedding model name, e.g. "text-embedding-3-small".

    Returns:
        One embedding vector per input text, in the same order as `texts`.
        Empty input returns an empty list without making an API call.

    Raises:
        openai.OpenAIError: If the API call fails.
    """
    if not texts:
        return []

    vectors: list[list[float]] = []
    for start in range(0, len(texts), MAX_BATCH_SIZE):
        batch = texts[start : start + MAX_BATCH_SIZE]
        response = client.embeddings.create(model=model, input=batch)
        # Sort by the API's own index rather than trusting response order,
        # even though OpenAI documents it as already input-order-preserving.
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors.extend(item.embedding for item in ordered)

    return vectors


def embed_text(text: str, client: OpenAI, model: str) -> list[float]:
    """Embed a single text, e.g. the fixed search query at trigger time.

    Args:
        text: Text to embed.
        client: An initialized OpenAI client.
        model: Embedding model name, e.g. "text-embedding-3-small".

    Returns:
        The text's embedding vector.

    Raises:
        openai.OpenAIError: If the API call fails.
    """
    return embed_texts([text], client, model)[0]

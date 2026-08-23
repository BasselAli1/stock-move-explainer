"""Explanation: the one LLM call in the system.

Sends a triggered price move plus the filing chunks retrieval found to an
LLM, and asks it to explain the move in plain English using only that
retrieved text — never outside knowledge — and to say so honestly when
nothing in the retrieved text plausibly explains the move. This is the
single place in the whole pipeline where a full LLM (not just an embedding
model) is used; see SPEC.md's "where AI is actually needed" section.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from openai import OpenAI

_SYSTEM_PROMPT = """\
You are a financial analyst assistant. You will be given a company's stock \
price move and several excerpts from that company's own SEC risk factor \
filings. Explain the price move in plain English using ONLY the text in \
the excerpts provided to you — never use outside knowledge, never \
speculate about causes not present in the excerpts, and never invent or \
paraphrase facts the excerpts don't state.

If, and only if, one or more excerpts plausibly relate to this price move, \
set "connection_found" to true, write a short plain-English explanation \
that only references facts present in the excerpts, and quote the exact \
sentence(s) you relied on in "cited_passages" (each entry must be an exact \
substring of one of the excerpts, not a paraphrase).

If none of the excerpts plausibly explain the move, set "connection_found" \
to false, set "explanation" to exactly "No clear connection found in \
recent filings.", and set "cited_passages" to an empty list. Do not force \
a connection that isn't really there.
"""

# Structured Outputs schema (gpt-5.6-luna supports JSON-schema structured
# outputs) — "strict": True makes the API itself guarantee the response
# matches this shape exactly, rather than relying on the model to follow
# formatting instructions in the prompt.
_RESPONSE_JSON_SCHEMA = {
    "name": "price_move_explanation",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "connection_found": {"type": "boolean"},
            "explanation": {"type": "string"},
            "cited_passages": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["connection_found", "explanation", "cited_passages"],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class Explanation:
    """The LLM's grounded explanation of a triggered price move.

    Attributes:
        connection_found: Whether the model found a plausible connection
            between the price move and the retrieved filing text.
        explanation: The plain-English explanation, or the fixed "no clear
            connection" message if connection_found is False.
        cited_passages: Exact quotes from the retrieved chunks the model
            relied on. Empty if connection_found is False.
    """

    connection_found: bool
    explanation: str
    cited_passages: list[str]


def _build_user_prompt(
    company_name: str,
    check_date: date,
    prev_close: float,
    curr_close: float,
    pct_change: float,
    chunks: list[dict],
) -> str:
    """Build the user-role prompt describing the price move and candidates.

    Args:
        company_name: The company's name.
        check_date: The trading date the price move occurred on.
        prev_close: Previous trading day's closing price.
        curr_close: Current trading day's closing price.
        pct_change: Percent change from prev_close to curr_close.
        chunks: Candidate filing chunks from `retrieval.find_relevant_chunks`,
            each with `content`, `form_type`, and `filing_date`.

    Returns:
        The formatted user-role prompt text.
    """
    move_summary = (
        f"Company: {company_name}\n"
        f"Date: {check_date.isoformat()}\n"
        f"Previous close: ${prev_close:.2f}\n"
        f"Current close: ${curr_close:.2f}\n"
        f"Change: {pct_change:.2f}%\n"
    )

    excerpts = "\n\n".join(
        f"Excerpt {i + 1} (from a {chunk['form_type']} filed "
        f"{chunk['filing_date'].isoformat()}):\n{chunk['content']}"
        for i, chunk in enumerate(chunks)
    )

    return f"{move_summary}\nCandidate excerpts from SEC filings:\n\n{excerpts}"


def explain_price_move(
    client: OpenAI,
    model: str,
    company_name: str,
    check_date: date,
    prev_close: float,
    curr_close: float,
    pct_change: float,
    chunks: list[dict],
) -> Explanation:
    """Ask the LLM to explain a triggered price move using only retrieved text.

    Args:
        client: An initialized OpenAI client.
        model: Chat model name, e.g. "gpt-5.6-luna".
        company_name: The company's name.
        check_date: The trading date the price move occurred on.
        prev_close: Previous trading day's closing price.
        curr_close: Current trading day's closing price.
        pct_change: Percent change from prev_close to curr_close.
        chunks: Candidate filing chunks from `retrieval.find_relevant_chunks`.

    Returns:
        The model's grounded explanation.

    Raises:
        ValueError: If the model's response is missing an expected field
            despite the strict schema (defensive — shouldn't happen).
        openai.OpenAIError: If the API call fails.
    """
    response = client.chat.completions.create(
        model=model,
        response_format={"type": "json_schema", "json_schema": _RESPONSE_JSON_SCHEMA},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_user_prompt(
                    company_name,
                    check_date,
                    prev_close,
                    curr_close,
                    pct_change,
                    chunks,
                ),
            },
        ],
    )

    data = json.loads(response.choices[0].message.content)

    missing = [
        key
        for key in ("connection_found", "explanation", "cited_passages")
        if key not in data
    ]
    if missing:
        raise ValueError(
            f"LLM response missing expected field(s): {missing}. "
            f"Raw response: {data!r}"
        )

    return Explanation(
        connection_found=bool(data["connection_found"]),
        explanation=str(data["explanation"]),
        cited_passages=[str(p) for p in data["cited_passages"]],
    )

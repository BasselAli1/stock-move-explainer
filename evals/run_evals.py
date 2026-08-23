"""Grounding eval runner: sanity-checks explain.py's LLM behavior against
hand-written cases.

Not part of CI — this makes real OpenAI API calls (see evals/cases.jsonl),
so it's run manually: `python evals/run_evals.py`. Checks two things the
whole system's grounding claim depends on:

1. `connection_found` matches the expected outcome for each case.
2. For cases expecting a connection, every cited passage is an exact
   substring of one of the provided chunks — catching fabrication, not
   just a right/wrong final verdict.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from openai import OpenAI

from app.config import get_settings
from app.explain import explain_price_move

CASES_PATH = Path(__file__).resolve().parent / "cases.jsonl"


def _load_cases(path: Path = CASES_PATH) -> list[dict]:
    """Load hand-written eval cases from a JSONL file.

    Args:
        path: Path to the cases file.

    Returns:
        A list of case dicts, with each chunk's `filing_date` parsed from
        an ISO string into a `date` object (as explain_price_move expects).
    """
    cases = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            for chunk in case["chunks"]:
                chunk["filing_date"] = date.fromisoformat(chunk["filing_date"])
            cases.append(case)
    return cases


def _run_case(client: OpenAI, model: str, case: dict) -> tuple[bool, str]:
    """Run one eval case and check its result against expectations.

    Args:
        client: An initialized OpenAI client.
        model: Chat model name, e.g. "gpt-5.6-luna".
        case: One parsed case dict from cases.jsonl.

    Returns:
        A (passed, detail) tuple — detail explains the result either way.
    """
    explanation = explain_price_move(
        client,
        model,
        case["company_name"],
        date.fromisoformat(case["check_date"]),
        case["prev_close"],
        case["curr_close"],
        case["pct_change"],
        case["chunks"],
    )

    expected = case["expected_connection_found"]
    if explanation.connection_found != expected:
        return False, (
            f"expected connection_found={expected}, got {explanation.connection_found} "
            f"(explanation: {explanation.explanation!r})"
        )

    if expected:
        chunk_texts = [chunk["content"] for chunk in case["chunks"]]
        fabricated = [
            passage
            for passage in explanation.cited_passages
            if not any(passage in text for text in chunk_texts)
        ]
        if fabricated:
            return False, f"cited passage(s) not found verbatim in any chunk: {fabricated}"

    return True, f"explanation: {explanation.explanation!r}"


def main() -> None:
    """Run every eval case and print a pass/fail summary."""
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    cases = _load_cases()

    failures = 0
    for case in cases:
        passed, detail = _run_case(client, settings.openai_chat_model, case)
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {case['case_id']}: {detail}")
        if not passed:
            failures += 1

    print(f"\n{len(cases) - failures}/{len(cases)} passed")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()

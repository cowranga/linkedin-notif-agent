"""Reason stage: ask Claude to filter LinkedIn emails to the 3 relevant categories
and write a short, friendly digest — or return the literal string "NONE".

See CLAUDE.md (LLM filtering rules) for the exact behavior implemented here.
"""

from __future__ import annotations

import logging
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised when the digest could not be produced due to a failure (not a quiet NONE)."""


MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 400

SYSTEM_PROMPT = """You filter LinkedIn notification emails and write a short DM digest.

KEEP only these three categories:
1. A new message I received on LinkedIn.
2. A connection request I received.
3. A connection request of mine that was accepted.

IGNORE everything else: post likes/comments, "people you may know", job alerts,
"X viewed your profile", newsletters, event invites, promotions, and anything else.

Output rules:
- Write a short, friendly message summarizing only the KEEP items: who messaged me,
  who sent me a connection request, and whose request was accepted. Use names when present.
- For each item, include WHEN it happened using that email's "Sent at" value, phrased as an
  approximate time (e.g. "around Sun 29 Jun, 1:36 PM IST"). This is when LinkedIn emailed me,
  which is roughly when the event happened. Put one item per line.
- No preamble, no greeting, no sign-off, no markdown headers — just the summary lines.
- If NONE of the three categories are present in the emails, output exactly: NONE"""


def _format_emails(emails: list[dict[str, str]]) -> str:
    blocks = []
    for i, e in enumerate(emails, 1):
        blocks.append(
            f"Email {i}:\n"
            f"From: {e.get('sender', '')}\n"
            f"Subject: {e.get('subject', '')}\n"
            f"Sent at: {e.get('sent_at', 'unknown')}\n"
            f"Snippet: {e.get('snippet', '')}"
        )
    return "\n\n".join(blocks)


def build_digest(emails: list[dict[str, str]]) -> str:
    """Return a short friendly digest of relevant LinkedIn emails, or "NONE".

    Returns "NONE" only when there is genuinely nothing relevant. Raises
    :class:`LLMError` on a real failure (missing key, API/network error) so the
    caller can surface it instead of silently swallowing it.
    """
    if not emails:
        return "NONE"

    # Strip whitespace: a stray trailing newline (common when pasting into a CI secret)
    # makes an invalid auth header, which the SDK surfaces as "Connection error."
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        raise LLMError("ANTHROPIC_API_KEY not set; cannot summarize.")

    user_content = (
        "Here are the LinkedIn emails from my inbox. Apply the rules and produce the digest "
        "or NONE.\n\n" + _format_emails(emails)
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
    except anthropic.APIError as exc:
        logger.error("Anthropic API error: %s", exc)
        raise LLMError(f"Anthropic API error: {exc}") from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Unexpected error calling Anthropic: %s", exc)
        raise LLMError(f"Unexpected error calling Anthropic: {exc}") from exc

    text = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ).strip()

    if not text:
        logger.warning("LLM returned empty output; treating as NONE.")
        return "NONE"

    logger.info("LLM digest produced (%d chars).", len(text))
    return text


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from email_reader import get_recent_linkedin_emails

    sample = get_recent_linkedin_emails()
    print("\n=== LLM OUTPUT ===")
    try:
        print(build_digest(sample))
    except LLMError as exc:
        print(f"LLMError: {exc}")

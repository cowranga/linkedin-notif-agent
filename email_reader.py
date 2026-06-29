"""Perceive stage: read recent LinkedIn notification emails from Gmail via IMAP.

See CLAUDE.md (IMAP details) for the rules implemented here. The key subtlety is that
IMAP SEARCH "SINCE" is date-granularity only, so we search a slightly wider window
(since yesterday) and then filter precisely to the last LOOKBACK_HOURS in Python using
the parsed Date header.
"""

from __future__ import annotations

import email
import imaplib
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = (os.getenv("EMAIL_APP_PASSWORD") or "").replace(" ", "") or None
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "6"))

# Timezone for displaying email send times in the digest (IANA name, e.g. "Asia/Kolkata").
DISPLAY_TIMEZONE = os.getenv("DISPLAY_TIMEZONE", "UTC")
try:
    _DISPLAY_TZ = ZoneInfo(DISPLAY_TIMEZONE)
except (ZoneInfoNotFoundError, ValueError):
    logger.warning("Unknown DISPLAY_TIMEZONE %r; falling back to UTC.", DISPLAY_TIMEZONE)
    _DISPLAY_TZ = timezone.utc

SNIPPET_MAX_CHARS = 300


def _format_sent_at(sent_at: datetime) -> str:
    """Render an email's send time in the configured display timezone.

    This is when LinkedIn sent the notification email — the best available proxy for
    when the underlying event happened (LinkedIn does not include the exact in-app time).
    """
    local = sent_at.astimezone(_DISPLAY_TZ)
    # e.g. "Sun 29 Jun, 1:36 PM IST"
    return local.strftime("%a %d %b, %-I:%M %p %Z")


def _decode(value: str | None) -> str:
    """Decode a possibly RFC 2047-encoded header into a plain string."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # pragma: no cover - defensive; malformed headers
        return value


def _extract_snippet(msg: Message) -> str:
    """Pull a short plain-text snippet from an email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(
                part.get("Content-Disposition", "")
            ):
                body = _payload_to_text(part)
                if body:
                    break
        if not body:
            # Fall back to HTML, stripped of tags.
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    body = re.sub(r"<[^>]+>", " ", _payload_to_text(part))
                    if body:
                        break
    else:
        body = _payload_to_text(msg)
        if msg.get_content_type() == "text/html":
            body = re.sub(r"<[^>]+>", " ", body)

    collapsed = re.sub(r"\s+", " ", body).strip()
    if len(collapsed) > SNIPPET_MAX_CHARS:
        collapsed = collapsed[:SNIPPET_MAX_CHARS].rstrip() + "…"
    return collapsed


def _payload_to_text(part: Message) -> str:
    """Decode a single message part's payload to text, best-effort."""
    try:
        raw = part.get_payload(decode=True)
        if raw is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")
    except Exception:  # pragma: no cover - defensive
        return ""


def get_recent_linkedin_emails() -> list[dict[str, str]]:
    """Return LinkedIn emails received within the last LOOKBACK_HOURS.

    Each item is a dict with keys: ``sender``, ``subject``, ``snippet``.
    Returns an empty list on any error (logged) or when nothing matches.
    """
    if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
        logger.error("EMAIL_ADDRESS / EMAIL_APP_PASSWORD not set; cannot read mail.")
        return []

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)
    # IMAP SINCE is date-only; search from yesterday to be safe, filter precisely below.
    since_date = (now - timedelta(days=1)).strftime("%d-%b-%Y")

    results: list[dict[str, str]] = []
    conn: imaplib.IMAP4_SSL | None = None
    try:
        conn = imaplib.IMAP4_SSL(IMAP_HOST, 993)
        conn.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        conn.select("INBOX", readonly=True)

        status, data = conn.search(
            None, "SINCE", since_date, "FROM", "linkedin.com"
        )
        if status != "OK":
            logger.error("IMAP search failed: %s", status)
            return []

        ids = data[0].split()
        logger.info("IMAP search returned %d candidate email(s) since %s.", len(ids), since_date)

        for num in ids:
            fetch_status, fetch_data = conn.fetch(num, "(RFC822)")
            if fetch_status != "OK" or not fetch_data or not fetch_data[0]:
                logger.warning("Failed to fetch message %s; skipping.", num.decode())
                continue

            msg = email.message_from_bytes(fetch_data[0][1])

            # Filter precisely to the last LOOKBACK_HOURS using the Date header.
            date_hdr = msg.get("Date")
            try:
                sent_at = parsedate_to_datetime(date_hdr) if date_hdr else None
            except (TypeError, ValueError):
                sent_at = None
            if sent_at is None:
                logger.warning("Message %s has no parseable Date; skipping.", num.decode())
                continue
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            if sent_at < cutoff:
                continue

            results.append(
                {
                    "sender": _decode(msg.get("From")),
                    "subject": _decode(msg.get("Subject")),
                    "snippet": _extract_snippet(msg),
                    "sent_at": _format_sent_at(sent_at),
                }
            )

        logger.info("Kept %d LinkedIn email(s) within the last %d hour(s).", len(results), LOOKBACK_HOURS)
    except imaplib.IMAP4.error as exc:
        logger.error("IMAP error: %s", exc)
    except OSError as exc:
        logger.error("Network error connecting to IMAP host: %s", exc)
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    emails = get_recent_linkedin_emails()
    print(f"\nFound {len(emails)} LinkedIn email(s) in the last {LOOKBACK_HOURS} hour(s):\n")
    for i, e in enumerate(emails, 1):
        print(f"--- [{i}] ---")
        print(f"From:    {e['sender']}")
        print(f"Subject: {e['subject']}")
        print(f"Sent at: {e['sent_at']}")
        print(f"Snippet: {e['snippet']}")
        print()

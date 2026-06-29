"""Orchestrator: perceive -> reason -> act.

read inbox -> if empty, exit quietly -> summarize with the LLM -> if "NONE", exit
quietly -> send the digest via Telegram.

Flags:
  --dry-run  Print the digest instead of sending it.
  --force    Ignore the LOOKBACK_HOURS window (useful for testing).
"""

from __future__ import annotations

import argparse
import logging
import sys

import email_reader
import llm
import notifier


def main() -> int:
    parser = argparse.ArgumentParser(description="LinkedIn email -> Telegram digest agent.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the digest instead of sending it."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore the LOOKBACK_HOURS time window (useful for testing).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("main")

    # Heartbeat (dead-man's-switch) confirms the agent ran to completion, even on quiet
    # days. Skipped in --dry-run so local testing never touches the production monitor.
    def ok_run() -> int:
        if not args.dry_run:
            notifier.heartbeat(success=True)
        return 0

    def failed_run() -> int:
        if not args.dry_run:
            notifier.heartbeat(success=False)
        return 1

    # --force: widen the window so old emails are not filtered out.
    if args.force:
        logger.info("--force enabled: ignoring the LOOKBACK_HOURS window.")
        email_reader.LOOKBACK_HOURS = 24 * 365

    # 1. Perceive.
    emails = email_reader.get_recent_linkedin_emails()
    if not emails:
        logger.info("No LinkedIn emails in window; nothing to do. Exiting quietly.")
        return ok_run()

    # 2. Reason.
    try:
        digest = llm.build_digest(emails)
    except llm.LLMError as exc:
        logger.error("Digest failed: %s", exc)
        alert = f"⚠️ LinkedIn Notifier Agent error: {exc}"
        if args.dry_run:
            print("\n=== ERROR ALERT (dry run) ===")
            print(alert)
        else:
            notifier.send(alert)
        return failed_run()

    if digest.strip() == "NONE":
        logger.info("LLM found nothing relevant (NONE); exiting quietly.")
        return ok_run()

    # 3. Act.
    if args.dry_run:
        logger.info("--dry-run enabled: printing digest instead of sending.")
        print("\n=== DIGEST (dry run) ===")
        print(digest)
        return 0

    if notifier.send(digest):
        return ok_run()
    return failed_run()


if __name__ == "__main__":
    sys.exit(main())

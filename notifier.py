"""Act stage: send a text message to me via the Telegram Bot API."""

from __future__ import annotations

import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT_SECONDS = 15
HEARTBEAT_TIMEOUT = 10


def send(text: str) -> bool:
    """Send ``text`` to the configured Telegram chat. Returns True on success."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set; cannot send.")
        return False

    try:
        response = requests.post(
            TELEGRAM_API.format(token=token),
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Failed to send Telegram message: %s", exc)
        return False

    logger.info("Telegram message sent (%d chars).", len(text))
    return True


def heartbeat(success: bool = True) -> bool:
    """Ping the optional dead-man's-switch URL (e.g. healthchecks.io) to signal a run.

    Confirms the agent ran to completion even on quiet days when no DM is sent. A no-op
    (returns True) when HEARTBEAT_URL is unset. When ``success`` is False, "/fail" is
    appended so the monitor records a failed run. Never raises.
    """
    url = os.getenv("HEARTBEAT_URL")
    if not url:
        return True
    if not success:
        url = url.rstrip("/") + "/fail"
    try:
        response = requests.get(url, timeout=HEARTBEAT_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Heartbeat ping failed: %s", exc)
        return False
    logger.info("Heartbeat ping sent (success=%s).", success)
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ok = send("✅ LinkedIn Notifier Agent: test message.")
    print("Sent!" if ok else "Send failed — check the logs above.")
    if os.getenv("HEARTBEAT_URL"):
        heartbeat(success=True)

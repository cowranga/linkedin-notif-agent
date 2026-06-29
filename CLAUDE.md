# LinkedIn Notifier Agent

## Goal
A scheduled agent that reads my email inbox, extracts LinkedIn notifications about
(1) new messages received, (2) connection requests received, (3) connection requests accepted,
and sends me a short DM. Runs every 6 hours. If nothing relevant happened, send nothing.

## Architecture (perceive → reason → act)
- email_reader.py — connects to Gmail via IMAP, returns LinkedIn emails from the last LOOKBACK_HOURS.
- llm.py — sends those emails to Claude, which filters to the 3 categories above and writes a
  short friendly digest, OR returns the literal string "NONE" if nothing relevant.
- notifier.py — send(text) function. Sends via the Telegram Bot API.
- main.py — orchestrates: read → if empty, exit quietly → llm → if "NONE", exit quietly → notify.

## Tech
- Python 3.11+. stdlib imaplib + email for mail. anthropic SDK. requests (Telegram). 
- Model: claude-haiku-4-5-20251001 (cheap, fast — this is simple summarization).
- All config via environment variables, loaded with python-dotenv.

## IMAP details
- Host imap.gmail.com:993 SSL. Auth with EMAIL_ADDRESS + EMAIL_APP_PASSWORD.
- IMPORTANT: IMAP SEARCH "SINCE" is date-granularity only, not hours. So search emails SINCE
  (today minus 1 day) FROM "linkedin.com", then filter precisely in Python by the parsed Date
  header to keep only those within the last LOOKBACK_HOURS. This avoids re-notifying old emails.
- Extract sender, subject, and a short text snippet from each matching email.

## LLM filtering rules (put these in the prompt)
- KEEP only: new message received, connection request received, connection request accepted.
- IGNORE everything else: post likes/comments, "people you may know", job alerts, "X viewed your
  profile", newsletters, event invites, etc.
- Output: a short, friendly message (who messaged me, who sent/accepted a request). No preamble.
- If none of the 3 categories are present, output exactly: NONE

## Env vars
ANTHROPIC_API_KEY, EMAIL_ADDRESS, EMAIL_APP_PASSWORD, IMAP_HOST, LOOKBACK_HOURS,
DISPLAY_TIMEZONE (IANA name for digest timestamps; default UTC),
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, HEARTBEAT_URL (optional)

## Conventions
- Keep it simple and readable. Type hints. Clear logging at each stage (use logging, not print).
- Wrap network calls in try/except. Never crash silently; never commit secrets.
- Provide a --dry-run flag (print the digest instead of sending) and a --force flag (ignore the
  time window, useful for testing).
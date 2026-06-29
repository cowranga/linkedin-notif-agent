# LinkedIn Notifier Agent

> A serverless agent that reads your email inbox every 6 hours, extracts the LinkedIn notifications that actually matter, and sends you a short Telegram DM — staying silent when nothing relevant happened.

## What it does

LinkedIn buries the three things you actually care about — **new messages**, **connection requests received**, and **connection requests accepted** — under a flood of "people you may know," job alerts, post reactions, and "X viewed your profile" noise.

This agent watches the LinkedIn notification emails that already land in your Gmail, uses an LLM to keep only those three categories, and pings you with a one-line digest. If nothing relevant arrived in the window, it sends **nothing** — no noise.

## How it works

A classic **perceive → reason → act** loop, run on a schedule:

```
            ┌─────────────┐      ┌──────────────┐      ┌──────────────┐
 Gmail ───► │  PERCEIVE   │ ───► │    REASON    │ ───► │     ACT      │ ───► Telegram
 (IMAP)     │ email_reader│      │    llm.py    │      │  notifier.py │
            │  .py        │      │ (Claude Haiku)│     │  (Bot API)   │
            └─────────────┘      └──────────────┘      └──────────────┘
                  │                     │                     │
          LinkedIn emails in     filter to 3 categories,  send DM, or stay
          last LOOKBACK_HOURS    write digest or "NONE"   silent on "NONE"
```

- **`email_reader.py` (perceive)** — connects to Gmail over IMAP, searches `FROM linkedin.com SINCE yesterday`, then filters precisely to the last `LOOKBACK_HOURS` in Python using each message's `Date` header. Returns `[{sender, subject, snippet}]`.
- **`llm.py` (reason)** — sends those emails to **Claude Haiku** with a system prompt encoding the filtering rules. Returns a short, friendly digest, or the exact string `NONE` if nothing relevant. Raises `LLMError` on a real API failure so it can be surfaced rather than silently swallowed.
- **`notifier.py` (act)** — `send(text)` posts to the Telegram Bot API via `requests`.
- **`main.py` (orchestrate)** — read → if empty, exit quietly → `build_digest` → if `NONE`, exit quietly → send (or print with `--dry-run`). On an `LLMError` it sends a Telegram **error alert** so failures stay visible.

### IMAP time-window subtlety

IMAP `SEARCH SINCE` is **date-granularity only** — it can't express "the last 6 hours." So the reader searches since *yesterday* (a deliberately wider net) and then filters to the exact hour window in Python. This is what makes the stateless schedule idempotent (see below).

## Why email instead of scraping (ToS-aware)

LinkedIn's User Agreement **prohibits scraping and automated access** to the site, and they actively defend it (bot detection, rate limiting, legal action — *hiQ v. LinkedIn*). Scraping would also mean storing your LinkedIn password or session cookies and fighting a constantly shifting DOM.

This agent never touches LinkedIn. It only reads **emails LinkedIn already chose to send you**, in **your own inbox**, using a Gmail **app password** scoped to mail. That's data you already own, accessed through a stable, documented protocol (IMAP) — no ToS gray area, no brittle HTML parsing, no credential risk on the LinkedIn side.

## Design decisions

- **Claude Haiku for cost** — this is simple, high-volume classification + a one-line summary, not reasoning. Haiku (`claude-haiku-4-5-20251001`) is the cheapest, fastest model and more than capable here. No reason to pay for Sonnet/Opus.
- **Stateless 6-hour window for idempotency** — the agent keeps **no database** of "already seen" emails. Instead it runs every 6 hours and only considers mail from the last `LOOKBACK_HOURS` (6). Each email falls into exactly one window, so you're notified once and never re-notified — without any persistence to manage. The `SINCE`-yesterday + precise Python filter is what keeps this exact.
- **GitHub Actions for serverless scheduling** — no server to run or pay for. A `cron` workflow spins up a runner every 6 hours, executes one short job, and shuts down. Free for this volume, with built-in logs and manual re-runs (`workflow_dispatch`).
- **Secrets via environment variables** — no secret ever touches the repo. Locally they live in `.env` (git-ignored); in CI they're GitHub **repo secrets** injected as env vars at runtime. `.env.example` documents every variable without values.
- **Fail loud, not silent** — a genuine API/credential failure raises and triggers a Telegram error alert, so a broken agent can't quietly stop notifying you. "Nothing relevant" (`NONE`) is the *only* reason it stays silent.
- **Heartbeat dead-man's-switch** — every successful run (including quiet `NONE`/empty days) pings the optional `HEARTBEAT_URL` (e.g. [healthchecks.io](https://healthchecks.io)); failures ping `…/fail`. The monitor alerts *you* if an expected ping never arrives — catching a silently disabled or stuck cron, which Telegram alone can't. Unset the var to disable.

## Setup

1. **Clone & install**
   ```bash
   python3 -m venv venv
   ./venv/bin/pip install -r requirements.txt
   ```
2. **Configure** — copy the example env file and fill it in:
   ```bash
   cp .env.example .env
   ```
   - `ANTHROPIC_API_KEY` — from console.anthropic.com (needs credit balance).
   - `EMAIL_ADDRESS` / `EMAIL_APP_PASSWORD` — your Gmail and a 16-char [App Password](https://myaccount.google.com/apppasswords) (requires 2-Step Verification). Spaces are stripped automatically.
   - `IMAP_HOST` — `imap.gmail.com`.
   - `LOOKBACK_HOURS` — `6` (match your schedule interval).
   - `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather).
   - `TELEGRAM_CHAT_ID` — your chat ID (message the bot, then check `https://api.telegram.org/bot<TOKEN>/getUpdates`).
   - `HEARTBEAT_URL` *(optional)* — a [healthchecks.io](https://healthchecks.io) ping URL; create a check with a period of 6h + a grace window and you'll be alerted if a run is ever missed. Leave unset to disable.
3. **Test the pieces**
   ```bash
   ./venv/bin/python email_reader.py        # prints LinkedIn emails it finds
   ./venv/bin/python notifier.py            # sends a Telegram test message
   ./venv/bin/python main.py --force --dry-run   # full pipeline, prints instead of sending
   ```
   - `--dry-run` prints the digest instead of sending it.
   - `--force` ignores the time window (useful for testing against older mail).
4. **Schedule** — push to GitHub, add each `.env` variable as a **repo secret** (Settings → Secrets and variables → Actions), and the included workflow runs it every 6 hours. Trigger a manual run from the Actions tab to confirm.

## What I'd build next

- **More categories & smarter digests** — InMail, post mentions, or messages grouped/threaded by sender.
- **Reply from the DM** — a Telegram bot that lets you draft a reply, opening the right LinkedIn thread via deep link.
- **Pluggable channels** — Slack, Discord, or WhatsApp behind the same `notifier.send()` interface.
- **De-dupe across providers** — extend beyond Gmail (Outlook/IMAP-generic) with a tiny seen-id store if windows ever overlap.
- **Self-tuning filter** — let me thumbs-down a digest item and feed that back into the prompt to cut false positives over time.
- **Status page** — a small public dashboard on top of the heartbeat history for at-a-glance health.

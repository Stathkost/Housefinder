# Housefinder

A Python bot that monitors Greek real-estate sites (**XE.gr** and **Spitogatos.gr**)
for new rental listings matching your filters and emails you when new ones appear.

Scraping is done through [ScraperAPI](https://www.scraperapi.com/). The bot runs in a
loop, checking every 30 minutes, and shows a live status console (uptime, CPU/memory,
trigger count) between runs.

## How it works

1. Reads your search filters and location IDs from `.env`.
2. Calls XE and Spitogatos search APIs (proxied through ScraperAPI).
3. Compares results against `data/results.json` / `data/results_spitogatos.json`
   to find listings it hasn't seen before.
4. Emails the new listings (HTML email via the Resend API) and logs to `data/logs/`.

## Setup

```bash
# 1. Create and activate a virtual environment
virtualenv venv            # or: python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 2b. Install the headless browser used to reach Spitogatos (see note below)
python -m playwright install chromium

# 3. Create your config from the template and fill it in
cp example.env .env
```

Edit `.env`:

- `RESEND_API_KEY` / `RESEND_FROM_EMAIL` — your [Resend](https://resend.com) API key
  and a verified sender address (e.g. `noreply@yourdomain`). Emails are sent through
  the Resend API. `RESEND_WEBHOOK_SECRET` is optional (only needed if you consume
  Resend webhooks).
- `RECIPIENTS_EMAILS` — JSON array of who gets notified.
- `SCRAPPER_API_KEY` — your ScraperAPI key.
- Search filters (price, size, bedrooms, floor) and location IDs — see the comments
  in `example.env` for the area-ID lookup tables.

## Run

```bash
source venv/bin/activate
python main.py
```

`Ctrl+C` stops it.

## Config GUI

Instead of hand-editing `.env`, you can manage everything from a small local web app:

```bash
source venv/bin/activate
python config_gui.py
```

Then open <http://127.0.0.1:5000>. From there you can:

- Edit the sender Gmail, app password and **recipient list**.
- Edit all XE and Spitogatos filters (price, size, bedrooms/rooms, floor, sorting).
- **Add/remove search areas** with a live search box that queries each site's own
  autocomplete API, so the IDs are always the exact ones the sites expect (XE uses
  Google place IDs, Spitogatos uses numeric area IDs).
- **Save** writes back to `.env`.
- **Fresh start** clears the "already seen" listings (`data/results*.json`) so the
  next run re-emails every current match.
- **Start / Stop** the bot.

Saving updates `.env`; restart the bot (or use the Restart button) to apply changes.

The GUI also has:

- **Scheduler** — set how often the bot re-checks (`SEARCH_INTERVAL_MINUTES`).
- **Console** — live tail of the bot's activity log and error log.
- **Start / Stop / Restart** — controls the background service (see below).

## Run as a service (auto-start on boot)

The bot and GUI are installed as **systemd user services** so they keep running
after a crash and start automatically when the PC boots (user *lingering* is
enabled, so they run even before you log in).

```bash
# status
systemctl --user status housefinder-bot.service
systemctl --user status housefinder-gui.service   # GUI at http://127.0.0.1:5000

# start / stop / restart
systemctl --user restart housefinder-bot.service

# live logs
journalctl --user -u housefinder-bot.service -f
```

Unit files live in `deploy/` (copied to `~/.config/systemd/user/`). To reinstall
on another machine: copy them there, then
`systemctl --user daemon-reload && systemctl --user enable --now housefinder-bot.service`
and `loginctl enable-linger $USER`.

The bot is resilient: each cycle is wrapped in error handling, one site failing
never stops the other, and any crash is logged to `data/logs/errors_*.txt` and
retried (systemd also restarts the process if it ever exits).

## Site status (June 2026)

- **XE.gr** — working through the standard ScraperAPI plan. ✅
- **Spitogatos.gr** — behind DataDome anti-bot protection, which blocks ScraperAPI's
  datacenter proxies (HTTP 500/403). Instead of a paid ScraperAPI premium plan, the
  bot reaches it for **free** with a local **headless browser** (Playwright/Chromium):
  it visits the site to clear the DataDome challenge, then calls the search API from
  inside the page. This works because the bot runs from a normal residential IP. ✅

  Requires the one-time `python -m playwright install chromium` step. If the challenge
  ever isn't cleared on a given run, it's logged as an error and that cycle is skipped;
  the next cycle retries. The `SCRAPERAPI_PREMIUM` / `SCRAPERAPI_ULTRA_PREMIUM` toggles
  still exist but are no longer needed for Spitogatos.

## Security note

Never commit real credentials. `.env` is gitignored; keep your Resend API key,
webhook secret and ScraperAPI key only there. If a secret was ever pushed, rotate it.

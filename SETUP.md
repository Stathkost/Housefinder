# Housefinder — Quick Setup

Get the bot running in a few minutes. It watches **XE.gr** and **Spitogatos.gr**
for new rental listings and emails you when new ones appear.

---

## 1. One-command install

```bash
git clone https://github.com/Stathkost/Housefinder.git
cd Housefinder
./setup.sh
```

`setup.sh` creates the virtual environment, installs the dependencies, downloads
the headless browser (needed for Spitogatos), and creates your `.env` from the
template. Safe to re-run any time.

## 2. Add your keys

Launch the desktop app:

```bash
./venv/bin/python app.py
```

This opens a native embedded-browser window. Fill in:

| Field | Where to get it |
|-------|-----------------|
| **Resend API key** + **From address** | [resend.com](https://resend.com) — create a key and verify a sending domain |
| **Recipients** | the email addresses that should get alerts |
| **ScraperAPI key** | [scraperapi.com](https://www.scraperapi.com) (free tier is enough for XE) |
| **Filters** | price, size, bedrooms, floor for each site |
| **Locations** | type an area name in the search box — it looks up the right IDs for you |
| **Interval** | how often to re-check (minutes) |

Click **💾 Save config**.

> Prefer editing a file? Everything lives in `.env` (copied from `example.env`).

## 3. Run it

**Option A — keep it running 24/7 (recommended).** Installs background services
that auto-start on boot and restart on failure:

```bash
./setup.sh --service
```

The bot and the GUI now run in the background. Manage them with:

```bash
systemctl --user status  housefinder-bot.service
systemctl --user restart housefinder-bot.service   # after changing config
systemctl --user stop    housefinder-bot.service
journalctl --user -u housefinder-bot.service -f     # live logs
```

**Option B — run it in a terminal** (stops when you close it):

```bash
./venv/bin/python main.py      # Ctrl+C to stop
```

---

## Good to know

- **Spitogatos works without a paid plan.** It's behind DataDome anti-bot
  protection; the bot clears it for free using a local headless browser, so you
  do **not** need ScraperAPI premium.
- **The GUI is just a control panel.** Closing it does not stop the bot. After
  changing config there, hit **Restart** (or restart the service) to apply.
- **Live console + errors** are visible in the GUI. Errors are also saved to
  `data/logs/errors_*.txt`.
- **"Fresh start"** in the GUI clears the list of already-seen listings, so the
  next run re-emails every current match. Normally you don't need it.
- **Your data** (`data/results*.json`) is the list of listings already seen, so
  you aren't emailed twice. Keep it.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Spitogatos says "anti-bot challenge not cleared" | Usually transient — it retries next cycle. If persistent, re-run `./venv/bin/python -m playwright install chromium`. |
| No emails arrive | Check the **Resend From address** is on a *verified* domain and recipients are correct (GUI → Console → Errors). |
| XE returns an HTTP error | Your ScraperAPI credits may be exhausted — check your scraperapi.com dashboard. |
| Bot not running after reboot | `loginctl enable-linger $USER` (may need `sudo`), then `systemctl --user start housefinder-bot.service`. |

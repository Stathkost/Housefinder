<div align="center">
  <img src="assets/logo.png" width="120" alt="Housefinder logo">
  <h1>Housefinder</h1>
  <p>A desktop property-alert bot for the Greek real-estate market.<br>
  Monitors <strong>XE.gr</strong> and <strong>Spitogatos.gr</strong> and emails you the moment new listings match your filters.</p>

  [![Build Desktop App](https://github.com/Stathkost/Housefinder/actions/workflows/build.yml/badge.svg)](https://github.com/Stathkost/Housefinder/actions/workflows/build.yml)
  [![Latest Build](https://img.shields.io/github/v/release/Stathkost/Housefinder?label=latest%20build&color=FFD43B)](https://github.com/Stathkost/Housefinder/releases/tag/latest-build)
</div>

---

> **Platform status — 29 June 2026**
> | Platform | Status |
> |----------|--------|
> | 🐧 Linux (Ubuntu 22.04+) | ✅ **Tested and working** |
> | 🪟 Windows 10/11 | 🔶 Build provided, community-tested |
> | 🍎 macOS 13+ | 🔶 Build provided, community-tested |

---

## How it works

1. Every N minutes (default 30) the bot fetches all pages of XE.gr results through ScraperAPI and all pages of Spitogatos.gr results through a local headless browser (bypassing DataDome for free).
2. New listings are compared against a local database (`data/results*.json`). Only truly new ones proceed.
3. An HTML email with clickable property cards is sent to all recipients via the Resend API.
4. Everything is configurable from a **built-in web GUI** — no hand-editing files needed.

---

## Quick start (packaged app)

Download the latest build from the [Releases](https://github.com/Stathkost/Housefinder/releases/tag/latest-build) page.

**Linux**
```bash
tar -xzf housefinder-linux.tar.gz
cd Housefinder
python -m playwright install chromium   # one-time, ~150 MB
./Housefinder                           # opens the desktop app
```

**Windows** — unzip `housefinder-windows.zip` and run `Housefinder.exe`.
WebView2 (part of Microsoft Edge) is required — already present on Windows 10/11.

**macOS** — unzip `housefinder-macos.tar.gz`, then:
```bash
xattr -cr ./Housefinder   # remove quarantine flag
./Housefinder
```

> The app opens a native embedded-browser window. Fill in your API keys, add locations, set filters, then click **Start** — the bot runs in the background and survives reboots.

---

## Developer setup (from source)

```bash
git clone https://github.com/Stathkost/Housefinder.git
cd Housefinder
./setup.sh                 # venv + deps + Chromium
# OR  ./setup.sh --service  to install systemd auto-start (Linux)
```

Then open the app:
```bash
./venv/bin/python app.py   # embedded browser window
# or just the web GUI:
./venv/bin/python config_gui.py   # then open http://127.0.0.1:5000
```

See [SETUP.md](SETUP.md) for detailed step-by-step instructions.

---

## API keys needed

| Service | Used for | Free tier |
|---------|----------|-----------|
| [ScraperAPI](https://www.scraperapi.com) | Fetching XE.gr through a proxy | 1,000 req/month |
| [Resend](https://resend.com) | Sending email alerts | 3,000 emails/month |

> **Spitogatos.gr** uses a local headless browser (Playwright/Chromium) to bypass DataDome anti-bot protection — **no paid plan needed**.

---

## Building from source

```bash
pip install pyinstaller pywebview
pyinstaller app.spec
# output: dist/Housefinder/
```

Every push to `main` triggers an automated build for all three platforms via GitHub Actions — see the [Actions tab](https://github.com/Stathkost/Housefinder/actions).

---

## Auto-start after reboot

| Platform | Mechanism |
|----------|-----------|
| Linux | `systemd --user` service (installed by `setup.sh --service`) |
| Windows | Windows Registry Run key (set automatically when you click **Start** in the app) |
| macOS | launchd plist in `~/Library/LaunchAgents/` (set automatically when you click **Start**) |

Clicking **Stop** in the app removes the autostart entry on all platforms.

---

## Legal & disclaimer

Housefinder is an **unofficial** personal automation tool. It is not affiliated with, endorsed by, or connected to XE.gr or Spitogatos.gr in any way.

Web scraping may be subject to each website's Terms of Service. You are solely responsible for how you use this software. This software is provided **"as is"**, without warranty of any kind.

---

## Credits

Built with ❤️ by:

| | |
|--|--|
| **Stathis Stathopoulos** | [@stathis1998](https://github.com/stathis1998) |
| **Konstantinos Stathopoulos** | [@Stathkost](https://github.com/Stathkost) |

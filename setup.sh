#!/usr/bin/env bash
#
# Housefinder one-shot setup.
#   ./setup.sh            # install everything
#   ./setup.sh --service  # also install + start the systemd user services (auto-start on boot)
#
# Safe to re-run.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"
PROJ="$(pwd)"
PY="$PROJ/venv/bin/python"

say() { printf "\n\033[1;33m==> %s\033[0m\n" "$1"; }

# 1) Python virtual environment ------------------------------------------------
if [ ! -x "$PY" ]; then
  say "Creating virtual environment (venv/)"
  python3 -m venv venv
fi

# 2) Dependencies --------------------------------------------------------------
say "Installing Linux system dependencies for embedded browser (GTK WebKit2)"
if command -v apt-get &>/dev/null; then
  sudo apt-get install -y -qq \
    python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.0 \
    libwebkit2gtk-4.0-dev 2>/dev/null || true
fi

say "Installing Python dependencies"
"$PY" -m pip install --upgrade pip >/dev/null
"$PY" -m pip install -r requirements.txt

# 3) Headless browser for Spitogatos (DataDome bypass) -------------------------
say "Installing the headless browser (Chromium for Playwright)"
"$PY" -m playwright install chromium

# 4) Config + data dirs --------------------------------------------------------
mkdir -p data/logs
[ -f data/results.json ]            || echo "[]" > data/results.json
[ -f data/results_spitogatos.json ] || echo "[]" > data/results_spitogatos.json
if [ ! -f .env ]; then
  say "Creating .env from template — EDIT IT with your keys/recipients"
  cp example.env .env
else
  echo "    .env already exists, leaving it untouched."
fi

# 5) Optional: systemd user services (auto-start on boot) ----------------------
if [ "${1:-}" = "--service" ]; then
  say "Installing systemd user services (bot + GUI)"
  mkdir -p "$HOME/.config/systemd/user"
  for unit in housefinder-bot housefinder-gui; do
    sed "s|@PROJ@|$PROJ|g; s|@PY@|$PY|g" "deploy/$unit.service.tmpl" \
      > "$HOME/.config/systemd/user/$unit.service"
  done
  systemctl --user daemon-reload
  systemctl --user enable --now housefinder-bot.service housefinder-gui.service
  loginctl enable-linger "$USER" 2>/dev/null || \
    echo "    (could not enable linger automatically; run: sudo loginctl enable-linger $USER)"
  say "Services installed. GUI at http://127.0.0.1:5000"
  systemctl --user --no-pager status housefinder-bot.service | head -4 || true
fi

say "Done!"
echo "Next:"
echo "  1. Launch the desktop app:      $PY app.py"
echo "     (or just the web GUI:        $PY config_gui.py  ->  http://127.0.0.1:5000)"
echo "  2. Fill in your API keys, set filters, then click Start in the app."
echo "  3. Or run ./setup.sh --service  to keep it running 24/7 (auto-start on boot)."

"""
Housefinder config GUI
=======================
A small local web app to manage the bot's .env configuration:
filters, recipients and search locations (with live area lookup from
XE.gr and Spitogatos.gr), plus start/stop the bot and a fresh-start button.

Run:
    ./venv/bin/python config_gui.py
then open http://127.0.0.1:5000 in your browser.
"""

import os
import re
import sys
import json
import signal
import platform
import subprocess
import requests
from flask import Flask, request, jsonify, render_template_string

BASE_DIR = os.path.dirname(os.path.abspath(
    sys.executable if getattr(sys, "frozen", False) else __file__
))
ENV_PATH = os.path.join(BASE_DIR, ".env")
PID_PATH = os.path.join(BASE_DIR, "data", "bot.pid")
RESULTS_XE = os.path.join(BASE_DIR, "data", "results.json")
RESULTS_SPITO = os.path.join(BASE_DIR, "data", "results_spitogatos.json")
PLATFORM = platform.system()   # 'Linux', 'Windows', 'Darwin'

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

app = Flask(__name__)


# --------------------------------------------------------------------------
# .env parsing / rendering. The GUI owns the .env format so it can round-trip
# values and keep human-readable location comments in sync.
# --------------------------------------------------------------------------

# Simple scalar keys: env_key -> default
SCALAR_KEYS = {
    "RESEND_API_KEY": "",
    "RESEND_FROM_EMAIL": "",
    "RESEND_WEBHOOK_SECRET": "",
    "SCRAPPER_API_KEY": "",
    "SCRAPERAPI_PREMIUM": "false",
    "SCRAPERAPI_ULTRA_PREMIUM": "false",
    "SEARCH_INTERVAL_MINUTES": "30",
    # XE filters
    "MINIMUM_PRICE": "", "MAXIMUM_PRICE": "",
    "MINIMUM_SIZE": "", "MAXIMUM_SIZE": "",
    "MINIMUM_BEDROOMS": "", "MAXIMUM_BEDROOMS": "",
    "MINIMUM_LEVEL": "", "MAXIMUM_LEVEL": "",
    "SORTING": "create_desc",
    # Spitogatos filters
    "LISTING_TYPE": "rent", "CATEGORY": "residential",
    "PRICE_LOW": "", "PRICE_HIGH": "",
    "LIVING_AREA_LOW": "", "LIVING_AREA_HIGH": "",
    "ROOMS_LOW": "", "ROOMS_HIGH": "",
    "FLOOR_NUMBER_LOW": "", "FLOOR_NUMBER_HIGH": "",
    "SORT_BY": "datemodified",
}


def _strip_quotes(v):
    v = v.strip()
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        return v[1:-1]
    return v


def parse_env():
    """Read .env into a config dict the GUI/JS understands."""
    cfg = {k: v for k, v in SCALAR_KEYS.items()}
    cfg["RECIPIENTS_EMAILS"] = []
    cfg["XE_LOCATIONS"] = []      # [{id, name}]
    cfg["SPITO_LOCATIONS"] = []   # [{id, name}]

    if not os.path.exists(ENV_PATH):
        return cfg

    with open(ENV_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # name lookups from "# <id> <name>" comment lines
    comment_names = {}
    for ln in lines:
        m = re.match(r"#\s*([\w-]+)\s+(.+?)\s*$", ln)
        if m:
            comment_names[m.group(1)] = m.group(2)

    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, _, val = s.partition("=")
        key = key.strip()
        val = val.strip()
        if key in SCALAR_KEYS:
            cfg[key] = _strip_quotes(val)
        elif key == "RECIPIENTS_EMAILS":
            try:
                cfg["RECIPIENTS_EMAILS"] = json.loads(val)
            except Exception:
                pass
        elif key in ("XE_LOCATION_IDS", "LOCATION_IDS"):
            try:
                ids = json.loads(val)
            except Exception:
                ids = []
            target = "XE_LOCATIONS" if key == "XE_LOCATION_IDS" else "SPITO_LOCATIONS"
            cfg[target] = [{"id": str(i), "name": comment_names.get(str(i), "")}
                           for i in ids]
    return cfg


def render_env(cfg):
    """Render the config dict back into the canonical .env layout."""
    def q(v):
        return '"{}"'.format(v)

    recipients = json.dumps(cfg.get("RECIPIENTS_EMAILS", []), ensure_ascii=False)
    xe_ids = json.dumps([l["id"] for l in cfg.get("XE_LOCATIONS", [])],
                        ensure_ascii=False)
    spito_ids = json.dumps([l["id"] for l in cfg.get("SPITO_LOCATIONS", [])],
                           ensure_ascii=False)

    def g(k):
        return cfg.get(k, SCALAR_KEYS.get(k, ""))

    lines = []
    lines.append('RECIPIENTS_EMAILS={}'.format(recipients))
    lines.append('SCRAPPER_API_KEY={}'.format(q(g("SCRAPPER_API_KEY"))))
    lines.append('')
    lines.append('# Resend Email API (used to send the notification emails)')
    lines.append('RESEND_API_KEY={}'.format(q(g("RESEND_API_KEY"))))
    lines.append('RESEND_FROM_EMAIL={}'.format(q(g("RESEND_FROM_EMAIL"))))
    lines.append('RESEND_WEBHOOK_SECRET={}'.format(q(g("RESEND_WEBHOOK_SECRET"))))
    lines.append('')
    lines.append('SCRAPERAPI_PREMIUM={}'.format(g("SCRAPERAPI_PREMIUM")))
    lines.append('SCRAPERAPI_ULTRA_PREMIUM={}'.format(g("SCRAPERAPI_ULTRA_PREMIUM")))
    lines.append('')
    lines.append('# How often the bot re-checks for new listings (in minutes)')
    lines.append('SEARCH_INTERVAL_MINUTES={}'.format(g("SEARCH_INTERVAL_MINUTES")))
    lines.append('')
    lines.append('')
    lines.append('#XE CONFIG')
    for k in ("MINIMUM_PRICE", "MAXIMUM_PRICE", "MINIMUM_SIZE", "MAXIMUM_SIZE",
              "MINIMUM_BEDROOMS", "MAXIMUM_BEDROOMS", "MINIMUM_LEVEL",
              "MAXIMUM_LEVEL", "SORTING"):
        lines.append('{}={}'.format(k, g(k)))
    lines.append('')
    lines.append('XE_LOCATION_IDS = {}'.format(xe_ids))
    lines.append('')
    for l in cfg.get("XE_LOCATIONS", []):
        lines.append('# {} {}'.format(l["id"], l.get("name", "")).rstrip())
    lines.append('')
    lines.append('')
    lines.append('#SPITOGATOS CONFIG')
    for k in ("LISTING_TYPE", "CATEGORY", "PRICE_LOW", "PRICE_HIGH",
              "LIVING_AREA_LOW", "LIVING_AREA_HIGH", "ROOMS_LOW", "ROOMS_HIGH",
              "FLOOR_NUMBER_LOW", "FLOOR_NUMBER_HIGH", "SORT_BY"):
        lines.append('{}={}'.format(k, g(k)))
    lines.append('LOCATION_IDS = {}'.format(spito_ids))
    for l in cfg.get("SPITO_LOCATIONS", []):
        lines.append('# {} {}'.format(l["id"], l.get("name", "")).rstrip())
    lines.append('')

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# --------------------------------------------------------------------------
# Live area lookup (the same endpoints the sites' own search boxes use)
# --------------------------------------------------------------------------

def search_xe(term):
    url = "https://www.xe.gr/services/places/autocomplete"
    params = {"query": term, "user_action": "typing",
              "country_code": "GR", "resolution": "1280x800"}
    r = requests.get(url, params=params, timeout=20,
                     headers={"User-Agent": UA, "Accept": "application/json",
                              "X-Requested-With": "XMLHttpRequest"})
    out = []
    for d in r.json():
        out.append({"id": d.get("place_id"), "name": d.get("name", "")})
    return out


def search_spito(term):
    url = "https://www.spitogatos.gr/n_api/v1/geographies/autocomplete"
    r = requests.post(url, data=json.dumps({"term": term}), timeout=20,
                      headers={"User-Agent": UA, "Accept": "application/json",
                               "Content-Type": "application/json",
                               "X-Requested-With": "XMLHttpRequest"})
    out = []
    data = r.json()
    if isinstance(data, list):
        for d in data:
            out.append({"id": str(d.get("geographyId")),
                        "name": d.get("fullName", ""),
                        "level": d.get("level")})
    return out


# --------------------------------------------------------------------------
# Bot process control.
# Prefers the systemd --user service (survives reboot); falls back to a raw
# detached subprocess when the service isn't installed.
# --------------------------------------------------------------------------

BOT_SERVICE = "housefinder-bot.service"


def _systemctl(*args):
    try:
        return subprocess.run(["systemctl", "--user", *args],
                              capture_output=True, text=True, timeout=15)
    except Exception:
        return None


def service_installed():
    r = _systemctl("list-unit-files", BOT_SERVICE, "--no-legend")
    return bool(r and r.returncode == 0 and BOT_SERVICE in r.stdout)


def _subprocess_pid():
    if not os.path.exists(PID_PATH):
        return None
    try:
        with open(PID_PATH) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # raises if not alive
        return pid
    except Exception:
        return None


def bot_status():
    """Return (running: bool, managed_by: 'systemd'|'subprocess'|'none')."""
    if service_installed():
        r = _systemctl("is-active", BOT_SERVICE)
        return (bool(r) and r.stdout.strip() == "active"), "systemd"
    pid = _subprocess_pid()
    return (pid is not None), ("subprocess" if pid else "none")


def _bot_cmd():
    """Return the command list that runs the bot (works in dev and packaged mode)."""
    if getattr(sys, "frozen", False):
        # Running as a PyInstaller bundle — re-invoke ourselves with --bot flag.
        return [sys.executable, "--bot"]
    # Dev mode — use the venv Python to run main.py.
    py = os.path.join(BASE_DIR, "venv", "bin", "python")
    if not os.path.exists(py):
        py = sys.executable
    return [py, os.path.join(BASE_DIR, "main.py")]


def _subprocess_start():
    logf = open(os.path.join(BASE_DIR, "data", "bot_stdout.log"), "a")
    p = subprocess.Popen(_bot_cmd(), cwd=BASE_DIR,
                         stdout=logf, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    with open(PID_PATH, "w") as f:
        f.write(str(p.pid))
    _register_autostart()
    return p.pid


def _subprocess_stop():
    _unregister_autostart()
    pid = _subprocess_pid()
    if not pid:
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
    try:
        os.remove(PID_PATH)
    except OSError:
        pass


# ── OS-specific autostart (bot survives reboot) ──────────────────────────────

_TASK_NAME = "HousefinderBot"
_LAUNCHD_PLIST = os.path.expanduser(
    "~/Library/LaunchAgents/com.housefinder.bot.plist")


def _register_autostart():
    """Register the bot to run at login (Windows / macOS). Linux uses systemd."""
    try:
        cmd = _bot_cmd()
        if PLATFORM == "Windows":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, _TASK_NAME, 0, winreg.REG_SZ,
                              " ".join(f'"{c}"' for c in cmd))
            winreg.CloseKey(key)
        elif PLATFORM == "Darwin":
            plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.housefinder.bot</string>
  <key>ProgramArguments</key><array>
    {"".join(f"<string>{c}</string>" for c in cmd)}
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key>
  <string>{os.path.join(BASE_DIR, "data", "bot_stdout.log")}</string>
  <key>StandardErrorPath</key>
  <string>{os.path.join(BASE_DIR, "data", "bot_stdout.log")}</string>
</dict></plist>"""
            os.makedirs(os.path.dirname(_LAUNCHD_PLIST), exist_ok=True)
            with open(_LAUNCHD_PLIST, "w") as f:
                f.write(plist)
            subprocess.run(["launchctl", "load", "-w", _LAUNCHD_PLIST],
                           capture_output=True)
    except Exception:
        pass   # non-fatal; bot still runs, just won't survive reboot


def _unregister_autostart():
    try:
        if PLATFORM == "Windows":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(key, _TASK_NAME)
            winreg.CloseKey(key)
        elif PLATFORM == "Darwin":
            subprocess.run(["launchctl", "unload", "-w", _LAUNCHD_PLIST],
                           capture_output=True)
            try:
                os.remove(_LAUNCHD_PLIST)
            except OSError:
                pass
    except Exception:
        pass


def tail(path, lines=200):
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except Exception as e:
        return f"(could not read {os.path.basename(path)}: {e})"


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template_string(PAGE)


@app.route("/api/config", methods=["GET"])
def api_get_config():
    return jsonify(parse_env())


@app.route("/api/config", methods=["POST"])
def api_save_config():
    cfg = request.get_json(force=True)
    render_env(cfg)
    return jsonify({"ok": True})


@app.route("/api/search")
def api_search():
    site = request.args.get("site")
    term = request.args.get("q", "").strip()
    if not term:
        return jsonify([])
    try:
        return jsonify(search_xe(term) if site == "xe" else search_spito(term))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/bot/status")
def api_bot_status():
    running, managed = bot_status()
    return jsonify({"running": running, "managed": managed,
                    "boot_persistent": managed == "systemd"})


@app.route("/api/bot/start", methods=["POST"])
def api_bot_start():
    running, _ = bot_status()
    if running:
        return jsonify({"ok": True, "msg": "already running"})
    if service_installed():
        _systemctl("start", BOT_SERVICE)
    else:
        _subprocess_start()
    return jsonify({"ok": True})


@app.route("/api/bot/stop", methods=["POST"])
def api_bot_stop():
    if service_installed():
        _systemctl("stop", BOT_SERVICE)
    else:
        _subprocess_stop()
    return jsonify({"ok": True})


@app.route("/api/bot/restart", methods=["POST"])
def api_bot_restart():
    if service_installed():
        _systemctl("restart", BOT_SERVICE)
    else:
        _subprocess_stop()
        _subprocess_start()
    return jsonify({"ok": True})


@app.route("/api/logs")
def api_logs():
    kind = request.args.get("kind", "activity")
    if kind == "error":
        # newest dated error file, if any
        logdir = os.path.join(BASE_DIR, "data", "logs")
        errs = sorted([f for f in os.listdir(logdir) if f.startswith("errors_")]) \
            if os.path.isdir(logdir) else []
        path = os.path.join(logdir, errs[-1]) if errs else ""
        return jsonify({"text": tail(path) if path else "(no errors logged 🎉)"})
    return jsonify({"text": tail(os.path.join(BASE_DIR, "data", "activity.log"))
                    or "(no activity yet — start the bot)"})


@app.route("/api/fresh-start", methods=["POST"])
def api_fresh_start():
    for p in (RESULTS_XE, RESULTS_SPITO):
        with open(p, "w", encoding="utf-8") as f:
            f.write("[]")
    return jsonify({"ok": True})


PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Housefinder</title>
<link rel="icon" type="image/png" href="https://raw.githubusercontent.com/Stathkost/Housefinder/main/assets/logo.png">
<style>
  :root { --y:#FFD43B; --bg:#0f1419; --card:#1b222b; --line:#2c3744; --txt:#e6edf3; --mut:#8b98a5; }
  * { box-sizing:border-box; }
  body { font-family:system-ui,Arial,sans-serif; margin:0; background:var(--bg); color:var(--txt); }
  header { background:var(--card); border-bottom:1px solid var(--line); padding:14px 22px;
           display:flex; align-items:center; gap:14px; position:sticky; top:0; z-index:5; }
  header h1 { font-size:18px; margin:0; } header h1 span { color:var(--y); }
  .pill { font-size:12px; padding:3px 10px; border-radius:20px; border:1px solid var(--line); color:var(--mut); }
  .pill.on { color:#10b981; border-color:#10b981; } .pill.off { color:#ef4444; border-color:#ef4444; }
  main { max-width:980px; margin:0 auto; padding:22px; }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px; margin-bottom:18px; }
  .card h2 { margin:0 0 14px; font-size:15px; color:var(--y); }
  label { display:block; font-size:12px; color:var(--mut); margin:10px 0 4px; }
  input, select { width:100%; padding:9px 10px; background:#0d1117; border:1px solid var(--line);
                  border-radius:8px; color:var(--txt); font-size:14px; }
  .row { display:flex; gap:10px; } .row > div { flex:1; }
  button { cursor:pointer; border:none; border-radius:8px; padding:9px 16px; font-size:14px; font-weight:600; }
  .btn-y { background:var(--y); color:#1b222b; } .btn-d { background:#2c3744; color:var(--txt); }
  .btn-r { background:#ef4444; color:#fff; } .btn-g { background:#10b981; color:#fff; }
  .chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:8px; }
  .chip { background:#0d1117; border:1px solid var(--line); border-radius:20px; padding:5px 10px 5px 12px;
          font-size:13px; display:flex; align-items:center; gap:8px; }
  .chip b { color:var(--y); font-weight:600; } .chip small { color:var(--mut); }
  .chip x { cursor:pointer; color:var(--mut); font-weight:700; } .chip x:hover { color:#ef4444; }
  .suggest { position:relative; }
  .results { position:absolute; left:0; right:0; top:100%; background:#0d1117; border:1px solid var(--line);
             border-radius:8px; margin-top:4px; max-height:240px; overflow:auto; z-index:9; }
  .results div { padding:8px 11px; cursor:pointer; font-size:13px; border-bottom:1px solid var(--line); }
  .results div:hover { background:#161b22; } .results div small { color:var(--mut); display:block; }
  .recip { display:flex; gap:8px; margin-bottom:6px; }
  .actions { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
  .toast { position:fixed; bottom:20px; left:50%; transform:translateX(-50%); background:var(--y); color:#1b222b;
           padding:11px 20px; border-radius:8px; font-weight:600; opacity:0; transition:.3s; pointer-events:none; }
  .toast.show { opacity:1; }
  .muted { color:var(--mut); font-size:12px; }
</style>
</head>
<body>
<header>
  <img src="https://raw.githubusercontent.com/Stathkost/Housefinder/main/assets/logo.png"
       width="36" height="36" style="border-radius:8px;flex-shrink:0">
  <h1><span>Housefinder</span> Config</h1>
  <span id="botPill" class="pill">bot: …</span>
  <span id="bootPill" class="pill" title="Whether the bot auto-starts after reboot"></span>
  <div style="flex:1"></div>
  <button class="btn-g" onclick="botStart()">Start</button>
  <button class="btn-d" onclick="botRestart()">Restart</button>
  <button class="btn-r" onclick="botStop()">Stop</button>
</header>
<main>
  <div class="card">
    <h2>Email (Resend)</h2>
    <div class="row">
      <div><label>From address</label><input id="RESEND_FROM_EMAIL" placeholder="noreply@yourdomain"></div>
      <div><label>Resend API key</label><input id="RESEND_API_KEY" type="password"></div>
    </div>
    <label>Webhook secret (optional)</label><input id="RESEND_WEBHOOK_SECRET" type="password">
    <label>Recipients</label>
    <div id="recipients"></div>
    <button class="btn-d" onclick="addRecipient('')">+ Add recipient</button>
  </div>

  <div class="card">
    <h2>ScraperAPI</h2>
    <label>API key</label><input id="SCRAPPER_API_KEY" type="password">
    <div class="row" style="margin-top:10px">
      <div><label>Premium proxies</label>
        <select id="SCRAPERAPI_PREMIUM"><option value="false">off</option><option value="true">on</option></select></div>
      <div><label>Ultra-premium proxies</label>
        <select id="SCRAPERAPI_ULTRA_PREMIUM"><option value="false">off</option><option value="true">on</option></select></div>
    </div>
  </div>

  <div class="card">
    <h2>Scheduler</h2>
    <label>Re-check for new listings every (minutes)</label>
    <input id="SEARCH_INTERVAL_MINUTES" type="number" min="1" style="max-width:200px">
    <p class="muted">Applies on the next bot (re)start. Use the Restart button after saving.</p>
  </div>

  <div class="grid">
    <div class="card">
      <h2>XE.gr filters</h2>
      <div class="row"><div><label>Min price €</label><input id="MINIMUM_PRICE"></div>
        <div><label>Max price €</label><input id="MAXIMUM_PRICE"></div></div>
      <div class="row"><div><label>Min size m²</label><input id="MINIMUM_SIZE"></div>
        <div><label>Max size m²</label><input id="MAXIMUM_SIZE"></div></div>
      <div class="row"><div><label>Min bedrooms</label><input id="MINIMUM_BEDROOMS"></div>
        <div><label>Max bedrooms</label><input id="MAXIMUM_BEDROOMS"></div></div>
      <div class="row"><div><label>Min level (e.g. L0)</label><input id="MINIMUM_LEVEL"></div>
        <div><label>Max level</label><input id="MAXIMUM_LEVEL"></div></div>
      <label>Sorting</label><input id="SORTING">
    </div>
    <div class="card">
      <h2>Spitogatos.gr filters</h2>
      <div class="row"><div><label>Listing type</label>
          <select id="LISTING_TYPE"><option>rent</option><option>buy</option></select></div>
        <div><label>Category</label><input id="CATEGORY"></div></div>
      <div class="row"><div><label>Min price €</label><input id="PRICE_LOW"></div>
        <div><label>Max price €</label><input id="PRICE_HIGH"></div></div>
      <div class="row"><div><label>Min area m²</label><input id="LIVING_AREA_LOW"></div>
        <div><label>Max area m²</label><input id="LIVING_AREA_HIGH"></div></div>
      <div class="row"><div><label>Min rooms</label><input id="ROOMS_LOW"></div>
        <div><label>Max rooms</label><input id="ROOMS_HIGH"></div></div>
      <div class="row"><div><label>Floor low</label><input id="FLOOR_NUMBER_LOW"></div>
        <div><label>Floor high</label><input id="FLOOR_NUMBER_HIGH"></div></div>
      <label>Sort by</label><input id="SORT_BY">
    </div>
  </div>

  <div class="card">
    <h2>XE locations</h2>
    <div class="suggest"><input id="xeSearch" placeholder="Search area, e.g. Peristeri…" autocomplete="off">
      <div id="xeResults" class="results" style="display:none"></div></div>
    <div id="xeChips" class="chips"></div>
  </div>
  <div class="card">
    <h2>Spitogatos locations</h2>
    <div class="suggest"><input id="spitoSearch" placeholder="Search area, e.g. Peristeri…" autocomplete="off">
      <div id="spitoResults" class="results" style="display:none"></div></div>
    <div id="spitoChips" class="chips"></div>
    <p class="muted">Tip: pick the municipality (level 4) entries for broad coverage.</p>
  </div>

  <div class="card">
    <h2>Actions</h2>
    <div class="actions">
      <button class="btn-y" onclick="save()">💾 Save config</button>
      <button class="btn-d" onclick="freshStart()">🧹 Fresh start (clear seen listings)</button>
      <span class="muted">Save writes to .env. Restart the bot to apply.</span>
    </div>
  </div>

  <div class="card">
    <h2>Help &amp; API Setup</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
      <div>
        <p style="margin:0 0 8px;font-size:13px;font-weight:600;color:var(--y)">🔑 ScraperAPI (for XE.gr)</p>
        <p class="muted">Used to fetch XE.gr search results through a proxy so the bot isn't IP-blocked.</p>
        <ol style="color:#c9d1d9;font-size:13px;padding-left:18px;margin:8px 0">
          <li>Create a free account at <a href="https://www.scraperapi.com" target="_blank" style="color:var(--y)">scraperapi.com</a></li>
          <li>Copy your API key from the dashboard</li>
          <li>Paste it in the <b>ScraperAPI</b> field above</li>
          <li>Free plan gives <b>1,000 credits/month</b> — enough for XE</li>
        </ol>
        <p class="muted">💡 Spitogatos uses a local headless browser — no ScraperAPI credits used.</p>
      </div>
      <div>
        <p style="margin:0 0 8px;font-size:13px;font-weight:600;color:var(--y)">📧 Resend (for emails)</p>
        <p class="muted">Sends the new-listing alert emails from your own domain.</p>
        <ol style="color:#c9d1d9;font-size:13px;padding-left:18px;margin:8px 0">
          <li>Create a free account at <a href="https://resend.com" target="_blank" style="color:var(--y)">resend.com</a></li>
          <li>Add and verify your sending domain (DNS records)</li>
          <li>Create an API key under <b>API Keys</b></li>
          <li>Set <b>From address</b> to something like <code style="color:var(--y)">noreply@yourdomain.com</code></li>
        </ol>
        <p class="muted">💡 Free plan: 3,000 emails/month — plenty for property alerts.</p>
      </div>
      <div>
        <p style="margin:0 0 8px;font-size:13px;font-weight:600;color:var(--y)">📍 Adding locations</p>
        <p class="muted">Type an area name (in Greek or Latin letters) in either location search box. Results come live from each site's own autocomplete — the IDs are always correct. Pick <b>level 4</b> entries for broad municipality coverage.</p>
      </div>
      <div>
        <p style="margin:0 0 8px;font-size:13px;font-weight:600;color:var(--y)">🔄 First-run browser setup</p>
        <p class="muted">The Spitogatos scraper needs a local Chromium browser (~150 MB, one-time download) to bypass DataDome protection for free.</p>
        <p class="muted">Run once in a terminal:</p>
        <code style="display:block;background:#0d1117;padding:8px 10px;border-radius:6px;font-size:12px;color:var(--y);margin-top:4px">python -m playwright install chromium</code>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>Legal &amp; Disclaimer</h2>
    <p style="font-size:13px;color:#c9d1d9;line-height:1.6;margin:0">
      Housefinder is an <b>unofficial</b> personal automation tool. It is not affiliated with,
      endorsed by, or connected to XE.gr or Spitogatos.gr in any way.<br><br>
      Web scraping may be subject to each website's <b>Terms of Service</b>. You are solely
      responsible for how you use this software and for ensuring your usage complies with
      applicable laws and the ToS of any website you access through it.<br><br>
      This software is provided <b>"as is"</b>, without warranty of any kind. The authors
      accept no liability for any damages or losses arising from its use. API keys, email
      credentials, and any personal data are stored <b>locally on your machine only</b> and
      are never transmitted to the authors or any third party beyond the configured services
      (ScraperAPI, Resend).
    </p>
  </div>

  <div class="card">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
      <h2 style="margin:0">Console</h2>
      <button id="tabActivity" class="btn-y" onclick="setLog('activity')">Activity</button>
      <button id="tabError" class="btn-d" onclick="setLog('error')">Errors</button>
      <div style="flex:1"></div>
      <label style="margin:0;display:flex;align-items:center;gap:6px;cursor:pointer">
        <input type="checkbox" id="autoscroll" checked style="width:auto"> auto-scroll</label>
    </div>
    <pre id="console" style="background:#0d1117;border:1px solid var(--line);border-radius:8px;
      padding:14px;height:300px;overflow:auto;margin:0;font-size:12.5px;line-height:1.5;
      white-space:pre-wrap;color:#c9d1d9">loading…</pre>
  </div>
</main>
<div id="toast" class="toast"></div>
<footer style="text-align:center;padding:22px 12px 32px;color:var(--mut);font-size:12px;line-height:1.8">
  <img src="https://raw.githubusercontent.com/Stathkost/Housefinder/main/assets/logo.png"
       width="36" height="36" style="border-radius:8px;vertical-align:middle;margin-right:8px">
  <b style="color:var(--txt)">Housefinder</b>
  &nbsp;·&nbsp; Built with 🤍 by
  <a href="https://github.com/stathis1998" target="_blank" style="color:var(--y);text-decoration:none">Stathis Stathopoulos</a>
  &amp;
  <a href="https://github.com/Stathkost" target="_blank" style="color:var(--y);text-decoration:none">Konstantinos Stathopoulos</a>
  <br>
  <span style="font-size:11px">Open source · Personal use only · No affiliation with XE.gr or Spitogatos.gr</span>
</footer>

<script>
let cfg = {};
const SCALARS = ["RESEND_API_KEY","RESEND_FROM_EMAIL","RESEND_WEBHOOK_SECRET","SCRAPPER_API_KEY","SCRAPERAPI_PREMIUM",
 "SCRAPERAPI_ULTRA_PREMIUM","MINIMUM_PRICE","MAXIMUM_PRICE","MINIMUM_SIZE","MAXIMUM_SIZE",
 "MINIMUM_BEDROOMS","MAXIMUM_BEDROOMS","MINIMUM_LEVEL","MAXIMUM_LEVEL","SORTING","LISTING_TYPE",
 "CATEGORY","PRICE_LOW","PRICE_HIGH","LIVING_AREA_LOW","LIVING_AREA_HIGH","ROOMS_LOW","ROOMS_HIGH",
 "FLOOR_NUMBER_LOW","FLOOR_NUMBER_HIGH","SORT_BY","SEARCH_INTERVAL_MINUTES"];

function toast(m){ const t=document.getElementById('toast'); t.textContent=m; t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'),2200); }

async function load(){
  cfg = await (await fetch('/api/config')).json();
  SCALARS.forEach(k=>{ const el=document.getElementById(k); if(el) el.value = cfg[k] ?? ''; });
  renderRecipients(); renderChips('xe'); renderChips('spito'); botStatus();
}

function renderRecipients(){
  const box=document.getElementById('recipients'); box.innerHTML='';
  (cfg.RECIPIENTS_EMAILS||[]).forEach((e,i)=>{
    const d=document.createElement('div'); d.className='recip';
    d.innerHTML=`<input value="${e}" oninput="cfg.RECIPIENTS_EMAILS[${i}]=this.value">
      <button class="btn-r" onclick="cfg.RECIPIENTS_EMAILS.splice(${i},1);renderRecipients()">✕</button>`;
    box.appendChild(d);
  });
}
function addRecipient(v){ (cfg.RECIPIENTS_EMAILS=cfg.RECIPIENTS_EMAILS||[]).push(v); renderRecipients(); }

function key(site){ return site==='xe'?'XE_LOCATIONS':'SPITO_LOCATIONS'; }
function renderChips(site){
  const box=document.getElementById(site+'Chips'); box.innerHTML='';
  (cfg[key(site)]||[]).forEach((l,i)=>{
    const c=document.createElement('div'); c.className='chip';
    c.innerHTML=`<span><b>${l.name||l.id}</b> <small>${l.id}</small></span>
      <x onclick="cfg.${key(site)}.splice(${i},1);renderChips('${site}')">✕</x>`;
    box.appendChild(c);
  });
}

function wireSearch(site){
  const inp=document.getElementById(site+'Search'); const res=document.getElementById(site+'Results');
  let t=null;
  inp.addEventListener('input',()=>{ clearTimeout(t); const q=inp.value.trim();
    if(q.length<2){ res.style.display='none'; return; }
    t=setTimeout(async()=>{
      res.innerHTML='<div>Searching…</div>'; res.style.display='block';
      try{
        const r=await (await fetch(`/api/search?site=${site}&q=`+encodeURIComponent(q))).json();
        if(r.error){ res.innerHTML='<div>Error: '+r.error+'</div>'; return; }
        if(!r.length){ res.innerHTML='<div>No matches</div>'; return; }
        res.innerHTML='';
        r.forEach(it=>{ const d=document.createElement('div');
          d.innerHTML=`${it.name}<small>${it.id}${it.level?(' · level '+it.level):''}</small>`;
          d.onclick=()=>{ const arr=cfg[key(site)]=cfg[key(site)]||[];
            if(!arr.some(x=>x.id==it.id)) arr.push({id:String(it.id),name:it.name});
            renderChips(site); res.style.display='none'; inp.value=''; };
          res.appendChild(d); });
      }catch(e){ res.innerHTML='<div>Request failed</div>'; }
    },280);
  });
  document.addEventListener('click',e=>{ if(!res.contains(e.target)&&e.target!==inp) res.style.display='none'; });
}

async function save(){
  SCALARS.forEach(k=>{ const el=document.getElementById(k); if(el) cfg[k]=el.value; });
  await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});
  toast('Saved to .env ✓');
}
async function freshStart(){
  if(!confirm('Clear all seen listings? Next run will re-email every current match.')) return;
  await fetch('/api/fresh-start',{method:'POST'}); toast('Seen listings cleared ✓');
}
async function botStatus(){
  const s=await (await fetch('/api/bot/status')).json();
  const p=document.getElementById('botPill');
  p.textContent='bot: '+(s.running?'running':'stopped'); p.className='pill '+(s.running?'on':'off');
  const b=document.getElementById('bootPill');
  if(s.boot_persistent){ b.textContent='auto-start: on'; b.className='pill on'; }
  else { b.textContent='auto-start: off'; b.className='pill off'; }
}
async function botStart(){ await fetch('/api/bot/start',{method:'POST'}); setTimeout(botStatus,800); toast('Bot started'); }
async function botStop(){ await fetch('/api/bot/stop',{method:'POST'}); setTimeout(botStatus,800); toast('Bot stopped'); }
async function botRestart(){ await fetch('/api/bot/restart',{method:'POST'}); setTimeout(botStatus,1200); toast('Bot restarting…'); }

let logKind='activity';
function setLog(k){ logKind=k;
  document.getElementById('tabActivity').className = k==='activity'?'btn-y':'btn-d';
  document.getElementById('tabError').className = k==='error'?'btn-y':'btn-d';
  refreshLog();
}
async function refreshLog(){
  try{
    const r=await (await fetch('/api/logs?kind='+logKind)).json();
    const el=document.getElementById('console'); const atBottom=document.getElementById('autoscroll').checked;
    el.textContent=r.text||''; if(atBottom) el.scrollTop=el.scrollHeight;
  }catch(e){}
}

wireSearch('xe'); wireSearch('spito'); load();
setInterval(botStatus,5000); setInterval(refreshLog,3000); refreshLog();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)

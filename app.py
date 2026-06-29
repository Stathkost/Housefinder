"""
Housefinder desktop entry point.

Normal launch  →  opens the embedded-browser config GUI window.
  python app.py           (dev)
  ./Housefinder           (packaged)

Bot-only mode  →  runs the scraper loop headlessly (used by OS autostart).
  python app.py --bot     (dev)
  ./Housefinder --bot     (packaged, called by systemd / Task Scheduler / launchd)
"""

import sys
import os

# Always work relative to this file so the app works from any cwd.
BASE_DIR = os.path.dirname(os.path.abspath(
    sys.executable if getattr(sys, "frozen", False) else __file__
))
os.chdir(BASE_DIR)

# ── Bot-only mode ────────────────────────────────────────────────────────────
if "--bot" in sys.argv:
    import main as _bot
    _bot.main()
    sys.exit(0)

# ── GUI mode ─────────────────────────────────────────────────────────────────
import socket
import time
import threading
import webbrowser

FLASK_HOST = "127.0.0.1"
FLASK_PORT = 5000


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((FLASK_HOST, port)) != 0


def _start_flask():
    from config_gui import app
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False,
            use_reloader=False, threaded=True)


def _wait_for_flask(timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _port_free(FLASK_PORT):
            return True
        time.sleep(0.25)
    return False


def _logo_path() -> str:
    return os.path.join(BASE_DIR, "assets", "logo.png")


def run_gui():
    # Start Flask server if not already running (e.g. the systemd GUI service).
    if _port_free(FLASK_PORT):
        t = threading.Thread(target=_start_flask, daemon=True)
        t.start()

    if not _wait_for_flask():
        # Fallback: open in system browser if webview fails to start.
        webbrowser.open(f"http://{FLASK_HOST}:{FLASK_PORT}")
        # Keep alive so Flask thread doesn't die.
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        return

    # Try PyWebView (embedded browser window).
    try:
        import webview
        logo = _logo_path()
        window = webview.create_window(
            title="🏠 Housefinder",
            url=f"http://{FLASK_HOST}:{FLASK_PORT}",
            width=1180,
            height=900,
            resizable=True,
            min_size=(900, 700),
        )
        kwargs = {}
        if os.path.exists(logo):
            kwargs["icon"] = logo          # Linux/Mac only; Windows uses .ico
        webview.start(**kwargs)
    except Exception:
        # If the webview backend isn't available (e.g. no display / missing lib),
        # fall back to opening the system browser and keeping the server alive.
        webbrowser.open(f"http://{FLASK_HOST}:{FLASK_PORT}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    run_gui()

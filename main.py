import os
import sys
import traceback
from dotenv import load_dotenv
import requests
import json
from datetime import date, datetime, timedelta
import time
import psutil
from colorama import init, Fore, Style

# Run relative to this file so the bot works no matter the working directory
# (e.g. when launched by systemd or the config GUI).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
os.makedirs("./data/logs", exist_ok=True)
ACTIVITY_LOG = "./data/activity.log"

load_dotenv()
init(autoreset=True, convert=False)
resend_api_key = os.getenv("RESEND_API_KEY")
sender = os.getenv("RESEND_FROM_EMAIL")
recipients_emails = json.loads(os.getenv("RECIPIENTS_EMAILS"))
scrapper_api_key = os.getenv("SCRAPPER_API_KEY")
# Some sites (e.g. Spitogatos) are now behind anti-bot protection and require
# ScraperAPI's premium/ultra-premium proxy pool. Toggle via the .env file.
scraperapi_premium = os.getenv("SCRAPERAPI_PREMIUM", "false").strip().lower() == "true"
scraperapi_ultra_premium = os.getenv("SCRAPERAPI_ULTRA_PREMIUM", "false").strip().lower() == "true"
# How often to re-check for new listings (minutes), configurable from the GUI.
try:
    SEARCH_INTERVAL_MINUTES = max(1, int(os.getenv("SEARCH_INTERVAL_MINUTES", "30") or 30))
except ValueError:
    SEARCH_INTERVAL_MINUTES = 30
COUNTDOWN_DURATION = SEARCH_INTERVAL_MINUTES * 60


def event(msg, color=Fore.LIGHTWHITE_EX):
    """Print and append a timestamped line to the activity log (read by the GUI console)."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{color}[{ts}] {msg}")
    try:
        with open(ACTIVITY_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def log_error(context, exc=None, message=None):
    """Record an error to the activity log and a dated error file, without crashing.

    Use `exc` for caught exceptions (a traceback is saved) or `message` for plain
    failures such as a fetch returning a bad status / no data."""
    detail = message if message is not None else (
        f"{type(exc).__name__}: {exc}" if exc is not None else "failed")
    event(f"ERROR in {context}: {detail}", Fore.LIGHTRED_EX)
    try:
        with open(f"./data/logs/errors_{date.today()}.txt", "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {context}: {detail}\n")
            tb = traceback.format_exc()
            if exc is not None and not tb.startswith("NoneType"):
                f.write(tb)
            f.write("\n" + "-" * 100 + "\n")
    except Exception:
        pass


def build_scraperapi_url(target_url):
    extra = ""
    if scraperapi_ultra_premium:
        extra = "&ultra_premium=true"
    elif scraperapi_premium:
        extra = "&premium=true"
    return f"http://api.scraperapi.com?api_key={scrapper_api_key}{extra}&url={target_url}"


BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_JS_FETCH = """async (u) => {
    const r = await fetch(u, {headers: {
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest"
    }});
    if (!(r.headers.get("content-type") || "").includes("json")) return null;
    return await r.json();
}"""


def _browser_session(warmup_url, warmup_ms=4000):
    """Open a headless Chromium context warmed up on warmup_url.
    Returns (playwright, browser, page) — caller must close browser."""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    )
    ctx = browser.new_context(user_agent=BROWSER_UA, locale="en-US",
                               viewport={"width": 1366, "height": 768})
    page = ctx.new_page()
    page.goto(warmup_url, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(warmup_ms)
    return pw, browser, page


def fetch_xe_via_browser(base_params):
    """Fetch ALL pages of XE results through a headless browser (free, no ScraperAPI).
    Returns list of all result objects across pages, or raises on failure."""
    pw, browser, page = _browser_session("https://www.xe.gr/property/")
    try:
        all_results, pg = [], 1
        while True:
            data = page.evaluate(_JS_FETCH, f"{base_params}&page={pg}")
            if not data or "results" not in data:
                raise RuntimeError(f"XE browser: no JSON on page {pg}")
            page_results = data["results"]
            all_results.extend(page_results)
            total_pages = data.get("paging", {}).get("total_pages", 1)
            event(f"XE page {pg}/{total_pages} — {len(page_results)} results (browser)")
            if pg >= total_pages:
                break
            pg += 1
            time.sleep(2)
        return all_results
    finally:
        browser.close()
        pw.stop()


def fetch_xe_via_scraperapi(base_params):
    """Fetch ALL pages of XE results through ScraperAPI (fallback).
    Returns list of all result objects across pages, or raises on failure."""
    all_results, pg = [], 1
    while True:
        url = build_scraperapi_url(f"{base_params}&page={pg}")
        r = requests.get(url, timeout=90)
        if not r.ok:
            raise RuntimeError(f"ScraperAPI HTTP {r.status_code} on XE page {pg}")
        data = r.json()
        page_results = data.get("results", [])
        all_results.extend(page_results)
        total_pages = data.get("paging", {}).get("total_pages", 1)
        event(f"XE page {pg}/{total_pages} — {len(page_results)} results (ScraperAPI)")
        if pg >= total_pages:
            break
        pg += 1
        time.sleep(3)
    return all_results


def fetch_spitogatos_via_browser(api_url):
    """Fetch Spitogatos search results through a headless browser (free, no ScraperAPI).
    Warms up on the home page + search page to build a convincing session.
    Retries once before raising. Returns parsed JSON dict, or raises on failure."""
    for attempt in range(1, 3):
        pw, browser, page = _browser_session("https://www.spitogatos.gr/en", warmup_ms=4000)
        try:
            # visit the search results page too — deeper session = less suspicious
            page.goto("https://www.spitogatos.gr/en/search/results",
                      wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            data = page.evaluate(_JS_FETCH, api_url)
            if data and "data" in data:
                return data
            event(f"Spitogatos browser attempt {attempt}/2: challenge not cleared, retrying...",
                  Fore.LIGHTYELLOW_EX)
        except Exception as e:
            if attempt == 2:
                raise
            event(f"Spitogatos browser attempt {attempt}/2 error: {e}, retrying...",
                  Fore.LIGHTYELLOW_EX)
        finally:
            browser.close()
            pw.stop()
        time.sleep(5)
    raise RuntimeError("Spitogatos browser: anti-bot challenge not cleared after 2 attempts")


def fetch_spitogatos_via_scraperapi(api_url):
    """Fetch Spitogatos search results through ScraperAPI (fallback, needs premium).
    Returns parsed JSON dict, or raises on failure."""
    r = requests.get(build_scraperapi_url(api_url), timeout=90)
    if not r.ok:
        raise RuntimeError(f"ScraperAPI HTTP {r.status_code} on Spitogatos"
                           + (" (needs SCRAPERAPI_PREMIUM=true)" if r.status_code in (403, 500) else ""))
    data = r.json()
    if "data" not in data:
        raise RuntimeError("ScraperAPI Spitogatos: unexpected response format")
    return data


def load_json_list(path):
    """Read a JSON list from disk, returning [] if the file is missing or empty
    (so a fresh checkout works without seed data files)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


script_trigger_count = 0
total_uptime = timedelta()


def clear_console():
    # Only clear when attached to a real terminal; avoids flooding log files
    # with escape codes when running under systemd / the GUI.
    if sys.stdout.isatty():
        os.system('cls' if os.name == 'nt' else 'clear')


def log():
     with open(f"./data/logs/logs_{date.today()}.txt", "a", encoding="utf-8") as f:
        f.write(f"E-mail sent to {recipients_emails}.\n")
        f.write(f"E-mail sent from {sender}.\n")
        f.write(f"------------------------------------------------------------------------------------------------------------------\n")
        f.write(f".\n")
        f.write(f".\n")
        f.write(f"\n\n")


def countdown_timer():
    global total_uptime
    is_tty = sys.stdout.isatty()
    event(f"Next check in {SEARCH_INTERVAL_MINUTES} min", Fore.LIGHTBLACK_EX)
    for remaining in range(COUNTDOWN_DURATION, 0, -1):
        if is_tty:
            minutes, seconds = divmod(remaining, 60)
            clear_console()
            print(
                f"{Fore.LIGHTWHITE_EX}{Style.BRIGHT}Countdown: {minutes:02d}:{seconds:02d}")
            print(f"{Fore.LIGHTWHITE_EX}Total Uptime: {total_uptime}")
            print(
                f"{Fore.LIGHTRED_EX}Script has been triggered {script_trigger_count} times.")
            print("")
            print("")
            print(f"{Fore.LIGHTWHITE_EX}Sender: {sender}")
            print(f"{Fore.LIGHTWHITE_EX}Recipients: {recipients_emails}")
            print(
                f"{Fore.LIGHTWHITE_EX}Python Scripted with 🤍 from Junior developer Konstantinosstath!")
            print("")
            print("")
            print(f"{Fore.LIGHTWHITE_EX}CPU Usage: {psutil.cpu_percent()}%")
            print(f"{Fore.LIGHTWHITE_EX}Memory Usage: {psutil.virtual_memory().percent}%")
            print(f"{Fore.LIGHTWHITE_EX}Press Ctrl+C to stop the script.")
        time.sleep(1)
        total_uptime += timedelta(seconds=1)


def information():
    print(f"Sender: {sender}")
    print(f"Recipients: {recipients_emails}")
    print("")
    time.sleep(3)


def send_email(subject, body):
    now = datetime.now().strftime('%d/%m/%Y %H:%M')
    subject_with_date_time = f"{subject} - {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"

    # Turn the newline-separated list of URLs into styled, clickable cards.
    links = [u.strip() for u in body.split("\n\n") if u.strip()]
    count = len(links)
    listings_html = "".join(
        f'<a href="{u}" target="_blank" '
        f'style="display:block;background:#ffffff;border:1px solid #e5e7eb;'
        f'border-left:4px solid #FFD43B;border-radius:10px;padding:14px 18px;'
        f'margin:10px 0;color:#1f2937;text-decoration:none;font-size:14px;'
        f'word-break:break-all;">🏠&nbsp; {u}</a>'
        for u in links
    )
    plural = "property" if count == 1 else "properties"

    html_content = f"""
    <!DOCTYPE html>
    <html>
      <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
      <body style="margin:0;padding:0;background:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif;color:#1f2937;">
        <div style="max-width:600px;margin:0 auto;padding:24px;">
          <div style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 18px rgba(0,0,0,.06);">
            <div style="background:linear-gradient(135deg,#1b222b,#0f1419);padding:28px 24px;text-align:center;">
              <img src="https://raw.githubusercontent.com/Stathkost/Housefinder/main/assets/logo.png"
                   alt="Housefinder" width="80" height="80" style="display:inline-block;margin-bottom:10px;border-radius:18px;">
              <h1 style="margin:0;color:#FFD43B;font-size:22px;">🏠 Property Finder</h1>
              <p style="margin:6px 0 0;color:#94a3b8;font-size:13px;">{now}</p>
            </div>
            <div style="padding:24px;">
              <h2 style="margin:0 0 4px;font-size:18px;">New listings 🌟</h2>
              <p style="margin:0 0 16px;color:#64748b;font-size:14px;">
                Found <b>{count}</b> new {plural} matching your filters. Tap any card to open it.
              </p>
              {listings_html}
            </div>
            <div style="background:#f8fafc;padding:16px 24px;text-align:center;border-top:1px solid #e5e7eb;">
              <p style="margin:0;color:#94a3b8;font-size:12px;">
                Python Scripted with 🤍 by Konstantinosstath
              </p>
            </div>
          </div>
        </div>
      </body>
    </html>
    """

    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {resend_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": sender,
            "to": recipients_emails,
            "subject": subject_with_date_time,
            "html": html_content,
        },
        timeout=30,
    )

    if response.ok:
        event(f"Email sent via Resend to {len(recipients_emails)} recipient(s) "
              f"(id={response.json().get('id')})", Fore.LIGHTGREEN_EX)
    else:
        log_error("send_email.resend",
                  message=f"Resend send FAILED: HTTP {response.status_code} {response.text[:200]}")


def main():
    global script_trigger_count
    event(f"Housefinder started. Interval={SEARCH_INTERVAL_MINUTES} min, "
          f"recipients={len(recipients_emails)}", Fore.LIGHTGREEN_EX)
    while True:
        try:
            clear_console()
            information()
            script_trigger_count += 1
            event(f"Cycle #{script_trigger_count} started")
            try:
                search_xe()
            except Exception as e:
                log_error("search_xe", e)
            try:
                search_spitogatos()
            except Exception as e:
                log_error("search_spitogatos", e)
            log()
            countdown_timer()
        except KeyboardInterrupt:
            event("Stopped by user (Ctrl+C).", Fore.LIGHTYELLOW_EX)
            break
        except Exception as e:
            # Never let the loop die; log and retry shortly (systemd also restarts us).
            log_error("main loop", e)
            time.sleep(30)


def search_xe():
    print("Running XE scrapper...")
    properties = load_json_list("./data/results.json")

    base_url = "https://www.xe.gr/en/property/results/map_search"

    filters = {
        "minimum_price": os.getenv("MINIMUM_PRICE"),
        "maximum_price": os.getenv("MAXIMUM_PRICE"),
        "minimum_size": os.getenv("MINIMUM_SIZE"),
        "maximum_size": os.getenv("MAXIMUM_SIZE"),
        "minimum_bedrooms": os.getenv("MINIMUM_BEDROOMS"),
        "maximum_bedrooms": os.getenv("MAXIMUM_BEDROOMS"),
        "minimum_bathrooms": os.getenv("MINIMUM_BATHROOMS"),
        "maximum_bathrooms": os.getenv("MAXIMUM_BATHROOMS"),
        "minimum_level": os.getenv("MINIMUM_LEVEL"),
        "maximum_level": os.getenv("MAXIMUM_LEVEL"),
        "sorting": os.getenv("SORTING"),
    }

    base_params = f"{base_url}?"
    for key, value in filters.items():
        if value:
            base_params += f"&{key}={value}"

    location_ids = json.loads(os.getenv("XE_LOCATION_IDS"))
    for location_id in location_ids:
        base_params += f"&geo_place_ids[]={location_id}"

    # Try browser first (free); fall back to ScraperAPI if it fails.
    results = []
    try:
        results = fetch_xe_via_browser(base_params)
    except Exception as e:
        log_error("search_xe.browser", e)
        event("XE: browser failed — falling back to ScraperAPI", Fore.LIGHTYELLOW_EX)
        try:
            results = fetch_xe_via_scraperapi(base_params)
        except Exception as e2:
            log_error("search_xe.scraperapi_fallback", e2)
            return

    new_properties = []
    for result in results:
        if any(obj.get("id") == result["id"] for obj in properties):
            continue

        new_properties.append(result)
        event(f"XE new property: {result['url']}", Fore.LIGHTYELLOW_EX)

    properties.extend(new_properties)

    with open("./data/results.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(properties, indent=4, ensure_ascii=False))

    if len(new_properties) == 0:
        event(f"XE: no new properties ({len(results)} checked).")
    else:
        event(f"XE: {len(new_properties)} new properties — sending email...", Fore.LIGHTGREEN_EX)
        send_email("(XE) New Properties Found!", "\n\n".join([prop["url"] for prop in new_properties]))

    with open(f"./data/logs/logs_{date.today()}.txt", "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}]\n(XE) found {len(new_properties)} new properties.\n")
        f.write(f"------------------------------------------------------------------------------------------------------------------\n")

    print("Done!")
    time.sleep(5)


def search_spitogatos():
    print("Running Spitogatos scrapper...")
    properties = load_json_list("./data/results_spitogatos.json")

    base_url = "https://www.spitogatos.gr/n_api/v1/properties/search-results"

    filters = { 
        "listingType": os.getenv("LISTING_TYPE"),
        "category": os.getenv("CATEGORY"),
        "priceLow": os.getenv("PRICE_LOW"),
        "priceHigh": os.getenv("PRICE_HIGH"),
        "livingAreaLow": os.getenv("LIVING_AREA_LOW"),
        "livingAreaHigh": os.getenv("LIVING_AREA_HIGH"),
        "roomsLow": os.getenv("ROOMS_LOW"),
        "roomsHigh": os.getenv("ROOMS_HIGH"),
        "floorNumberLow": os.getenv("FLOOR_NUMBER_LOW"),
        "floorNumberHigh": os.getenv("FLOOR_NUMBER_HIGH"),
        "sortBy": os.getenv("SORT_BY"),
    }

    final_url = f"{base_url}?"
    for key, value in filters.items():
        if value:
            final_url += f"&{key}={value}"

    location_ids = json.loads(os.getenv("LOCATION_IDS"))


    for location_id in location_ids:
        final_url += f"&areaIDs[]={location_id}"

    # Try browser first (free); fall back to ScraperAPI if it fails.
    # Note: ScraperAPI fallback for Spitogatos requires SCRAPERAPI_PREMIUM=true.
    data = None
    try:
        data = fetch_spitogatos_via_browser(final_url)
    except Exception as e:
        log_error("search_spitogatos.browser", e)
        event("Spitogatos: browser failed — falling back to ScraperAPI", Fore.LIGHTYELLOW_EX)
        try:
            data = fetch_spitogatos_via_scraperapi(final_url)
        except Exception as e2:
            log_error("search_spitogatos.scraperapi_fallback", e2)
            return

    results = data["data"]

    url_prop_path = "https://www.spitogatos.gr/en/property/21"

    new_properties = []
    for result in results:
        if any(obj.get("id") == result["id"] for obj in properties):
            continue

        new_properties.append(result)
        event(f"Spitogatos new property: {url_prop_path}{result['id']}", Fore.LIGHTYELLOW_EX)

    properties.extend(new_properties)

    with open("./data/results_spitogatos.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(properties, indent=4, ensure_ascii=False))

    if len(new_properties) == 0:
        event(f"Spitogatos: no new properties ({len(results)} checked).")
    else:
        event(f"Spitogatos: {len(new_properties)} new properties — sending email...", Fore.LIGHTGREEN_EX)
        send_email("(Spitogatos) New Properties Found!", "\n\n".join([f"{url_prop_path}{prop['id']}" for prop in new_properties]))

    with open(f"./data/logs/logs_{date.today()}.txt", "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}]\n(Spitogatos) found {len(new_properties)} new properties.\n")
        f.write(f"------------------------------------------------------------------------------------------------------------------\n")

    print("Done!")
    time.sleep(5)


if __name__ == "__main__":
    main()

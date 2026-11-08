#!/usr/bin/env python3
"""
iPhone Duo in-store pickup stock checker - Austin, TX Apple Stores only.

Checks every 10 seconds between 8:00 AM and 11:00 AM Austin time
(America/Chicago), every day. Outside that window it sleeps until the next
window opens. No third-party dependencies (Python 3.9+).

Alerts on any Austin store showing "available":
  - terminal message + bell
  - desktop notification + sound (macOS / Linux notify-send / Windows beep)
  - optional phone push via ntfy.sh  (--ntfy-topic YOUR_TOPIC)
"""

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
WINDOW_START = (8, 0)    # 8:00 AM
WINDOW_END = (11, 0)     # 11:00 AM
INTERVAL = 10            # seconds
AUSTIN_ZIP = "78701"
BUY_PAGE = "https://www.apple.com/shop/buy-iphone/iphone-duo"
FULFILLMENT = "https://www.apple.com/shop/fulfillment-messages"
PART_RE = re.compile(r"\b([A-Z0-9]{4,5}\d?[A-Z]{1,2}/A)\b")
BATCH = 8                # parts per fulfillment request
REALERT_SECONDS = 300    # re-alert for the same store/part every 5 min while in stock

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"),
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BUY_PAGE,
}


def log(msg):
    print(f"[{datetime.now(TZ):%Y-%m-%d %H:%M:%S %Z}] {msg}", flush=True)


def http_get(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def discover_parts():
    """Pull every iPhone Duo part number (US, LL/A) off Apple's buy page."""
    html = http_get(BUY_PAGE)
    parts = set()
    for m in re.finditer(r'"partNumber"\s*:\s*"([^"]+)"', html):
        parts.add(m.group(1))
    if not parts:
        parts.update(PART_RE.findall(html))
    return sorted(p for p in parts if p.endswith("LL/A"))


def check(parts):
    """Return list of (store_name, city, part, title, quote) currently available in Austin."""
    hits, stores_seen = [], set()
    for i in range(0, len(parts), BATCH):
        chunk = parts[i:i + BATCH]
        q = {"fae": "true", "pl": "true", "mts.0": "regular", "location": AUSTIN_ZIP}
        for n, p in enumerate(chunk):
            q[f"parts.{n}"] = p
        data = json.loads(http_get(f"{FULFILLMENT}?{urllib.parse.urlencode(q)}"))
        stores = (data.get("body", {}).get("content", {})
                  .get("pickupMessage", {}).get("stores", []))
        for s in stores:
            city = (s.get("city") or s.get("address", {}).get("city") or "").strip()
            if city.lower() != "austin":
                continue
            name = s.get("storeName", s.get("storeNumber", "?"))
            stores_seen.add(name)
            for part, info in (s.get("partsAvailability") or {}).items():
                if info.get("pickupDisplay") == "available":
                    title = (info.get("messageTypes", {}).get("regular", {})
                             .get("storePickupProductTitle")
                             or info.get("storePickupProductTitle") or part)
                    hits.append((name, city, part, title, info.get("pickupSearchQuote", "")))
    return hits, stores_seen


def notify(title, body, ntfy_topic=None):
    print("\a" * 3, end="", flush=True)
    system = platform.system()
    try:
        if system == "Darwin":
            safe_b = body.replace('"', "'")
            safe_t = title.replace('"', "'")
            subprocess.run(["osascript", "-e",
                            f'display notification "{safe_b}" with title "{safe_t}" sound name "Glass"'],
                           check=False)
            subprocess.Popen(["say", "iPhone Duo in stock in Austin"])
        elif system == "Linux":
            subprocess.run(["notify-send", "-u", "critical", title, body], check=False)
        elif system == "Windows":
            import winsound
            for _ in range(5):
                winsound.Beep(1500, 300)
    except Exception:
        pass
    if ntfy_topic:
        try:
            req = urllib.request.Request(
                f"https://ntfy.sh/{urllib.parse.quote(ntfy_topic)}",
                data=body.encode(), method="POST",
                headers={"Title": title, "Priority": "urgent", "Tags": "iphone,rotating_light",
                         "Click": BUY_PAGE})
            urllib.request.urlopen(req, timeout=10).read()
        except Exception as e:
            log(f"ntfy push failed: {e}")


def in_window(now):
    start = now.replace(hour=WINDOW_START[0], minute=WINDOW_START[1], second=0, microsecond=0)
    end = now.replace(hour=WINDOW_END[0], minute=WINDOW_END[1], second=0, microsecond=0)
    return start <= now < end, start, end


def next_window_start(now):
    inside, start, end = in_window(now)
    if now < start:
        return start
    return start + timedelta(days=1)


def main():
    ap = argparse.ArgumentParser(description="iPhone Duo stock checker - Austin Apple Stores, 8-11 AM CT, every 10 s")
    ap.add_argument("--parts", nargs="*", help="Part numbers to check (e.g. MXXX3LL/A). Default: auto-discover all.")
    ap.add_argument("--match", help="Only alert when product title contains this text (e.g. '512GB' or 'Night Sky').")
    ap.add_argument("--ntfy-topic", default=os.environ.get("NTFY_TOPIC"),
                    help="ntfy.sh topic for phone push alerts (install the ntfy app, subscribe to the same topic).")
    ap.add_argument("--once", action="store_true", help="Run a single check now, ignoring the time window.")
    ap.add_argument("--ignore-window", action="store_true", help="Check every 10 s around the clock.")
    args = ap.parse_args()

    parts = args.parts
    if not parts:
        for attempt in range(5):
            try:
                parts = discover_parts()
                if parts:
                    break
            except Exception as e:
                log(f"Part discovery failed ({e}); retrying...")
            time.sleep(5)
        if not parts:
            sys.exit("Could not discover iPhone Duo part numbers. Pass them with --parts.")
    log(f"Watching {len(parts)} iPhone Duo configurations at Austin Apple Stores.")

    last_alert = {}
    announced_stores = False
    while True:
        now = datetime.now(TZ)
        if not (args.once or args.ignore_window or in_window(now)[0]):
            nxt = next_window_start(now)
            log(f"Outside 8:00-11:00 AM window. Sleeping until {nxt:%a %b %d %I:%M %p %Z}.")
            time.sleep(max(1, (nxt - datetime.now(TZ)).total_seconds()))
            continue

        t0 = time.monotonic()
        try:
            hits, stores = check(parts)
            if not announced_stores and stores:
                log("Austin stores: " + ", ".join(sorted(stores)))
                announced_stores = True
            if args.match:
                hits = [h for h in hits if args.match.lower() in h[3].lower()]
            if hits:
                for store, city, part, title, quote in hits:
                    log(f"IN STOCK  {store}  {title} ({part})  {quote}")
                    key = (store, part)
                    if time.time() - last_alert.get(key, 0) >= REALERT_SECONDS:
                        last_alert[key] = time.time()
                        notify("iPhone Duo IN STOCK - Austin",
                               f"{title} at Apple {store}. {quote}".strip(), args.ntfy_topic)
            else:
                log("No stock at Austin stores.")
        except urllib.error.HTTPError as e:
            log(f"HTTP {e.code} from Apple (rate limited or blocked); continuing.")
        except Exception as e:
            log(f"Check failed: {e}")

        if args.once:
            break
        time.sleep(max(0, INTERVAL - (time.monotonic() - t0)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()

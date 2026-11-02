#!/usr/bin/env python3
"""
OLX.ba Mac mini watcher -> prave push notifikacije na iPhone preko ntfy (bez Apple dev računa).

Pokretanje:
  NTFY_TOPIC=tvoj-tajni-topic python3 watcher.py          # jedna provjera (za GitHub Actions / cron)
  NTFY_TOPIC=tvoj-tajni-topic python3 watcher.py --loop   # vrti se stalno, provjera svake 3 min
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ---------------- POSTAVKE ----------------
QUERIES = ["mac mini", "macmini"]
MAX_AGE_HOURS = 48
MIN_PRICE = 150                 # ispod ovoga je obično fake cijena
INCLUDE_NEGOTIABLE = False      # "Po dogovoru"
UNKNOWN_CHIP_MAX = 800          # oglasi bez čipa u naslovu (None = ignoriši ih)
MAX_PRICE = {                   # "povoljno" = cijena <= prag (KM)
    "M1": 800, "M2": 1000, "M2 Pro": 1500, "M3": 1100, "M3 Pro": 1700,
    "M4": 1300, "M4 Pro": 2300, "M5": 1600, "M5 Pro": 2600, "M6": 1900, "M6 Pro": 2900,
}
EXCLUDE = [
    "intel", "i3", "i5", "i7", "i9", "2012", "2014", "2018",
    "kutija", "kutiju", "stalak", "postolje", "stand", "hub", "dock", "docking",
    "adapter", "kabl", "kabal", "punjač", "punjac", "napajanje", "futrola", "torba",
    "tražim", "trazim", "kupujem", "kupim", "otkup", "dijelove", "dijelovi",
]
LOOP_SECONDS = 180
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen.json")
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
# ------------------------------------------

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
CHIP_RE = re.compile(r"(?<![a-z0-9])m\s?-?([1-6])(?:\s?-?(pro|max|ultra))?(?![0-9])")


def detect_chip(title):
    t = title.lower()
    m = CHIP_RE.search(t)
    if m:
        return "M" + m.group(1) + (" " + m.group(2).capitalize() if m.group(2) else "")
    if "2020" in t:
        return "M1"
    return None


def is_mac_mini(title):
    return "macmini" in title.lower().replace(" ", "").replace("-", "")


def is_excluded(title):
    return any(re.search(r"(?<![^\W_])" + re.escape(k) + r"(?![^\W_])", title, re.I) for k in EXCLUDE)


def to_float(v):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def parse_date(v):
    if v is None:
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
        n = float(v)
        return datetime.fromtimestamp(n / 1000 if n > 1e12 else n, tz=timezone.utc)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            d = datetime.strptime(v.replace("Z", "+0000"), fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def evaluate(item):
    """Vraća oznaku čipa ako je povoljan Mac mini, inače None."""
    title = str(item.get("title") or "")
    if not is_mac_mini(title) or is_excluded(title):
        return None
    chip = detect_chip(title)
    if chip in MAX_PRICE:
        limit = MAX_PRICE[chip]
    elif UNKNOWN_CHIP_MAX is not None:
        limit, chip = UNKNOWN_CHIP_MAX, chip or "Čip ?"
    else:
        return None
    price = to_float(item.get("price"))
    if not price:
        return chip if INCLUDE_NEGOTIABLE else None
    return chip if MIN_PRICE <= price <= limit else None


def fetch(query, with_filters=True):
    params = {"q": query, "page": 1, "per_page": 100}
    if with_filters:
        params.update(sort_by="date", sort_order="desc", created_gte=f"-{MAX_AGE_HOURS} hours")
    url = "https://api.olx.ba/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r).get("data") or []
    except urllib.error.HTTPError as e:
        if with_filters and 400 <= e.code < 500:
            return fetch(query, with_filters=False)
        raise


def notify(title, message, click=None, image=None, priority=4):
    if not NTFY_TOPIC:
        print(f"[bez NTFY_TOPIC] {title} | {message} | {click}")
        return
    payload = {"topic": NTFY_TOPIC, "title": title, "message": message, "priority": priority, "tags": ["desktop_computer"]}
    if click:
        payload["click"] = click
    if image:
        payload["attach"] = image
    req = urllib.request.Request(
        NTFY_SERVER.rstrip("/") + "/",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=15).read()


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"seen": [], "initialized": False}


def save_state(state):
    state["seen"] = state["seen"][-5000:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def check_once():
    state = load_state()
    seen = set(state["seen"])
    items = {}
    for q in QUERIES:
        for it in fetch(q):
            if "id" in it:
                items[it["id"]] = it

    cutoff = time.time() - MAX_AGE_HOURS * 3600
    deals = []
    for it in items.values():
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        state["seen"].append(it["id"])
        posted = parse_date(it.get("date"))
        if posted and posted.timestamp() < cutoff:
            continue
        chip = evaluate(it)
        if chip:
            deals.append((chip, it))

    if deals:
        if state["initialized"]:
            for chip, it in deals[:10]:
                price = to_float(it.get("price"))
                price_txt = f"{price:.0f} KM" if price else (it.get("display_price") or "Po dogovoru")
                notify(
                    f"Mac mini {chip} · {price_txt}",
                    str(it.get("title")),
                    click=f"https://olx.ba/artikal/{it['id']}",
                    image=it.get("image") if isinstance(it.get("image"), str) else None,
                )
        else:
            notify("Mac mini lovac je aktivan",
                   f"Trenutno {len(deals)} povoljnih oglasa. Od sada javljam samo nove.",
                   click="https://olx.ba/pretraga?q=mac+mini", priority=3)

    state["initialized"] = True
    save_state(state)
    print(f"{datetime.now():%H:%M:%S} provjereno {len(items)} oglasa, novih povoljnih: {len(deals)}")


if __name__ == "__main__":
    if "--loop" in sys.argv:
        while True:
            try:
                check_once()
            except Exception as e:  # mreža zna zezati – samo nastavi
                print("Greška:", e)
            time.sleep(LOOP_SECONDS)
    else:
        check_once()

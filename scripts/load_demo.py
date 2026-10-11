"""Generate demo traffic for the Grafana dashboard: ~30 bookings and ~20 chat turns over ~2 minutes.

Usage:  python scripts/load_demo.py [BASE_URL] [--bookings N] [--chats N] [--duration SECONDS]
        BASE_URL defaults to http://localhost:8000 (use http://localhost:3000 to go through nginx).

Standard library only. Bookings go to POST /api/restaurants/{slug}/bookings with a random
restaurant, a date in the next 7 days, a free slot from /availability and a random source.
Chats go to POST /api/chat and the SSE stream is read to the end.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from datetime import date, timedelta

SOURCES = ["web", "chat", "mcp", "google", "phone"]
FIRST = ["Aarav", "Diya", "Kabir", "Ananya", "Vihaan", "Isha", "Rohan", "Meera", "Arjun", "Saanvi",
         "Neil", "Tara", "Dev", "Riya", "Zoya", "Kian"]
LAST = ["Mehta", "Shah", "Iyer", "Patil", "Desai", "Kapoor", "Nair", "Joshi", "Rao", "Khan"]
CHAT_PROMPTS = [
    "Any rooftop places in Bandra for tonight?",
    "Suggest a pure veg thali place in Andheri",
    "Where can I get good seafood in Juhu?",
    "Which restaurant is best for a date night with live music?",
    "Do you have vegan options at {name}?",
    "What are the opening hours of {name}?",
    "Is there parking at {name}?",
    "What's the cancellation policy at {name}?",
    "Is {name} pet friendly?",
    "What is the average cost for two at {name}?",
    "Is there a table for 4 tomorrow at 8pm at {name}?",
    "Recommend something Japanese in Colaba",
    "Tell me about the dress code at {name}",
    "hi there!",
]


def request(base: str, method: str, path: str, body: dict | None = None, timeout: float = 30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        return resp.status, (json.loads(raw) if raw else None)


def error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        return str(json.loads(exc.read()).get("detail"))
    except Exception:  # noqa: BLE001
        return exc.reason or str(exc.code)


def make_booking(base: str, restaurants: list[dict], stats: Counter, sources: Counter) -> None:
    for _ in range(5):  # retry a few random picks if a day is full
        r = random.choice(restaurants)
        day = date.today() + timedelta(days=random.randint(0, 6))
        party = random.choices([1, 2, 2, 2, 3, 4, 4, 5, 6, 8], k=1)[0]
        qs = urllib.parse.urlencode({"date": day.isoformat(), "party_size": party})
        try:
            _, avail = request(base, "GET", f"/api/restaurants/{r['slug']}/availability?{qs}")
        except urllib.error.HTTPError as exc:
            stats["availability_error"] += 1
            print(f"  availability {r['slug']} {day}: {exc.code} {error_detail(exc)}")
            continue
        free = [s for s in (avail or {}).get("slots", []) if s.get("available")]
        if not free:
            continue
        slot = random.choice(free)
        start = slot.get("start") or f"{day.isoformat()}T{slot['time']}:00"
        source = random.choice(SOURCES)
        name = f"{random.choice(FIRST)} {random.choice(LAST)}"
        body = {"guest_name": name, "party_size": party, "start_time": start, "source": source,
                "phone": f"+91 9{random.randint(100000000, 999999999)}", "notes": "load_demo"}
        try:
            _, booking = request(base, "POST", f"/api/restaurants/{r['slug']}/bookings", body)
        except urllib.error.HTTPError as exc:
            stats["booking_rejected"] += 1
            print(f"  booking {r['slug']} {start}: {exc.code} {error_detail(exc)}")
            continue
        stats["bookings"] += 1
        sources[source] += 1
        print(f"  booked {booking.get('code', '?'):>9}  {r['name']:<20} {start[:16]}  party {party}  via {source}")
        return
    stats["booking_no_slot"] += 1


def chat(base: str, restaurants: list[dict], stats: Counter, intents: Counter) -> None:
    r = random.choice(restaurants)
    message = random.choice(CHAT_PROMPTS).format(name=r["name"])
    body = {"message": message, "thread_id": f"load-demo-{uuid.uuid4().hex[:10]}",
            "restaurant_slug": random.choice([None, r["slug"]])}
    req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "text/event-stream"})
    started = time.perf_counter()
    events, errors, intent = 0, 0, None
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            for line in resp:  # read the SSE stream to the end
                line = line.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    evt = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                events += 1
                kind = evt.get("type")
                if kind == "node" and evt.get("node") == "router" and evt.get("intent"):
                    intent = evt["intent"]
                elif kind == "error":
                    errors += 1
                elif kind == "done":
                    break
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        stats["chat_failed"] += 1
        print(f"  chat failed: {exc}")
        return
    stats["chats"] += 1
    stats["chat_errors"] += errors
    intents[intent or "unknown"] += 1
    print(f"  chat [{intent or '?':>9}] {time.perf_counter() - started:5.1f}s {events:3d} events  {message!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base_url", nargs="?", default="http://localhost:8000")
    ap.add_argument("--bookings", type=int, default=30)
    ap.add_argument("--chats", type=int, default=20)
    ap.add_argument("--duration", type=float, default=120, help="spread the traffic over this many seconds")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")

    try:
        _, restaurants = request(base, "GET", "/api/restaurants")
    except (urllib.error.URLError, ConnectionError) as exc:
        print(f"Cannot reach {base}/api/restaurants: {exc}. Is the stack up (docker compose up -d)?")
        return 1
    if not restaurants:
        print("No restaurants returned; seed the database first (python -m app.seed).")
        return 1
    print(f"{len(restaurants)} restaurants at {base}; sending {args.bookings} bookings + {args.chats} chats "
          f"over ~{args.duration:.0f}s")

    jobs = ["booking"] * args.bookings + ["chat"] * args.chats
    random.shuffle(jobs)
    gap = args.duration / max(len(jobs), 1)
    stats, sources, intents = Counter(), Counter(), Counter()
    t0 = time.perf_counter()
    for i, job in enumerate(jobs, 1):
        tick = time.perf_counter()
        print(f"[{i:2d}/{len(jobs)}] {job}")
        if job == "booking":
            make_booking(base, restaurants, stats, sources)
        else:
            chat(base, restaurants, stats, intents)
        time.sleep(max(0.0, gap - (time.perf_counter() - tick)) * random.uniform(0.5, 1.5))

    print("\nSummary")
    print(f"  elapsed           {time.perf_counter() - t0:.0f}s")
    print(f"  bookings created  {stats['bookings']}/{args.bookings}"
          f"  (rejected {stats['booking_rejected']}, no free slot {stats['booking_no_slot']},"
          f" availability errors {stats['availability_error']})")
    print(f"  by source         {dict(sources.most_common())}")
    print(f"  chats completed   {stats['chats']}/{args.chats}"
          f"  (failed {stats['chat_failed']}, error events {stats['chat_errors']})")
    print(f"  by intent         {dict(intents.most_common())}")
    print("  Grafana:          http://localhost:3001/d/tablewise-overview")
    return 0


if __name__ == "__main__":
    sys.exit(main())

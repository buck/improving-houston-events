#!/usr/bin/env python3
"""Scrape Danyal Mahmud's monthly "meetups at the Improving Houston office" LinkedIn posts.

Everything is fetched logged-out (no LinkedIn account involved):
  1. Discover posts from the public profile page (plus any URLs listed in posts.txt).
  2. For each candidate post, read the SocialMediaPosting JSON-LD: body text, comments, image.
  3. Parse event lines like "🐍 Tuesday 10/20 at 6pm - PyHou: https://lnkd.in/xyz".
  4. Resolve each link and read the schema.org Event JSON-LD on the destination page
     (Meetup, Eventbrite, Luma, LinkedIn Events ...) for exact times / cancellations.
  5. Merge into data/events.json, keeping a change history per event.

Stdlib only; run with the system python3.
"""

import datetime as dt
import html
import json
import re
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
EVENTS_FILE = DATA / "events.json"
POSTS_DIR = DATA / "posts"
LINKS_FILE = DATA / "links.json"
MANUAL_POSTS = ROOT / "posts.txt"

PROFILE_URL = "https://www.linkedin.com/in/danyalmahmud"
AUTHOR_SLUG = "danyalmahmud"
TZ = ZoneInfo("America/Chicago")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")
# A post is treated as a calendar post when at least this many lines parse as events.
MIN_EVENT_LINES = 3
# Keep re-checking a calendar post while it has events this recent or later.
RECHECK_DAYS = 3

WEEKDAYS = "monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun"
EVENT_LINE = re.compile(
    rf"""^\W*?(?P<emoji>[^\w\s]+(?:\s*[^\w\s]+)*)?\s*    # leading emoji(s)
    (?:(?P<dow>{WEEKDAYS})\.?,?\s+)?
    (?P<month>\d{{1,2}})/(?P<day>\d{{1,2}})(?:/\d{{2,4}})?
    (?:\s*(?:at|@)\s*(?P<time>\d{{1,2}}(?::\d{{2}})?\s*(?:am|pm)|noon))?
    \s*[-–—:]\s*
    (?P<rest>.+)$""",
    re.I | re.X,
)
URL_RE = re.compile(r"https?://\S+")
CHANGE_WORDS = re.compile(
    r"cancel|postpon|resched|moved|move[sd]? to|instead|correction|update[d:]|change[d]?|"
    r"no longer|not happening|new date|new time|\d{1,2}/\d{1,2}",
    re.I,
)


class FetchError(RuntimeError):
    pass


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def curl(url, *, head_only=False):
    """Fetch with curl (LinkedIn and some event sites are friendlier to it than urllib)."""
    cmd = ["curl", "-s", "--compressed", "--max-time", "30", "-A", UA,
           "-H", "Accept-Language: en-US,en;q=0.9",
           "-w", "\n%{http_code} %{url_effective} %{redirect_url}"]
    if not head_only:
        cmd.append("-L")
    else:
        cmd += ["-o", "/dev/null"]
    cmd.append(url)
    out = subprocess.run(cmd, capture_output=True, text=True, errors="replace").stdout
    body, _, trailer = out.rpartition("\n")
    parts = trailer.split(" ")
    code = int(parts[0]) if parts and parts[0].isdigit() else 0
    effective = parts[1] if len(parts) > 1 else url
    redirect = parts[2] if len(parts) > 2 else ""
    return code, body, effective, redirect


def json_ld(page):
    out = []
    for m in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(m)
        except json.JSONDecodeError:
            continue
        stack = d if isinstance(d, list) else [d]
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack.extend(x)
            elif isinstance(x, dict):
                if "@graph" in x:
                    stack.extend(x["@graph"])
                out.append(x)
    return out


def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n")
    tmp.replace(path)


def activity_id(url):
    m = re.search(r"activity[-:](\d{19})", url)
    return m.group(1) if m else None


def activity_time(aid):
    """LinkedIn activity IDs embed a millisecond timestamp in their top 41 bits."""
    return dt.datetime.fromtimestamp((int(aid) >> 22) / 1000, dt.timezone.utc)


# ---------------------------------------------------------------- discovery

def discover():
    """Return {activity_id: url} for Danyal's recent posts plus manual ones."""
    found = {}
    code, page, eff, _ = curl(PROFILE_URL)
    if code != 200 or "authwall" in eff:
        log(f"warning: profile fetch failed ({code} {eff}); using known posts only")
    else:
        for u in re.findall(r'https://www\.linkedin\.com/posts/([^"?&\s]+)', page):
            if u.startswith(AUTHOR_SLUG + "_") and (aid := activity_id(u)):
                found[aid] = "https://www.linkedin.com/posts/" + html.unescape(u)
        log(f"profile: {len(found)} posts by {AUTHOR_SLUG}")
    if MANUAL_POSTS.exists():
        for line in MANUAL_POSTS.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line and (aid := activity_id(line)):
                found.setdefault(aid, line)
    return found


# ---------------------------------------------------------------- post parsing

def fetch_post(url):
    aid = activity_id(url)
    canonical = f"https://www.linkedin.com/feed/update/urn:li:activity:{aid}/"
    code, page, eff, _ = curl(canonical)
    if code != 200 or "authwall" in eff or "login" in eff:
        raise FetchError(f"post {aid}: HTTP {code} -> {eff}")
    posting = next((x for x in json_ld(page) if x.get("@type") == "SocialMediaPosting"), None)
    if not posting or not posting.get("articleBody"):
        raise FetchError(f"post {aid}: no SocialMediaPosting JSON-LD (layout change or block?)")
    image = posting.get("image") or {}
    return {
        "id": aid,
        "url": posting.get("@id") or url,
        "published": posting.get("datePublished") or activity_time(aid).isoformat(),
        "headline": posting.get("headline", ""),
        "body": posting["articleBody"],
        "image": image.get("url") if isinstance(image, dict) else image,
        "comment_count": posting.get("commentCount"),
        "comments": [
            {
                "author": (c.get("author") or {}).get("name", ""),
                "published": c.get("datePublished", ""),
                "text": (c.get("text") or "").strip(),
            }
            for c in posting.get("comment", [])
        ],
        "fetched": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }


def parse_time(s):
    if not s:
        return None
    s = s.lower().replace(" ", "")
    if s == "noon":
        return "12:00"
    m = re.match(r"(\d{1,2})(?::(\d{2}))?(am|pm)", s)
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    h = h % 12 + (12 if ap == "pm" else 0)
    return f"{h:02d}:{mi:02d}"


def infer_date(month, day, published):
    """Pick the year that puts month/day closest to the post date."""
    best = None
    for y in (published.year - 1, published.year, published.year + 1):
        try:
            d = dt.date(y, month, day)
        except ValueError:
            continue
        gap = abs((d - published.date()).days)
        if best is None or gap < best[0]:
            best = (gap, d)
    return best[1] if best else None


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def parse_events(post):
    published = dt.datetime.fromisoformat(post["published"].replace("Z", "+00:00")).astimezone(TZ)
    events, seen = [], {}
    for raw in post["body"].splitlines():
        line = raw.strip()
        m = EVENT_LINE.match(line)
        if not m:
            continue
        d = infer_date(int(m["month"]), int(m["day"]), published)
        if not d:
            continue
        rest = m["rest"].strip()
        urls = URL_RE.findall(rest)
        title = URL_RE.sub("", rest).strip().rstrip(":-–— ").strip()
        if not title:
            continue
        key = slug(title)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            key = f"{key}-{seen[key]}"
        events.append({
            "key": key,
            "title": title,
            "emoji": (m["emoji"] or "").strip(),
            "date": d.isoformat(),
            "time": parse_time(m["time"]),
            "link": urls[0].rstrip(".,)") if urls else None,
            "line": line,
        })
    return events


# ---------------------------------------------------------------- link enrichment

def resolve(link, cache):
    """Follow lnkd.in shorteners to the real destination (cached forever)."""
    if link in cache:
        return cache[link]
    target = link
    if "lnkd.in/" in link:
        code, body, eff, redirect = curl(link, head_only=True)
        if redirect:
            target = redirect
        else:
            _, body, _, _ = curl(link)
            hrefs = [h for h in re.findall(r'href="(https?://[^"]+)"', body)
                     if "linkedin.com" not in h and "licdn.com" not in h]
            target = html.unescape(hrefs[0]) if hrefs else link
    cache[link] = target
    return target


def source_event(url):
    """Read the schema.org Event from an event page; None if there isn't exactly one useful one."""
    if "linkedin.com/" in url:
        return None  # LinkedIn events/company pages are behind the login wall
    try:
        code, page, eff, _ = curl(url)
    except Exception as e:  # noqa: BLE001
        log(f"  source fetch failed {url}: {e}")
        return None
    if code != 200:
        return None
    evs = [x for x in json_ld(page) if "Event" in str(x.get("@type")) and x.get("startDate")]
    if not evs:
        return None
    if len(evs) > 1:
        # group pages list many events; let the caller pick by date
        return {"multiple": [_event_fields(e) for e in evs]}
    return _event_fields(evs[0])


def _event_fields(e):
    loc = e.get("location") or {}
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    addr = loc.get("address") if isinstance(loc, dict) else None
    if isinstance(addr, dict):
        addr = addr.get("streetAddress") or ""
    status = (e.get("eventStatus") or "").rsplit("/", 1)[-1]
    return {
        "name": html.unescape(e.get("name") or ""),
        "start": e.get("startDate"),
        "end": e.get("endDate"),
        "status": status or None,
        "venue": html.unescape((loc.get("name") if isinstance(loc, dict) else "") or ""),
        "address": html.unescape(addr or ""),
    }


def match_source(src, date):
    if not src:
        return None
    cands = src["multiple"] if "multiple" in src else [src]
    for c in cands:
        try:
            start = dt.datetime.fromisoformat(c["start"].replace("Z", "+00:00"))
        except ValueError:
            continue
        local = start.astimezone(TZ) if start.tzinfo else start
        c = dict(c, local_date=local.date().isoformat(), local_time=local.strftime("%H:%M"))
        if c["local_date"] == date or "multiple" not in src:
            return c
    return None


# ---------------------------------------------------------------- merge

def merge(store, post, parsed, link_cache, today):
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    events = store["events"]
    current_ids = set()
    for p in parsed:
        eid = f"{post['id']}:{p['key']}"
        current_ids.add(eid)
        ev = events.get(eid)
        fields = {k: p[k] for k in ("title", "emoji", "date", "time", "link", "line")}
        if ev is None:
            ev = events[eid] = {"id": eid, "post": post["id"], **fields,
                                "status": "scheduled", "first_seen": now, "history": []}
            log(f"  + {p['date']} {p['title']}")
        else:
            changed = {k: [ev.get(k), v] for k, v in fields.items() if ev.get(k) != v and k != "line"}
            if changed:
                ev["history"].append({"at": now, "source": "post edit", "changes": changed})
                log(f"  ~ {p['title']}: {changed}")
            ev.update(fields)
            if ev["status"] == "removed":
                ev["status"] = "scheduled"
                ev["history"].append({"at": now, "source": "post edit", "changes": {"status": ["removed", "scheduled"]}})
        ev["last_seen"] = now

        # enrichment from the linked event page, only for upcoming events
        if p["link"] and p["date"] >= today:
            target = resolve(p["link"], link_cache)
            ev["source_url"] = target
            m = match_source(source_event(target), p["date"])
            if m:
                prev = ev.get("source") or {}
                diffs = {k: [prev.get(k), m.get(k)] for k in ("start", "end", "status", "name")
                         if prev and prev.get(k) != m.get(k)}
                if diffs:
                    ev["history"].append({"at": now, "source": "event page", "changes": diffs})
                ev["source"] = m
                flags = []
                if m["local_date"] != p["date"]:
                    flags.append(f"event page says {m['local_date']}")
                if m.get("status") in ("EventCancelled", "EventPostponed"):
                    ev["status"] = "cancelled" if m["status"] == "EventCancelled" else "postponed"
                elif ev["status"] in ("cancelled", "postponed"):
                    ev["status"] = "scheduled"
                addr = (m.get("address") or "") + " " + (m.get("venue") or "")
                if addr.strip() and not re.search(r"10111\s+richmond|improving", addr, re.I):
                    flags.append(f"event page venue: {addr.strip()}")
                ev["flags"] = flags

    # events that vanished from an edited post
    for eid, ev in events.items():
        if ev["post"] == post["id"] and eid not in current_ids and ev["status"] != "removed":
            ev["history"].append({"at": now, "source": "post edit", "changes": {"status": [ev["status"], "removed"]}})
            ev["status"] = "removed"
            log(f"  - {ev['date']} {ev['title']} (no longer in post)")


def comment_alerts(old_post, post):
    """Comments that look like schedule changes and weren't there last run."""
    old = {(c["author"], c["text"]) for c in (old_post or {}).get("comments", [])}
    return [c for c in post["comments"]
            if (c["author"], c["text"]) not in old and CHANGE_WORDS.search(c["text"])]


def main():
    store = load_json(EVENTS_FILE, {"posts": {}, "events": {}})
    link_cache = load_json(LINKS_FILE, {})
    today_dt = dt.datetime.now(TZ).date()
    today = today_dt.isoformat()

    candidates = discover()
    # keep re-checking known calendar posts that still have upcoming events
    cutoff = (today_dt - dt.timedelta(days=RECHECK_DAYS)).isoformat()
    for aid, meta in store["posts"].items():
        if meta.get("calendar") and meta.get("last_event", "") >= cutoff:
            candidates.setdefault(aid, meta["url"])

    alerts, errors = [], []
    for aid, url in sorted(candidates.items()):
        meta = store["posts"].get(aid)
        if meta and not meta.get("calendar"):
            continue  # already looked at it; not a calendar post
        if meta and meta.get("calendar") and meta.get("last_event", "") < cutoff:
            continue  # past month, frozen
        log(f"post {aid} {url}")
        try:
            post = fetch_post(url)
        except FetchError as e:
            errors.append(str(e))
            log(f"  ERROR {e}")
            continue
        parsed = parse_events(post)
        is_cal = len(parsed) >= MIN_EVENT_LINES
        snap_path = POSTS_DIR / f"{aid}.json"
        old_post = load_json(snap_path, None)
        store["posts"][aid] = {
            "url": post["url"], "published": post["published"], "calendar": is_cal,
            "headline": post["headline"],
            "last_event": max((p["date"] for p in parsed), default=""),
        }
        if not is_cal:
            log("  not a calendar post")
            continue
        save_json(snap_path, post)
        merge(store, post, parsed, link_cache, today)
        for c in comment_alerts(old_post, post):
            alerts.append(f"{c['author']}: {c['text'][:200]}")

    store["updated"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    store["events"] = dict(sorted(store["events"].items(), key=lambda kv: (kv[1]["date"], kv[1]["time"] or "", kv[0])))
    save_json(EVENTS_FILE, store)
    save_json(LINKS_FILE, link_cache)

    if not any(m.get("calendar") for m in store["posts"].values()):
        errors.append("no calendar posts known at all")
    # machine-readable summary for run.sh
    print(json.dumps({"errors": errors, "comment_alerts": alerts}))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

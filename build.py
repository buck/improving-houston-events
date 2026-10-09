#!/usr/bin/env python3
"""Render data/events.json into the static GitHub Pages site in docs/.

Outputs:
  docs/index.html            calendar page
  docs/improving-houston.ics subscribable iCalendar feed
  docs/events.json           public copy of the data
"""

import calendar
import datetime as dt
import html
import json
import shutil
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"
TZ = ZoneInfo("America/Chicago")
SITE_URL = "https://buck.github.io/improving-houston-events/"
ICS_NAME = "improving-houston.ics"
VENUE = "Improving Houston, 10111 Richmond Ave Suite 100, Houston, TX 77042"
DEFAULT_HOURS = 2

e = html.escape


def load():
    store = json.loads((DATA / "events.json").read_text())
    posts = {}
    for p in (DATA / "posts").glob("*.json"):
        posts[p.stem] = json.loads(p.read_text())
    return store, posts


def start_end(ev):
    """Best-known local start/end datetimes: event page beats post text."""
    src = ev.get("source") or {}
    start = end = None
    if src.get("start") and src.get("local_date") == ev["date"]:
        try:
            start = dt.datetime.fromisoformat(src["start"].replace("Z", "+00:00")).astimezone(TZ)
            if src.get("end"):
                end = dt.datetime.fromisoformat(src["end"].replace("Z", "+00:00")).astimezone(TZ)
        except ValueError:
            start = end = None
    if start is None:
        d = dt.date.fromisoformat(ev["date"])
        if not ev.get("time"):
            return d, None  # all-day
        h, m = map(int, ev["time"].split(":"))
        start = dt.datetime(d.year, d.month, d.day, h, m, tzinfo=TZ)
    if end is None or end <= start:
        end = start + dt.timedelta(hours=DEFAULT_HOURS)
    return start, end


def fmt_time(t):
    s = t.strftime("%-I:%M %p").replace(":00", "").lower()
    return s.replace(" ", "")


def link_for(ev):
    return ev.get("source_url") or ev.get("link")


# ---------------------------------------------------------------- iCalendar

def ics_escape(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_fold(line):
    out, b = [], line.encode()
    while len(b) > 74:
        cut = 74
        while (b[cut] & 0xC0) == 0x80:  # don't split a UTF-8 sequence
            cut -= 1
        out.append(b[:cut].decode())
        b = b" " + b[cut:]
    out.append(b.decode())
    return "\r\n".join(out)


def build_ics(events, updated):
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//improving-houston-events//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "X-WR-CALNAME:Meetups at Improving Houston",
        "X-WR-TIMEZONE:America/Chicago",
        "X-PUBLISHED-TTL:PT12H", "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
    ]
    for ev in events:
        if ev["status"] == "removed":
            continue
        start, end = start_end(ev)
        src = ev.get("source") or {}
        desc = []
        if src.get("name") and src["name"] != ev["title"]:
            desc.append(src["name"])
        if link_for(ev):
            desc.append(link_for(ev))
        if ev.get("flags"):
            desc.append("Check: " + "; ".join(ev["flags"]))
        desc.append(f"Listed by Danyal Mahmud on LinkedIn. Calendar: {SITE_URL}")
        title = ev["title"]
        if ev["status"] in ("cancelled", "postponed"):
            title = f"{ev['status'].upper()}: {title}"
        # stable per-event stamp so the feed only changes when events do
        changed = (ev["history"][-1]["at"] if ev.get("history") else ev["first_seen"])
        stamp = dt.datetime.fromisoformat(changed).astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        lines += ["BEGIN:VEVENT", f"UID:{ev['id'].replace(':', '-')}@improving-houston-events",
                  f"DTSTAMP:{stamp}"]
        if isinstance(start, dt.datetime):
            lines += [f"DTSTART:{start.astimezone(dt.timezone.utc):%Y%m%dT%H%M%SZ}",
                      f"DTEND:{end.astimezone(dt.timezone.utc):%Y%m%dT%H%M%SZ}"]
        else:
            lines += [f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
                      f"DTEND;VALUE=DATE:{start + dt.timedelta(days=1):%Y%m%d}"]
        lines += [f"SUMMARY:{ics_escape(title)}",
                  f"LOCATION:{ics_escape(VENUE)}",
                  f"DESCRIPTION:{ics_escape(chr(10).join(desc))}",
                  "STATUS:" + ("CANCELLED" if ev["status"] == "cancelled" else "CONFIRMED")]
        if link_for(ev):
            lines.append(f"URL:{link_for(ev)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(ics_fold(l) for l in lines) + "\r\n"


# ---------------------------------------------------------------- HTML

CSS = """
/* Layout: one narrow column; a month strip of day cells on top, then a day-by-day agenda. */
:root {
  --bg: #f6f7f5; --surface: #ffffff; --ink: #18211f; --muted: #5d6965;
  --line: #dde3e0; --accent: #0b6e66; --accent-soft: #e0f0ec;
  --warn: #9a5b00; --warn-soft: #fbeed8; --bad: #b3261e; --bad-soft: #fbe3e1;
  --display: "Archivo", "Helvetica Neue", Arial, sans-serif;
  --body: "Source Sans 3", "Segoe UI", system-ui, sans-serif;
  --mono: "JetBrains Mono", ui-monospace, Menlo, monospace;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #111816; --surface: #18211f; --ink: #e7eeeb; --muted: #9aa8a3;
  --line: #2a3632; --accent: #5cc4b6; --accent-soft: #163a35;
  --warn: #f0b45c; --warn-soft: #3a2c14; --bad: #ff8a80; --bad-soft: #3d1c1a; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #111816; --surface: #18211f; --ink: #e7eeeb; --muted: #9aa8a3;
  --line: #2a3632; --accent: #5cc4b6; --accent-soft: #163a35;
  --warn: #f0b45c; --warn-soft: #3a2c14; --bad: #ff8a80; --bad-soft: #3d1c1a; color-scheme: dark }
* { box-sizing: border-box }
body { margin: 0; background: var(--bg); color: var(--ink); font: 17px/1.5 var(--body); }
.wrap { max-width: 760px; margin: 0 auto; padding-inline: 16px; padding-block: 32px 64px; display: grid; gap: 40px }
a { color: var(--accent) }
a:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px }
header { display: grid; gap: 12px }
.wrap > * { min-width: 0 }
h1, .addr { overflow-wrap: anywhere }
.eyebrow { font: 600 12px/1 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted) }
h1 { font: 800 clamp(30px, 6vw, 44px)/1.05 var(--display); letter-spacing: -.02em; margin: 0; text-wrap: balance }
.addr { color: var(--muted); margin: 0 }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px }
.btn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; border-radius: 999px;
  border: 1px solid var(--accent); color: var(--accent); text-decoration: none; font-weight: 600; font-size: 15px }
.btn.primary { background: var(--accent); color: var(--bg) }
h2 { font: 700 22px/1.2 var(--display); margin: 0 0 12px; letter-spacing: -.01em }
.month { display: grid; gap: 16px }
.strip { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 3px; max-width: 440px; font-variant-numeric: tabular-nums }
.strip .dow { font: 600 11px/1 var(--mono); color: var(--muted); text-align: center; padding-bottom: 4px; text-transform: uppercase }
.cell { aspect-ratio: 1.15; max-width: 100%; border-radius: 6px; background: var(--surface); border: 1px solid var(--line);
  display: grid; place-items: center; font: 500 14px/1 var(--mono); color: var(--muted); text-decoration: none; position: relative }
.cell.has { background: var(--accent-soft); border-color: transparent; color: var(--ink); font-weight: 700 }
.cell.has::after { content: attr(data-n); position: absolute; top: 3px; right: 5px; font-size: 10px; color: var(--accent) }
.cell.today { outline: 2px solid var(--ink); outline-offset: -2px }
.cell.past { opacity: .45 }
.cell.blank { visibility: hidden }
.agenda { display: grid; gap: 0; border-top: 1px solid var(--line) }
.day { display: grid; grid-template-columns: 72px 1fr; gap: 16px; padding-block: 14px; border-bottom: 1px solid var(--line); scroll-margin-top: 16px }
.date { display: grid; align-content: start; gap: 2px }
.date .dnum { font: 800 30px/1 var(--display) }
.date .dname { font: 600 12px/1 var(--mono); color: var(--muted); text-transform: uppercase; letter-spacing: .06em }
.day.is-today .dnum { color: var(--accent) }
.events { display: grid; gap: 12px; min-width: 0 }
.ev { display: grid; grid-template-columns: 76px 1fr; gap: 8px; align-items: baseline }
.ev .t { font: 500 14px/1.4 var(--mono); color: var(--muted); font-variant-numeric: tabular-nums }
.ev .body { min-width: 0 }
.ev .title { font-weight: 700; font-size: 18px; color: var(--ink); text-decoration: none }
.ev a.title:hover { color: var(--accent); text-decoration: underline }
.ev .sub { color: var(--muted); font-size: 15px; overflow-wrap: anywhere }
.ev.cancelled .title, .ev.removed .title { text-decoration: line-through; color: var(--muted) }
.chip { display: inline-block; font: 700 11px/1 var(--mono); letter-spacing: .05em; text-transform: uppercase;
  padding: 4px 7px; border-radius: 4px; margin-left: 6px; vertical-align: 2px }
.chip.bad { background: var(--bad-soft); color: var(--bad) }
.chip.warn { background: var(--warn-soft); color: var(--warn) }
.flag { color: var(--warn); font-size: 14px }
details.past > summary { cursor: pointer; font: 600 15px var(--body); color: var(--muted); padding-block: 8px }
.notes { display: grid; gap: 10px }
.comment { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px }
.comment .who { font-weight: 700 }
.comment .when { color: var(--muted); font: 12px var(--mono) }
.comment.hot { border-color: var(--warn) }
.src img { border-radius: 8px; border: 1px solid var(--line); display: block }
footer { color: var(--muted); font-size: 14px; display: grid; gap: 6px }
@media (max-width: 480px) {
  .day { grid-template-columns: 52px 1fr; gap: 10px }
  .date .dnum { font-size: 24px }
  .ev { grid-template-columns: 1fr; gap: 0 }
}
"""


def chips(ev):
    out = []
    if ev["status"] == "cancelled":
        out.append('<span class="chip bad">Cancelled</span>')
    elif ev["status"] == "postponed":
        out.append('<span class="chip bad">Postponed</span>')
    elif ev["status"] == "removed":
        out.append('<span class="chip warn">Dropped from list</span>')
    return "".join(out)


def render_event(ev):
    start, end = start_end(ev)
    when = (f"{fmt_time(start)}–{fmt_time(end)}" if isinstance(start, dt.datetime) else "All day")
    href = link_for(ev)
    title = f"{ev['emoji']} {ev['title']}".strip()
    title_html = (f'<a class="title" href="{e(href)}" target="_blank" rel="noopener">{e(title)}</a>'
                  if href else f'<span class="title">{e(title)}</span>')
    src = ev.get("source") or {}
    sub = []
    if src.get("name") and src["name"].lower() != ev["title"].lower():
        sub.append(f'<div class="sub">{e(src["name"])}</div>')
    for f in ev.get("flags") or []:
        sub.append(f'<div class="flag">⚠ {e(f)}</div>')
    return (f'<div class="ev {e(ev["status"])}"><div class="t">{when}</div>'
            f'<div class="body">{title_html}{chips(ev)}{"".join(sub)}</div></div>')


def render_days(events, today):
    by_day = {}
    for ev in events:
        by_day.setdefault(ev["date"], []).append(ev)
    out = []
    for d, evs in sorted(by_day.items()):
        dd = dt.date.fromisoformat(d)
        evs.sort(key=lambda x: (start_end(x)[0].strftime("%H%M") if isinstance(start_end(x)[0], dt.datetime) else "0000"))
        cls = "day is-today" if dd == today else "day"
        out.append(f'<div class="{cls}" id="d{d}"><div class="date"><span class="dname">{dd:%a}</span>'
                   f'<span class="dnum">{dd.day}</span><span class="dname">{dd:%b}</span></div>'
                   f'<div class="events">{"".join(render_event(x) for x in evs)}</div></div>')
    return "".join(out)


def render_strip(year, month, events, today):
    counts = {}
    for ev in events:
        if ev["status"] != "removed":
            counts[ev["date"]] = counts.get(ev["date"], 0) + 1
    cells = [f'<div class="dow">{n}</div>' for n in ("Su", "Mo", "Tu", "We", "Th", "Fr", "Sa")]
    for week in calendar.Calendar(firstweekday=6).monthdatescalendar(year, month):
        for d in week:
            if d.month != month:
                cells.append('<div class="cell blank"></div>')
                continue
            iso = d.isoformat()
            cls = ["cell"]
            if d == today:
                cls.append("today")
            if d < today:
                cls.append("past")
            n = counts.get(iso)
            if n:
                cls.append("has")
                cells.append(f'<a class="{" ".join(cls)}" href="#d{iso}" data-n="{n if n > 1 else ""}" '
                             f'aria-label="{d:%B %-d}: {n} event{"s" if n > 1 else ""}">{d.day}</a>')
            else:
                cells.append(f'<div class="{" ".join(cls)}">{d.day}</div>')
    return f'<div class="strip" aria-label="{calendar.month_name[month]} {year}">{"".join(cells)}</div>'


def render_page(store, posts, today, now):
    events = list(store["events"].values())
    months = sorted({ev["date"][:7] for ev in events})
    month_html = []
    for ym in months:
        y, m = map(int, ym.split("-"))
        mev = [ev for ev in events if ev["date"].startswith(ym)]
        upcoming = [ev for ev in mev if ev["date"] >= today.isoformat()]
        past = [ev for ev in mev if ev["date"] < today.isoformat()]
        if not upcoming and (y, m) < (today.year, today.month):
            body = f'<details class="past"><summary>Show {len(past)} events</summary><div class="agenda">{render_days(past, today)}</div></details>'
        else:
            body = ""
            if past:
                body += (f'<details class="past"><summary>Earlier this month · {len(past)} events</summary>'
                         f'<div class="agenda">{render_days(past, today)}</div></details>')
            body += f'<div class="agenda">{render_days(upcoming, today)}</div>'
        month_html.append(f'<section class="month" id="m{ym}"><h2>{calendar.month_name[m]} {y}</h2>'
                          f'{render_strip(y, m, mev, today)}{body}</section>')
    month_html.sort(reverse=False)
    # newest month first only once it has started
    current = [s for s, ym in zip(month_html, months) if ym >= today.strftime("%Y-%m")]
    older = [s for s, ym in zip(month_html, months) if ym < today.strftime("%Y-%m")]
    sections = "".join(current) + "".join(reversed(older))

    # source posts and their comments, newest first
    src_html = []
    cal_posts = sorted((p for p in posts.values()), key=lambda p: p["published"], reverse=True)
    for p in cal_posts[:2]:
        pub = dt.datetime.fromisoformat(p["published"].replace("Z", "+00:00")).astimezone(TZ)
        cm = []
        for c in p["comments"]:
            when = c.get("published", "")[:10]
            hot = " hot" if any(w in c["text"].lower() for w in ("cancel", "postpon", "resched", "moved", "correction", "update")) else ""
            cm.append(f'<div class="comment{hot}"><span class="who">{e(c["author"])}</span> '
                      f'<span class="when">{e(when)}</span><div>{e(c["text"])}</div></div>')
        cm_html = "".join(cm) or '<p class="addr">No comments yet.</p>'
        img = (f'<a href="{e(p["image"])}" target="_blank" rel="noopener"><img src="{e(p["image"])}" '
               f'alt="Calendar graphic from the LinkedIn post" loading="lazy"></a>' if p.get("image") else "")
        src_html.append(
            f'<section class="src notes"><h2>From the LinkedIn post</h2>'
            f'<p class="addr"><a href="{e(p["url"])}" target="_blank" rel="noopener">{e(p["headline"])}</a> '
            f'· Danyal Mahmud, {pub:%b %-d, %Y}. Corrections are often posted as comments, shown below.</p>'
            f'{cm_html}{img}</section>')

    updated = dt.datetime.fromisoformat(store["updated"]).astimezone(TZ)
    webcal = "webcal://" + SITE_URL.split("://", 1)[1] + ICS_NAME
    gcal = "https://calendar.google.com/calendar/render?cid=" + html.escape(webcal)
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Improving Houston Meetups</title>
<meta name="description" content="Tech and community meetups hosted at the Improving office in Houston, updated daily.">
<link rel="alternate" type="text/calendar" title="Meetups at Improving Houston" href="{ICS_NAME}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@700;800&family=JetBrains+Mono:wght@500;600;700&family=Source+Sans+3:wght@400;600;700&display=swap">
<style>{CSS}</style>
</head><body><div class="wrap">
<header>
  <span class="eyebrow">Unofficial community calendar</span>
  <h1>Meetups at Improving Houston</h1>
  <p class="addr">10111 Richmond Ave, Suite 100 · Houston, TX 77042</p>
  <div class="actions">
    <a class="btn primary" href="{e(webcal)}">Subscribe in your calendar app</a>
    <a class="btn" href="{gcal}" target="_blank" rel="noopener">Add to Google Calendar</a>
    <a class="btn" href="{ICS_NAME}">Download .ics</a>
  </div>
</header>
{sections}
{"".join(src_html)}
<footer>
  <div>Updated {updated:%a %b %-d, %Y at %-I:%M %p} Central. Built daily from Danyal Mahmud's monthly LinkedIn post, with times and cancellations checked against each group's own event page.</div>
  <div>Not affiliated with Improving. Always confirm on the group's page before you go. <a href="events.json">Raw data (JSON)</a></div>
</footer>
</div></body></html>
"""


def main():
    store, posts = load()
    now = dt.datetime.now(TZ)
    DOCS.mkdir(exist_ok=True)
    events = list(store["events"].values())
    (DOCS / "index.html").write_text(render_page(store, posts, now.date(), now))
    (DOCS / ICS_NAME).write_text(build_ics(events, dt.datetime.fromisoformat(store["updated"])), newline="")
    public = [{k: ev.get(k) for k in ("id", "date", "time", "title", "emoji", "status", "link",
                                       "source_url", "source", "flags")} for ev in events]
    (DOCS / "events.json").write_text(json.dumps({"updated": store["updated"], "events": public},
                                                 indent=1, ensure_ascii=False) + "\n")
    (DOCS / ".nojekyll").touch()


if __name__ == "__main__":
    main()

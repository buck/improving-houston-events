# Meetups at Improving Houston

An unofficial, daily-updated calendar of the community meetups hosted at the Improving office
(10111 Richmond Ave, Suite 100, Houston). It is published at
https://buck.github.io/improving-houston-events/ and has an iCalendar feed at
https://buck.github.io/improving-houston-events/improving-houston.ics.

## Where the data comes from

Danyal Mahmud posts a monthly list of the month's meetups on LinkedIn. Everything below is
fetched without logging in to LinkedIn:

1. `scrape.py` reads Danyal's public profile page to find new posts. It also reads any URLs
   listed in `posts.txt`.
2. Each post's text, comments, and image come from the post's schema.org JSON-LD. A post counts
   as a calendar post when at least 3 lines look like `🐍 Tuesday 10/20 at 6pm - PyHou: <link>`.
3. For upcoming events, each link is followed (`lnkd.in` short links are resolved) to the
   group's event page on Meetup, Eventbrite, Luma, etc. That page's schema.org `Event` supplies
   the exact start and end times, the title of that night's talk, and whether the event is
   cancelled or postponed. LinkedIn Events pages need a login, so they're skipped.
4. The results are merged into `data/events.json`, and each event keeps a history of its
   changes. An event that disappears from an edited post is marked "dropped from list".
5. `build.py` renders `docs/` (the HTML page, the `.ics` feed, and a public `events.json`).
   GitHub Pages serves that folder.

Corrections posted as comments aren't applied automatically. They're shown on the page, and any
new comment that mentions a cancellation, a move, or a date sends an alert so someone can
review it.

## Running

Requires only the system `python3` (standard library), `curl`, `jq`, and `git`.

```
./run.sh        # scrape, build, commit and push if anything changed, alert on problems
```

Cron on quad runs it daily. The push uses a deploy key for this repo only
(`~/.ssh/id_ed25519_improving_deploy`) because cron has no SSH agent.

If a new monthly post isn't picked up, add its URL to `posts.txt`.

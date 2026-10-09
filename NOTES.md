# Project notes

Status as of 2026-10-08, when the site first went live.

- Site: https://buck.github.io/improving-houston-events/
- Calendar feed: https://buck.github.io/improving-houston-events/improving-houston.ics
  (subscribe from Google Calendar, Apple Calendar, Outlook, etc.)

The first run loaded all 17 October events from Danyal's post. It also caught something the post
doesn't say: Eventbrite lists **Product Houston on Sat 10/10 as cancelled**. The site shows that
event crossed out with a "Cancelled" tag.

## How it works

Everything is free and nothing logs in to LinkedIn.

- **Finding new posts:** Danyal's public LinkedIn profile page lists his recent posts without a
  login, so new monthly posts are found without Apify or a search engine. Any post where at
  least 3 lines look like event listings counts as a calendar post.
- **The event list:** taken from the post text, which repeats everything in the calendar image.
  The image is shown on the site for reference, so it doesn't need OCR.
- **Exact times and cancellations:** each event's link is followed to the group's own Meetup,
  Eventbrite or Luma page. That page also corrects the post. For example, the Houston Java User
  Group on 10/15 starts at 6:30pm, not the 6pm the post says.
- **Edits to the post:** if Danyal edits the post, events update in place and their earlier
  versions are kept in `data/events.json`. An event that disappears from the post is marked
  "Dropped from list".
- **Daily run:** a cron job on quad runs `run.sh` at 7:15am. It commits and pushes only if
  something changed. If the scrape fails, or a new comment mentions cancelling, moving or a
  date, it sends a notification through `/usr/local/bin/alert`.

## Things to know

- **Comments are not applied automatically.** Corrections posted as comments are shown on the
  site and trigger an alert, and a person makes the change. Applying them automatically would
  need an LLM, which costs a little. That could be added later.
- **Five October events can't be checked against a group page:** Side Project Society, Design
  Thinking and Innovation, Goals Alliance, HOUBA and Cloud Native Houston link to LinkedIn pages
  that need a login. For those, the site shows the time from the post.
- **New-post discovery isn't proven yet.** The real test comes around Nov 1, when the November
  post should appear. If it's missed, add its URL to `posts.txt`.
- **Apify is an alternative for discovery.** It costs roughly $1 a month, and the account's
  usage limit resets on 2026-11-04. It's only worth adding if the profile-page check stops
  working.
- **The repo is public**, which free GitHub Pages requires. It includes the names and text of
  LinkedIn commenters, which are already public on LinkedIn.
- **Cron pushes with a deploy key:** `~/.ssh/id_ed25519_improving_deploy` has no passphrase and
  can push to this repo only. The normal SSH key needs an SSH agent, which cron doesn't have.

## Files

- `scrape.py` finds posts, parses the events, checks the group pages, and updates
  `data/events.json`.
- `build.py` writes the site into `docs/`: `index.html`, the `.ics` feed, and a public
  `events.json`.
- `run.sh` is the cron wrapper: scrape, build, commit, push, alert.
- `posts.txt` lists extra post URLs to scrape when one isn't found automatically.

# Job hitlist

Monitors LinkedIn (guest search, no login) and Jobright (your feed, read via
your own Chrome) for Director / Senior Director / Senior Manager design roles,
scores them against `config.yaml`, and renders `hitlist.html`.

    ./daily.sh            # refresh: collect -> import Jobright -> score -> render -> open
    ./daily.sh r86400     # only the past 24 hours

Files
- `config.yaml`      searches, title tiers, locations, weights. Edit this, not the code.
- `data/jobs.json`   everything ever seen, with first_seen / last_seen. Never hand-edit.
- `data/jobright.json`  hand-captured rows from your Jobright feed (Claude reads the page).
- `data/enrich.json` recruiters found per job, keyed by job id.
- `data/Connections.csv`  your LinkedIn export. Drop it here and re-run render.
- `hitlist.html`     the output.

What needs Claude in the loop
- Reading your Jobright feed (it is your logged-in account).
- Recruiter lookups on LinkedIn people search (same reason). Low volume only.
Everything else runs unattended.

Scoring, in one line: tier (100/80/75/40) + location (+20 target city, +15
says remote, +6 LinkedIn-filter remote, -100 elsewhere) + recency (+25 today
down to -25 past two weeks) + AI signal (+15) + small keyword bonuses.
Rows under 80 stay in data but are not rendered.

## Served copy (25 Sep 2026)

    http://localhost:8766/

`serve.py` runs permanently (LaunchAgent `com.perfectpixels.jobhitlist-server`,
127.0.0.1 only). It adds what a file:// page cannot do:

- **Refresh** button: LinkedIn past 24h + alert mail + boards, ~5 min.
  **Full**: past week, ~20 min. Progress shows in the toolbar; the page
  reloads itself when the run finishes. Only one run at a time (the 7am job
  and a click cannot overlap; `data/.running` is the lock).
- Applied / Follow up / Not a fit marks are written to `data/decisions.json`
  on every click, and merged back on load. Use this URL, not the file path.

# Job hitlist

A personal job-search monitor you run on your own machine. Every morning it
collects new postings from LinkedIn (public search, no login), optionally
from job-alert emails (Jobright, Ladders, CareerBuilder via Apple Mail), and
from the career boards of companies you name (Greenhouse, Lever, Ashby, plus
Intuit, Google and Microsoft). It merges the same posting seen on several
sites into one row, scores each one against your titles, locations and
recency, and renders a single page where you mark each role Applied,
Follow up or Not a fit.

It also builds a browser userscript that fills your work history into
Workday, Greenhouse and Lever application forms from a file you control, so
no applicant-tracking system ever has to parse your resume.

Nothing leaves your computer. There is no account, no server, no telemetry.

## Requirements

- macOS (the scheduler and Apple Mail steps are macOS-only; the rest runs
  anywhere with Python 3.12+)
- Python 3.12 or newer (`brew install python`)
- Chrome with the Tampermonkey extension, for the autofill
- Optional: Claude Code, which makes setup a conversation instead of a form

## Setup with Claude Code (recommended, about 10 minutes)

1. Clone this repo and open the folder in Claude Code.
2. Type `/hitlist-setup`.
3. Answer the questions: the job titles you want, the words that mark a
   posting as your field, your target cities, whether remote counts.
4. When asked, give it your resume (.docx or .pdf). It copies your work
   history into `resume.yaml` word for word and shows you a table to confirm.
5. It builds the autofill script and puts it on your clipboard, runs the
   first collection, and opens your list.

## Setup without Claude Code

```bash
./run setup.py                                 # answers the same questions
cp autofill/resume.template.yaml resume.yaml   # then fill it in by hand
./run autofill/build_userscript.py             # builds workday-autofill.user.js
./daily.sh                                     # first collection, opens the list
```

## Installing the autofill in Chrome

1. Install Tampermonkey from the Chrome Web Store.
2. In Chrome, open `chrome://extensions`, click **Details** on Tampermonkey,
   and turn on **Allow User Scripts**. Without this the script installs,
   shows green, and silently never runs.
3. Click the Tampermonkey icon, **Create a new script**, replace the
   contents with your `workday-autofill.user.js`, and save.
4. On any Workday, Greenhouse or Lever application page a **Fill** button
   appears bottom-left. On Workday it fills every work-history entry and your
   LinkedIn URL; on Greenhouse and Lever it fills contact fields. It never
   touches dropdowns, uploads, EEO or consent questions, or Submit. Those are
   yours.

## Day to day

- Your list: `http://localhost:8766/` if you installed the server, otherwise
  open `hitlist.html`. The **Refresh** button re-collects; the 7am job does
  it for you.
- `config.yaml` is where you tune titles, cities and weights.
- `watchlist.yaml` is where you add companies to poll directly. For a
  Greenhouse, Lever or Ashby board the slug is the path on their careers
  page (`boards.greenhouse.io/<slug>`).
- Edit `resume.yaml` when your resume changes, then re-run
  `./run autofill/build_userscript.py` and re-paste into Tampermonkey.

## Privacy

`resume.yaml`, everything under `data/`, and the generated `hitlist.html` and
userscript are gitignored. Keep `resume.yaml` out of shared folders; it holds
your address and employment history. LinkedIn collection uses the public
guest endpoint and never asks for your login.

## Files

| File | What it does |
|---|---|
| `collect.py` | LinkedIn guest search and detail fetch |
| `mail_alerts.py`, `alerts_import.py` | Job-alert email harvest (Apple Mail) |
| `boards.py`, `careers.py` | Company boards and career sites from `watchlist.yaml` |
| `verify_alerts.py` | Double-checks alert-only postings against LinkedIn |
| `score.py` | Scoring, cross-source dedup, per-track tiers |
| `render.py` | Builds `hitlist.html` |
| `serve.py` | Local server: Refresh button, saved decisions |
| `daily.sh` | The whole pipeline in order |
| `setup.py` | Personalizes everything above |
| `autofill/` | Resume template and the userscript builder |

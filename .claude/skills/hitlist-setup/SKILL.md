---
name: hitlist-setup
description: Personalize the job hitlist and the application autofill for a new user. Use when someone opens this repo for the first time, or says "set this up for me" / "personalize this for my job search". Asks for their search criteria and their resume, writes config.yaml and resume.yaml, builds the Tampermonkey userscript, and runs the first collection.
---

# Hitlist setup

You are helping a new user turn this repo into their own job monitor. Two
things come from them: search criteria and a resume. Everything else is
derived. Do not invent facts about them; ask.

## 1. Criteria (use AskUserQuestion, one call, four questions)
- Target titles (strong fit), as they would appear in a posting.
- Weaker-fit titles to include at reduced weight (optional).
- Words that mark a posting as their field (e.g. "product design, ux"), and
  words that mean it is NOT their field even if it matches (e.g. for a
  designer: "engineer, architect"; default "intern, internship").
- Target cities/regions, and whether remote US roles count.
Then ask, in a second call: read job-alert mail from Apple Mail (only if they
use Mail.app and get Jobright/Ladders/CareerBuilder alerts), and install the
7am scheduler + local server (macOS only).

Write the answers to `data/setup-answers.json` with keys
`name, titles, also_titles, field_words, exclude_words, cities, remote, alerts, schedule`
(lists as JSON arrays, booleans as true/false), then run
`./run setup.py --answers data/setup-answers.json --no-run`.

## 2. Resume -> resume.yaml (this is the part that needs you)
Ask for their resume file (.docx or .pdf). Extract the text yourself (docx:
`<w:t>` runs from word/document.xml; pdf: pypdf). Then write `resume.yaml`
following `autofill/resume.template.yaml` exactly:
- `work` in reverse-chronological order; company, title, dates, location,
  employment type copied verbatim (these are LOCKED fields that employment
  verification checks). Dates as YYYY-MM.
- `description.medium` is the role paragraph as written; `bullets` are the
  bullets as written. Do not reword, summarize or "improve" anything.
- `contact` and `education` from the resume; anything missing stays TODO and
  you tell them which fields.
Show them the work entries (company / title / dates) as a table and ask them
to confirm before continuing. Never write anything into resume.yaml that is
not in their document or their answer.

## 3. Build and hand over
- `./run autofill/build_userscript.py` then `pbcopy < workday-autofill.user.js`.
- Tell them: install Tampermonkey, create a new script, paste, save, and turn
  ON "Allow User Scripts" in chrome://extensions > Tampermonkey > Details
  (without it the script installs but never runs). The Fill button appears
  bottom-left on Workday, Greenhouse and Lever application pages; it fills
  work history and contact fields only and never touches dropdowns,
  uploads, EEO questions or Submit.
- Run `./daily.sh r604800` for the first collection (several minutes), then
  open http://localhost:8766/ if the server was installed, else hitlist.html.
- Point out the two files they will edit from now on: `config.yaml`
  (titles, cities, weights) and `watchlist.yaml` (companies to poll directly).

## Boundaries
resume.yaml is private and gitignored; never commit it, never paste its
contents into chat beyond the confirmation table. Do not create accounts,
fill consent/EEO fields, or press Submit on any site. LinkedIn collection
uses the public guest endpoint only; never ask for their LinkedIn password.

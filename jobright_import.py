#!/usr/bin/env python3
"""Fold data/jobright.json (hand-captured from the Jobright feed) into
data/jobs.json so the scorer treats both sources alike.

Jobright rows get ids like jr-<company>-<title-slug>. Their summary stands
in for the description, and posted_ago ("3 days ago") becomes a date.
"""
import json, pathlib, re
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).parent
STORE = HERE / "data/jobs.json"
jobs = json.loads(STORE.read_text()) if STORE.exists() else {}
src = json.loads((HERE / "data/jobright.json").read_text())

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]
def ago_to_date(s):
    m = re.search(r"(\d+)\s*(hour|day|week|month)", s or "")
    if not m: return None
    n, u = int(m.group(1)), m.group(2)
    days = {"hour": n / 24, "day": n, "week": 7 * n, "month": 30 * n}[u]
    return (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()

now = datetime.now(timezone.utc).isoformat(timespec="seconds")
n = 0
for r in src:
    jid = f"jr-{r['jr_id']}" if r.get("jr_id") else f"jr-{slug(r['company'])}-{slug(r['title'])}"
    j = jobs.setdefault(jid, {"first_seen": now, "sources": []})
    j.update({
        "id": jid, "title": r["title"], "company": r["company"],
        "location": f"{r['location']} ({r['workplace']})" if r.get("workplace") else r["location"],
        "posted": r.get("posted") or ago_to_date(r.get("posted_ago")), "applicants": r.get("applicants"),
        "description": r.get("summary", ""), "seniority_level": r.get("level"),
        "comp": r.get("comp"), "jobright_match": r.get("match"), "jobright_network": r.get("network"),
        "url": r.get("url") or "https://jobright.ai/jobs/recommend", "last_seen": now, "detail_fetched": now,
    })
    if "jobright" not in j["sources"]: j["sources"].append("jobright")
    n += 1
STORE.write_text(json.dumps(jobs, indent=1))
print(f"imported {n} Jobright rows; store now {len(jobs)}")

#!/usr/bin/env python3
"""Fold data/alerts.json (and the legacy hand-captured data/jobright.json)
into data/jobs.json so the scorer treats every source alike."""
import json, pathlib, re
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).parent
STORE = HERE / "data/jobs.json"
jobs = json.loads(STORE.read_text()) if STORE.exists() else {}

def slug(s): return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:40]
def ago_to_date(s):
    m = re.search(r"(\d+)\s*(hour|day|week|month)", s or "")
    if not m: return None
    n, u = int(m.group(1)), m.group(2)
    days = {"hour": n / 24, "day": n, "week": 7 * n, "month": 30 * n}[u]
    return (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()

rows = []
for f in ("data/alerts.json", "data/jobright.json"):
    p = HERE / f
    if p.exists():
        for r in json.loads(p.read_text()):
            r.setdefault("source", "jobright"); rows.append(r)

now = datetime.now(timezone.utc).isoformat(timespec="seconds")
n = 0
for r in rows:
    src = r["source"]
    jid = f"jr-{r['jr_id']}" if r.get("jr_id") else f"{src[:2]}-{slug(r['company']) or 'loc-' + slug(r.get('location',''))}-{slug(r['title'])}"
    j = jobs.setdefault(jid, {"first_seen": now, "sources": []})
    j.update({
        "id": jid, "title": r["title"], "company": r["company"],
        "location": f"{r['location']} ({r['workplace']})" if r.get("workplace") else r.get("location", ""),
        "posted": r.get("posted") or ago_to_date(r.get("posted_ago")), "applicants": r.get("applicants"),
        "description": r.get("summary", "") or "", "seniority_level": r.get("level"),
        "comp": r.get("comp"), "jobright_match": r.get("match"), "jobright_network": r.get("network"),
        "needs_company": bool(r.get("needs_company")),
        "url": r.get("url") or "https://jobright.ai/jobs/recommend", "last_seen": now, "detail_fetched": now,
    })
    if src not in j["sources"]: j["sources"].append(src)
    n += 1
STORE.write_text(json.dumps(jobs, indent=1))
print(f"imported {n} alert rows; store now {len(jobs)}")

#!/usr/bin/env python3
"""Poll the ATS job boards in watchlist.yaml (Greenhouse, Lever, Ashby) and
fold matching postings into data/jobs.json.

    ./run boards.py

Each board's public JSON API is read once; only titles that clear a tier on
some track are kept. Rows carry the ATS's own posted date and the full job
description, so no LinkedIn detail fetch is needed and the scorer sees them
exactly like a LinkedIn row. Ids: gh-<slug>-<id>, lv-<slug>-<id>, ab-<slug>-<id>.
"""
import json, pathlib, re, sys, time
from datetime import datetime, timezone
import requests, yaml
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import collect as C

HERE = pathlib.Path(__file__).parent
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"}

def strip_html(h): return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h or "")).strip()
def day(iso):
    try: return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).date().isoformat()
    except Exception: return None

def greenhouse(slug):
    r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"}, headers=UA, timeout=20)
    r.raise_for_status()
    for j in r.json().get("jobs", []):
        yield {"id": f"gh-{slug}-{j['id']}", "title": j.get("title", ""), "location": (j.get("location") or {}).get("name", ""),
               "posted": day(j.get("first_published") or j.get("updated_at")), "url": j.get("absolute_url"),
               "description": strip_html(j.get("content", ""))}

def lever(slug):
    r = requests.get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}, headers=UA, timeout=20)
    r.raise_for_status()
    for j in r.json():
        cat = j.get("categories") or {}
        loc = ", ".join(x for x in [cat.get("location"), cat.get("allLocations") and None] if x) or cat.get("location", "")
        if (j.get("workplaceType") or "").lower() == "remote": loc = f"{loc} (Remote)".strip()
        yield {"id": f"lv-{slug}-{j['id']}", "title": j.get("text", ""), "location": loc,
               "posted": datetime.fromtimestamp((j.get("createdAt") or 0) / 1000, tz=timezone.utc).date().isoformat() if j.get("createdAt") else None,
               "url": j.get("hostedUrl"), "description": j.get("descriptionPlain") or strip_html(j.get("description", ""))}

def ashby(slug):
    r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", headers=UA, timeout=20)
    r.raise_for_status()
    for j in r.json().get("jobs", []):
        loc = j.get("location") or ""
        if j.get("isRemote"): loc = f"{loc} (Remote)".strip()
        yield {"id": f"ab-{slug}-{j['id']}", "title": j.get("title", ""), "location": loc,
               "posted": day(j.get("publishedAt") or j.get("publishedDate")), "url": j.get("jobUrl"),
               "description": j.get("descriptionPlain") or strip_html(j.get("descriptionHtml", ""))}

FETCH = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}

def main():
    wl = yaml.safe_load((HERE / "watchlist.yaml").read_text()).get("boards", [])
    jobs = json.loads(C.STORE.read_text()) if C.STORE.exists() else {}
    now = C.now(); total_new = 0
    for b in wl:
        try:
            rows = list(FETCH[b["ats"]](b["slug"]))
        except Exception as e:
            print(f"  {b['company'][:24]:<24} {b['ats']:<10} ERROR {type(e).__name__}: {str(e)[:60]}"); continue
        kept = new = 0
        for r in rows:
            if not C.title_clears_tier(r["title"]): continue
            kept += 1
            j = jobs.setdefault(r["id"], {"first_seen": now, "sources": []})
            if r["id"] not in jobs or not j.get("last_seen"): pass
            was_new = "last_seen" not in j
            j.update({k: v for k, v in r.items() if v})
            j.update({"company": b["company"], "last_seen": now, "detail_fetched": now})
            if b["ats"] not in j["sources"]: j["sources"].append(b["ats"])
            if was_new: new += 1
        total_new += new
        print(f"  {b['company'][:24]:<24} {b['ats']:<10} {len(rows):>4} jobs  {kept:>2} design-leadership  {new:>2} new")
        time.sleep(0.4)
    C.STORE.write_text(json.dumps(jobs, indent=1))
    print(f"{len(wl)} boards, {total_new} new postings; store now {len(jobs)}")

if __name__ == "__main__":
    main()

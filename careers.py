#!/usr/bin/env python3
"""Poll company career sites that have no standard ATS feed (watchlist.yaml
`sites:`) and fold tier-clearing postings into data/jobs.json.

    ./run careers.py

Adapters return {id, title, location, url, posted?, description?}; ids are
prefixed per site (it-, go-, ms-) so re-runs update rather than duplicate.
"""
import json, pathlib, re, sys, time
from datetime import datetime, timezone
import requests, yaml
from bs4 import BeautifulSoup
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import collect as C

HERE = pathlib.Path(__file__).parent
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
                  "Accept-Language": "en-US,en;q=0.9"})
def nap(s=1.5): time.sleep(s)
def clean(s): return re.sub(r"\s+", " ", s or "").strip()

# ---------------------------------------------------------------- Intuit
def intuit(site):
    seen = set()
    for q in site["queries"]:
        for p in range(1, site.get("max_pages", 3) + 1):
            r = S.get(f"https://jobs.intuit.com/search-jobs/{requests.utils.quote(q)}/27595/1", params={"p": p}, timeout=30)
            if r.status_code != 200: break
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select("a[data-job-id][href^='/job/']")
            if not cards: break
            for a in cards:
                jid = a["data-job-id"]
                if jid in seen: continue
                seen.add(jid)
                lines = [clean(t) for t in a.get_text("\n").splitlines() if clean(t)]
                title = a.get("data-title") or (lines[0] if lines else "")
                loc = next((l for l in lines[1:] if l not in ("Save",)), "")
                yield {"id": f"it-{jid}", "title": title, "location": loc, "url": "https://jobs.intuit.com" + a["href"]}
            nap()

def intuit_detail(url):
    """Posted date and description live in the job page's JSON-LD."""
    r = S.get(url, timeout=30)
    if r.status_code != 200: return {}
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', r.text, re.S):
        try: j = json.loads(m.group(1))
        except Exception: continue
        if j.get("@type") == "JobPosting":
            d = j.get("datePosted", "")
            m2 = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", d)
            return {"posted": f"{m2.group(1)}-{int(m2.group(2)):02d}-{int(m2.group(3)):02d}" if m2 else None,
                    "description": clean(re.sub(r"<[^>]+>", " ", j.get("description", "")))}
    return {}

# ---------------------------------------------------------------- Google
def google(site):
    seen = set()
    for q in site["queries"]:
        for p in range(1, site.get("max_pages", 3) + 1):
            r = S.get("https://www.google.com/about/careers/applications/jobs/results",
                      params={"q": q, "location": site.get("location", "United States"), "page": p}, timeout=30)
            if r.status_code != 200: break
            soup = BeautifulSoup(r.text, "html.parser")
            links = soup.select("a[href*='jobs/results/']")
            new = 0
            for a in links:
                m = re.search(r"jobs/results/(\d+)-", a["href"])
                if not m or m.group(1) in seen: continue
                seen.add(m.group(1)); new += 1
                li = a.find_parent("li") or a.parent
                lines = [clean(t) for t in li.get_text("\n").splitlines() if clean(t)]
                title = lines[0] if lines else ""
                # lines look like: title, corporate_fare, Google, place, "Mountain View, CA, USA", bar_chart, Mid
                loc = ""
                if "place" in lines:
                    i = lines.index("place"); loc = " ".join(l for l in lines[i+1:i+3] if not l.startswith(("bar_chart",))).replace(" ;", ";")
                sub = lines[lines.index("corporate_fare")+1] if "corporate_fare" in lines and lines.index("corporate_fare")+1 < len(lines) else "Google"
                yield {"id": f"go-{m.group(1)}", "title": title, "location": loc,
                       "url": "https://www.google.com/about/careers/applications/jobs/results/" + a["href"].split("jobs/results/")[1].split("?")[0],
                       "company_sub": sub}
            if new == 0: break
            nap()

# ---------------------------------------------------------------- Microsoft (Eightfold)
def microsoft(site):
    """Eightfold answers 429 to a bare API call; loading the careers page first
    sets the cookies it wants, after which the JSON API is open."""
    seen = set()
    hdr = {"Accept": "application/json, text/plain, */*", "Referer": "https://apply.careers.microsoft.com/careers", "Origin": "https://apply.careers.microsoft.com"}
    S.get("https://apply.careers.microsoft.com/careers?query=design", timeout=30); nap(2)
    for q in site["queries"]:
        for start in (0, 10, 20):
            r = S.get("https://apply.careers.microsoft.com/api/pcsx/search", headers=hdr, timeout=30,
                      params={"domain": "microsoft.com", "query": q, "location": site.get("location", "United States"),
                              "start": start, "num": 10, "sort_by": "timestamp", "hl": "en"})
            if r.status_code == 429: print("  microsoft: rate limited, backing off 60s"); time.sleep(60); r = S.get(r.url, headers=hdr, timeout=30)
            if r.status_code != 200: print(f"  microsoft: HTTP {r.status_code}"); break
            body = r.json(); ps = (body.get("data") or {}).get("positions") or body.get("positions") or []
            if not ps: break
            for p in ps:
                pid = str(p.get("id"))
                if pid in seen: continue
                seen.add(pid)
                loc = p.get("location") or "; ".join(p.get("locations") or [])
                if (p.get("workLocationOption") or "").lower() == "remote": loc = f"{loc} (Remote)".strip()
                ts = p.get("postedTs") or p.get("creationTs") or p.get("t_create")
                if ts and ts > 1e12: ts = ts / 1000                      # ms vs s
                yield {"id": f"ms-{pid}", "title": p.get("name", ""), "location": loc,
                       "url": ("https://apply.careers.microsoft.com" + p["positionUrl"]) if (p.get("positionUrl") or "").startswith("/") else (p.get("positionUrl") or p.get("canonicalPositionUrl") or f"https://apply.careers.microsoft.com/careers?pid={pid}"),
                       "posted": datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat() if ts else None,
                       "description": clean(re.sub(r"<[^>]+>", " ", p.get("job_description", "") or ""))[:6000]}
            nap(2.5)

ADAPTERS = {"intuit": intuit, "google": google, "microsoft": microsoft}

def main():
    sites = (yaml.safe_load((HERE / "watchlist.yaml").read_text()) or {}).get("sites", [])
    jobs = json.loads(C.STORE.read_text()) if C.STORE.exists() else {}
    now = C.now(); today = datetime.now(timezone.utc).date().isoformat()
    for site in sites:
        kind = site["kind"]; total = kept = new = 0
        try:
            for r in ADAPTERS[kind](site):
                total += 1
                if not C.title_clears_tier(r["title"]): continue
                kept += 1
                j = jobs.setdefault(r["id"], {"first_seen": now, "sources": []})
                was_new = "last_seen" not in j
                if was_new:
                    new += 1
                    if kind == "intuit":
                        r.update({k: v for k, v in intuit_detail(r["url"]).items() if v}); nap()
                j.update({k: v for k, v in r.items() if v})
                j.setdefault("posted", today)               # Google shows no dates: first sighting stands in
                j.update({"company": site["company"], "last_seen": now, "detail_fetched": now})
                if kind not in j["sources"]: j["sources"].append(kind)
        except Exception as e:
            print(f"  {site['company']:<10} ERROR {type(e).__name__}: {str(e)[:80]}")
        print(f"  {site['company']:<10} {total:>4} seen  {kept:>3} design-leadership  {new:>3} new")
    C.STORE.write_text(json.dumps(jobs, indent=1))
    print(f"store now {len(jobs)}")

if __name__ == "__main__":
    main()

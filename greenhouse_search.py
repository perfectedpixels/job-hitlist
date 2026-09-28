#!/usr/bin/env python3
"""Import a capture from Greenhouse's cross-company search (my.greenhouse.io).

    ./run greenhouse_search.py                  # reads data/mygreenhouse_capture.txt

my.greenhouse.io is login-gated and its API URLs are obfuscated per session,
so the search page itself is read by Claude in Jason's Chrome and the card
links ("<slug>/<job id>") pasted into data/mygreenhouse_capture.txt. Every
link maps onto Greenhouse's PUBLIC board API, so this script:
  1. fetches each job (title, location, description, dates) with no login,
  2. imports the ones that clear a tier into data/jobs.json under the same
     gh-<slug>-<id> ids boards.py uses, so the two never duplicate,
  3. adds every slug seen to watchlist.yaml, so from then on that company's
     board is polled daily and the search capture is only needed for
     discovering NEW companies.
"""
import json, pathlib, re, sys, time
from datetime import datetime
import requests, yaml
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import collect as C

HERE = pathlib.Path(__file__).parent
CAP = HERE / "data/mygreenhouse_capture.txt"
WL = HERE / "watchlist.yaml"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"}

def strip_html(h): return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h or "")).strip()
def day(iso):
    try: return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).date().isoformat()
    except Exception: return None

def main():
    pairs = re.findall(r"([a-z0-9_-]+)/(\d+)", "\n".join(l for l in CAP.read_text().splitlines() if not l.startswith("#")))
    print(f"{len(pairs)} captured links")
    jobs = json.loads(C.STORE.read_text())
    wl = yaml.safe_load(WL.read_text()) or {"boards": []}
    known = {b["slug"] for b in wl["boards"]}
    names, now, kept, new_cos = {}, C.now(), 0, []
    for slug, jid in pairs:
        if slug not in names:
            try:
                r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}", headers=UA, timeout=15)
                names[slug] = r.json().get("name", slug) if r.status_code == 200 else slug
            except Exception: names[slug] = slug
            if slug not in known:
                wl["boards"].append({"company": names[slug], "ats": "greenhouse", "slug": slug}); known.add(slug); new_cos.append(names[slug])
        try:
            r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{jid}", headers=UA, timeout=15)
            if r.status_code != 200: print(f"  {slug}/{jid}: HTTP {r.status_code}"); continue
            j = r.json()
        except Exception as e:
            print(f"  {slug}/{jid}: {type(e).__name__}"); continue
        title = j.get("title", "")
        if not C.title_clears_tier(title): continue
        kept += 1
        key = f"gh-{slug}-{jid}"
        row = jobs.setdefault(key, {"first_seen": now, "sources": []})
        row.update({"id": key, "title": title, "company": names[slug],
                    "location": (j.get("location") or {}).get("name", ""),
                    "posted": day(j.get("first_published") or j.get("updated_at")),
                    "url": j.get("absolute_url"), "description": strip_html(j.get("content", "")),
                    "last_seen": now, "detail_fetched": now})
        if "greenhouse-search" not in row["sources"]: row["sources"].append("greenhouse-search")
        print(f"  kept {names[slug][:24]:<24} {title[:50]}")
        time.sleep(0.3)
    C.STORE.write_text(json.dumps(jobs, indent=1))
    WL.write_text(re.sub(r"\n(boards:)", r"\n\1", WL.read_text().split("boards:")[0]) + yaml.safe_dump({"boards": wl["boards"]}, sort_keys=False, allow_unicode=True))
    print(f"{kept} design-leadership postings imported; {len(new_cos)} companies added to watchlist: {', '.join(new_cos)}")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Collect job cards from LinkedIn's guest search endpoint, then fetch the
full posting for anything whose title clears a tier. No login, no cookies.

    ./run collect.py                 # uses config.yaml time_window
    ./run collect.py --window r86400 # override: past 24h

Everything lands in data/jobs.json keyed by LinkedIn job id, with first_seen
and last_seen so recency survives across runs. Detail pages are fetched once
and cached; re-runs only pay for new postings.
"""
import argparse, json, pathlib, random, re, sys, time
from datetime import datetime, timezone
import requests, yaml
from bs4 import BeautifulSoup

HERE = pathlib.Path(__file__).parent
DATA = HERE / "data"; DATA.mkdir(exist_ok=True)
STORE = DATA / "jobs.json"
CFG = yaml.safe_load((HERE / "config.yaml").read_text())

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
VIEW = "https://www.linkedin.com/jobs/view/{id}"
S = requests.Session(); S.headers["User-Agent"] = UA
S.headers["Accept-Language"] = "en-US,en;q=0.9"

def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def nap(): time.sleep(CFG["fetch"]["delay_seconds"] + random.random())

def get(url, **params):
    """One slow LinkedIn response must not take the whole run down: a timeout
    or dropped connection is retried with backoff, then skipped."""
    for attempt in range(4):
        try:
            r = S.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            wait = 15 * (attempt + 1); print(f"  network error ({type(e).__name__}), retry in {wait}s"); time.sleep(wait); continue
        if r.status_code == 200: return r.text
        if r.status_code in (429, 503):
            wait = 20 * (attempt + 1); print(f"  {r.status_code}, backing off {wait}s"); time.sleep(wait); continue
        print(f"  HTTP {r.status_code} for {url}"); return ""
    print(f"  giving up on {url[:80]}"); return ""

def clean(s): return re.sub(r"\s+", " ", s or "").strip()

def parse_cards(html):
    soup = BeautifulSoup(html, "html.parser")
    for card in soup.select("div.base-card, li > div.base-search-card"):
        urn = card.get("data-entity-urn", "")
        m = re.search(r"jobPosting:(\d+)", urn)
        a = card.select_one("a.base-card__full-link")
        if not m and a:
            m = re.search(r"-(\d{6,})\?", a.get("href", "")) or re.search(r"/view/(\d+)", a.get("href", ""))
        if not m: continue
        t = card.select_one("time")
        yield {
            "id": m.group(1),
            "title": clean(card.select_one(".base-search-card__title") and card.select_one(".base-search-card__title").text),
            "company": clean(card.select_one(".base-search-card__subtitle") and card.select_one(".base-search-card__subtitle").text),
            "location": clean(card.select_one(".job-search-card__location") and card.select_one(".job-search-card__location").text),
            "posted": (t.get("datetime") if t else None),
        }

def title_clears_tier(title):
    """Worth a detail fetch if the title clears a tier on ANY track."""
    t = title.lower()
    if not re.search(CFG["design_signal"], t): return False
    if re.search(CFG["design_exclude"], t): return False
    for tcfg in CFG["tracks"].values():
        if tcfg.get("exclude") and re.search(tcfg["exclude"], t): continue
        if any(re.search(v["pattern"], t) and v["score"] >= CFG["fetch"]["detail_min_tier_score"]
               for v in tcfg["tiers"].values()):
            return True
    return False

def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    def txt(sel):
        el = soup.select_one(sel); return clean(el.get_text(" ")) if el else None
    crit = {}
    for li in soup.select(".description__job-criteria-item"):
        k = txt_of(li, ".description__job-criteria-subheader"); v = txt_of(li, ".description__job-criteria-text")
        if k: crit[k.lower().replace(" ", "_")] = v
    t = soup.select_one(".posted-time-ago__text, time")
    posted = None
    for el in soup.select("time[datetime]"):
        posted = el.get("datetime"); break
    return {
        "title": txt("h1.top-card-layout__title") ,
        "company": txt("a.topcard__org-name-link") or txt(".topcard__flavor"),
        "location": txt(".topcard__flavor--bullet"),
        "applicants": txt(".num-applicants__caption"),
        "posted_detail": posted,
        "description": txt(".show-more-less-html__markup") or txt(".description__text"),
        **crit,
    }

def txt_of(el, sel):
    x = el.select_one(sel); return clean(x.get_text(" ")) if x else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default=CFG["searches"]["time_window"])
    ap.add_argument("--no-detail", action="store_true")
    ap.add_argument("--detail-only", action="store_true", help="skip searches; fetch details for what is already in the store")
    a = ap.parse_args()

    jobs = json.loads(STORE.read_text()) if STORE.exists() else {}
    seen_before = set(jobs)
    sc = CFG["searches"]
    passes = [(k, loc, {}) for k in sc["keywords"] for loc in sc["locations"]]
    if sc.get("remote_us"):
        passes += [(k, "United States", {"f_WT": "2"}) for k in sc["keywords"]]
    print(f"{len(passes)} searches x {sc['pages_per_search']} pages, window {a.window}")

    new = 0
    if a.detail_only: passes = []
    for kw, loc, extra in passes:
        for page in range(sc["pages_per_search"]):
            html = get(SEARCH, keywords=kw, location=loc, f_TPR=a.window, start=page * 25, **extra)
            n = 0
            for c in parse_cards(html):
                n += 1
                j = jobs.setdefault(c["id"], {"first_seen": now(), "sources": []})
                for k, v in c.items():
                    if v and not j.get(k): j[k] = v
                j["last_seen"] = now()
                src = f"{kw} | {loc}"
                if src not in j["sources"]: j["sources"].append(src)
                j["url"] = VIEW.format(id=c["id"])
                if c["id"] not in seen_before: new += 1; seen_before.add(c["id"])
            print(f"  {kw:<36} {loc:<26} p{page}  {n:>2} cards")
            STORE.write_text(json.dumps(jobs, indent=1))
            if n == 0: break
            nap()
    STORE.write_text(json.dumps(jobs, indent=1))
    print(f"\n{len(jobs)} jobs in store, {new} new this run")

    if a.no_detail: return
    todo = [j for j in jobs.values() if not j.get("detail_fetched") and title_clears_tier(j.get("title", ""))]
    print(f"fetching detail for {len(todo)} tier-clearing postings")
    for i, j in enumerate(todo, 1):
        html = get(VIEW.format(id=j["id"]))
        if html:
            d = parse_detail(html)
            for k, v in d.items():
                if v: j[k] = v
            j["detail_fetched"] = now()
            print(f"  [{i}/{len(todo)}] {j.get('company','?')[:28]:<28} {j.get('title','?')[:50]}")
        else:
            j["detail_error"] = now()
        if i % 10 == 0: STORE.write_text(json.dumps(jobs, indent=1))
        nap()
    STORE.write_text(json.dumps(jobs, indent=1))
    print("done")

if __name__ == "__main__":
    main()

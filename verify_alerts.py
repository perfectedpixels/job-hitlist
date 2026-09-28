#!/usr/bin/env python3
"""Double-check alert-only postings (Ladders, CareerBuilder) against LinkedIn.

    ./run verify_alerts.py            # checks unverified alert rows from the last 14 days
    ./run verify_alerts.py --max 40

Why: Ladders and CareerBuilder scrape other boards, carry no job id, and date
rows by the email rather than the posting. For every alert-sourced job that
clears a tier and has not yet been matched to a LinkedIn posting, this runs
one LinkedIn guest search for the title + company. A hit is imported into
the store so score.py's dedup merges the two rows and the LinkedIn copy
(with its real posted date, applicants and description) wins. A miss is
recorded so the row can be tagged "not found on LinkedIn" rather than
trusted on Ladders' word. Each row is checked at most once a week.
"""
import argparse, json, pathlib, re, sys, time
from datetime import datetime, timezone, date
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import collect as C          # reuse the guest search, parsers and store path
import yaml

HERE = pathlib.Path(__file__).parent
CFG = yaml.safe_load((HERE / "config.yaml").read_text())
ALERT_PREFIX = ("la-", "ca-")

def norm(s):
    s = re.sub(r"\(.*?\)", " ", (s or "").lower())
    s = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|company|plc|group|holdings|the)\b\.?", " ", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()

def title_words(t):
    t = re.sub(r"\bsr\.?\b", "senior", (t or "").lower()); t = re.sub(r"\(.*?\)", " ", t)
    return set(re.findall(r"[a-z0-9]+", t)) - {"and", "of", "the", "for", "a", "remote", "us"}

def days_since(iso):
    try: return (datetime.now(timezone.utc).date() - date.fromisoformat(iso[:10])).days
    except Exception: return None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--max", type=int, default=40); ap.add_argument("--recheck-days", type=int, default=7)
    a = ap.parse_args()
    jobs = json.loads(C.STORE.read_text())
    today = datetime.now(timezone.utc).date().isoformat()
    todo = []
    for j in jobs.values():
        if not j["id"].startswith(ALERT_PREFIX): continue
        if not C.title_clears_tier(j.get("title", "")): continue
        d = days_since(j.get("posted") or "")
        if d is None or d > 14: continue
        last = j.get("linkedin_checked")
        if last and (days_since(last) or 0) < a.recheck_days: continue
        if j.get("verified_linkedin"): continue
        todo.append(j)
    todo = todo[: a.max]
    print(f"verifying {len(todo)} alert-only postings against LinkedIn")
    found = 0
    for j in todo:
        no_company = not (j.get("company") or "").strip()
        loc = j.get("location") or "United States"
        if re.search(r"remote|virtual", loc, re.I): loc = "United States"
        q = j.get("title", "") if no_company else f'{j.get("title","")} {j.get("company","")}'
        html = C.get(C.SEARCH, keywords=q, location=loc, f_TPR="r2592000", start=0)
        hit = None
        want_c, want_t = norm(j.get("company")), title_words(j.get("title"))
        for c in C.parse_cards(html):
            tw = title_words(c["title"]); overlap = len(want_t & tw) / max(1, len(want_t | tw))
            if no_company:
                # no company to match on, so demand a near-exact title
                if overlap >= 0.85: hit = c; break
            else:
                same_co = norm(c["company"]) == want_c or (len(want_c) >= 4 and (want_c in norm(c["company"]) or norm(c["company"]) in want_c))
                if same_co and overlap >= 0.6: hit = c; break
        j["linkedin_checked"] = today
        if hit:
            found += 1
            j["verified_linkedin"] = hit["id"]
            if no_company: j["company"] = hit["company"]; j["needs_company"] = False
            li = jobs.setdefault(hit["id"], {"first_seen": C.now(), "sources": []})
            for k, v in hit.items():
                if v and not li.get(k): li[k] = v
            li["url"] = C.VIEW.format(id=hit["id"]); li["last_seen"] = C.now()
            if "verify | United States" not in li["sources"]: li["sources"].append("verify | United States")
            print(f"  ok   {j['company'][:22]:<22} {j['title'][:44]:<44} -> LinkedIn {hit['id']}")
        else:
            j["linkedin_found"] = False
            print(f"  miss {j['company'][:22]:<22} {j['title'][:44]}")
        C.nap()
    C.STORE.write_text(json.dumps(jobs, indent=1))
    print(f"{found}/{len(todo)} confirmed on LinkedIn; unconfirmed rows will be tagged")

if __name__ == "__main__":
    main()

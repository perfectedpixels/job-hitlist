#!/usr/bin/env python3
"""Harvest job-alert emails from Apple Mail -> data/alerts.json

    ./run mail_alerts.py              # last 8 days
    ./run mail_alerts.py --days 30

Sources (all read from the inbox, no site logins):
  jobright      "Instant Alert" mails: company, match %, title, comp, location,
                referrals, posted-ago, stable jobs/info/<id> link.
  careerbuilder daily alert: title | company | city | Posted: | ISO date.
                Links are tracking redirects, no job id.
  ladders       several mails a day: title | comp | company | location.
                Tracking links, no id, no posted date (email date is used).

Rows without a stable id are keyed by normalised company+title, and score.py
collapses near-duplicates across sources, so the same Amazon posting seen on
LinkedIn, Ladders and Jobright becomes one row.
"""
import argparse, email, json, pathlib, re, subprocess, sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from bs4 import BeautifulSoup

HERE = pathlib.Path(__file__).parent
OUT = HERE / "data/alerts.json"
SEP = "=====MSG====="
SENDERS = {"jobright": "jobright", "careerbuilder": "careerbuilder", "ladders": "theladders"}
# Mail's `sender contains` query is loose in practice, so every message is
# re-checked against the real From: header before a parser sees it.
FROM_RE = {"jobright": r"@jobright\.(ai|com)\b", "careerbuilder": r"careerbuilder\.com\b", "ladders": r"@(my|inform)\.theladders\.com\b"}

APPLESCRIPT = '''
with timeout of 900 seconds
  tell application "Mail"
    set cutoff to (current date) - (%d * days)
    set out to ""
    set msgs to (messages of inbox whose sender contains "%s" and date received > cutoff)
    repeat with m in msgs
      set out to out & "%s" & linefeed & (source of m) & linefeed
    end repeat
    return out
  end tell
end timeout
'''

def fetch_sources(sender_fragment, days):
    # Reading message sources through Mail is ~2s each; Ladders alone sends
    # ~10 a day, so the cap scales with the window. A hang well past that is
    # the signature of an unanswered Automation permission prompt.
    cap = 120 + 60 * days
    try:
        r = subprocess.run(["osascript", "-e", APPLESCRIPT % (days, sender_fragment, SEP)],
                           capture_output=True, text=True, timeout=cap)
    except subprocess.TimeoutExpired:
        sys.exit(f"Mail did not answer in {cap}s for '{sender_fragment}'. If this persists, check "
                 "System Settings > Privacy & Security > Automation > allow 'sh'/'osascript' to control Mail.")
    if r.returncode != 0:
        sys.exit(f"AppleScript failed (Mail permission?): {r.stderr.strip()[:300]}")
    return [s.lstrip() for s in r.stdout.split(SEP) if s.strip()]

def html_of(raw):
    msg = email.message_from_string(raw)
    try: received = parsedate_to_datetime(msg["Date"])
    except Exception: received = datetime.now(timezone.utc)
    html = next((p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "ignore")
                 for p in msg.walk() if p.get_content_type() == "text/html"), "")
    return msg, received, BeautifulSoup(html, "html.parser")

def block_lines(a, stop_when_many_links=4):
    """Climb from an anchor to the smallest container that is still one job."""
    node = a
    for _ in range(8):
        if node.parent is None: break
        if len(node.parent.select("a[href]")) > stop_when_many_links: break
        node = node.parent
    return [l.strip() for l in node.get_text("\n").splitlines() if l.strip()]

def ago_to_days(s):
    m = re.search(r"(\d+)\s*(minute|hour|day|week|month)", s or "")
    if not m: return None
    n, u = int(m.group(1)), m.group(2)
    return {"minute": n / 1440, "hour": n / 24, "day": n, "week": 7 * n, "month": 30 * n}[u]

# ---------------------------------------------------------------- parsers
def parse_jobright(raw):
    msg, received, soup = html_of(raw)
    jobs, seen = [], set()
    for a in soup.select('a[href*="jobs/info/"]'):
        jid = re.search(r"jobs/info/([0-9a-f]+)", a["href"]).group(1)
        if jid in seen: continue
        seen.add(jid)
        node = a
        while node.parent is not None:
            if len(set(re.findall(r"jobs/info/([0-9a-f]+)", str(node.parent)))) > 1: break
            node = node.parent
        L = [l.strip() for l in node.get_text("\n").splitlines() if l.strip()]
        try: pct = next(i for i, l in enumerate(L) if l == "%")
        except StopIteration: continue
        company = L[0]; industry = L[1] if pct > 2 else ""
        stage = L[2].lstrip("· ").strip() if pct > 3 else ""
        match = int(L[pct - 1]) if L[pct - 1].isdigit() else None
        rest = L[pct + 1:]
        title = rest[0] if rest else ""
        comp = next((x for x in rest[1:4] if re.match(r"^\$\d", x)), None)
        network = next((x for x in rest if re.search(r"referral", x)), None)
        ago = next((x for x in rest if re.search(r"\bago\b", x)), None)
        locs = [x for x in rest[1:5] if x not in (comp, network, ago) and not re.search(r"ago|applicant|APPLY|^·$", x)]
        d = ago_to_days(ago)
        posted = (received - timedelta(days=d)).date().isoformat() if d is not None else received.date().isoformat()
        jobs.append({"source": "jobright", "jr_id": jid, "url": f"https://jobright.ai/jobs/info/{jid}",
                     "company": company, "title": title, "location": locs[0] if locs else "",
                     "match": match, "comp": comp, "network": network, "posted": posted,
                     "summary": f"{industry} · {stage}".strip(" ·"), "received": received.isoformat(timespec="minutes")})
    return jobs

def parse_careerbuilder(raw):
    msg, received, soup = html_of(raw)
    # the alert subject ends "..., <City>, <State>"; cities in the body carry no state
    state = ""
    m = re.search(r",\s*([A-Za-z .]+),\s*([A-Za-z ]+)\s*$", (msg["Subject"] or "").replace("\n", " "))
    if m: state = {"washington": "WA", "california": "CA"}.get(m.group(2).strip().lower(), m.group(2).strip())
    jobs, seen = [], set()
    for a in soup.select("a[href]"):
        L = block_lines(a)
        if len(L) < 3 or not any(l.startswith("Posted") for l in L): continue
        title, company, city = L[0], L[1], L[2]
        key = (title, company)
        if key in seen or title.lower().startswith("apply"): continue
        seen.add(key)
        iso = next((l for l in L if re.match(r"\d{4}-\d{2}-\d{2}", l)), None)
        jobs.append({"source": "careerbuilder", "url": a["href"], "company": company, "title": title,
                     "location": f"{city}, {state}".strip(", "), "posted": iso[:10] if iso else received.date().isoformat(),
                     "received": received.isoformat(timespec="minutes")})
    return jobs

def parse_ladders(raw):
    """Two layouts seen so far:
      A "Your Skills are in High Demand":  title / "/ City, ST" / "/" / "$comp*" / Remote
         -- no company anywhere. Row is kept with company="" and
            needs_company=True; verify_alerts.py recovers it from LinkedIn.
      B "New Jobs Posted":  title / "$comp*" / "| Company | Location" / Apply Now
    """
    msg, received, soup = html_of(raw)
    jobs, seen = [], set()
    for a in soup.select("a[href]"):
        t = a.get_text(" ", strip=True)
        if len(t) < 8 or re.search(r"apply now|find more|unsubscribe|view|browser|preferences", t, re.I): continue
        L = block_lines(a)
        if len(L) < 2 or L[0] != t: continue
        title = t
        comp = next((x.rstrip("*").strip() for x in L[1:5] if re.match(r"^\$\d", x)), None)
        workplace = next((x for x in L[1:6] if x in ("Remote", "Hybrid", "On-site", "Onsite")), None)
        company, location = "", ""
        pipe = next((x for x in L[1:6] if "|" in x and not re.match(r"^\$", x)), None)
        if pipe:                                            # layout B
            parts = [q.strip() for q in pipe.split("|") if q.strip()]
            if len(parts) >= 2: company, location = parts[0], parts[1]
            elif parts: location = parts[0]
        else:                                               # layout A
            loc = next((x for x in L[1:4] if x.startswith("/") and len(x.strip("/ \xa0")) > 1), None)
            if loc: location = loc.strip("/ \xa0")
        if location in ("Virtual / Travel", "Virtual"): location = "Remote"
        if not location and workplace: location = workplace
        key = (title, company or location)
        if key in seen or not location: continue
        seen.add(key)
        jobs.append({"source": "ladders", "url": a["href"], "company": company, "title": title, "location": location,
                     "workplace": workplace, "comp": comp, "posted": received.date().isoformat(),
                     "needs_company": not company, "received": received.isoformat(timespec="minutes")})
    return jobs

PARSERS = {"jobright": parse_jobright, "careerbuilder": parse_careerbuilder, "ladders": parse_ladders}

def norm(s):
    s = re.sub(r"\(.*?\)", " ", (s or "").lower())
    s = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|company|plc|group|holdings|the)\b\.?", " ", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--days", type=int, default=3)   # daily run; older mail is already in alerts.json
    ap.add_argument("--only", choices=list(PARSERS), help="one source, for debugging")
    a = ap.parse_args()
    existing = json.loads(OUT.read_text()) if OUT.exists() else []
    by_key = {(r.get("jr_id") and f"jr:{r['jr_id']}") or f"{r['source']}:{norm(r['company']) or 'loc-' + norm(r.get('location',''))}|{norm(r['title'])}": r for r in existing}
    stats = {}
    for src, frag in SENDERS.items():
        if a.only and src != a.only: continue
        msgs = fetch_sources(frag, a.days)
        n_new, skipped = 0, 0
        for raw in msgs:
            frm = re.search(r"^From:\s*(.*)$", raw, re.M | re.I)
            if not frm or not re.search(FROM_RE[src], frm.group(1), re.I):
                skipped += 1; continue
            for j in PARSERS[src](raw):
                k = f"jr:{j['jr_id']}" if j.get("jr_id") else f"{src}:{norm(j['company']) or 'loc-' + norm(j['location'])}|{norm(j['title'])}"
                if k not in by_key: by_key[k] = j; n_new += 1
                else:
                    old = by_key[k]
                    # keep the earliest sighting as the posted date: alert mails repeat for days
                    if j["posted"] < (old.get("posted") or "9"): old["posted"] = j["posted"]
                    for f in ("comp", "network", "match", "location", "url"):
                        if j.get(f) and not old.get(f): old[f] = j[f]
        stats[src] = (len(msgs) - skipped, n_new)
        if skipped: print(f"  {src:<14} skipped {skipped} messages whose From: was not {src}")
    OUT.write_text(json.dumps(list(by_key.values()), indent=1))
    for src, (m, n) in stats.items(): print(f"  {src:<14} {m:>3} emails  {n:>3} new jobs")
    print(f"{len(by_key)} total in alerts.json")

if __name__ == "__main__":
    main()

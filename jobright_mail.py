#!/usr/bin/env python3
"""Harvest Jobright's "Instant Alert" emails from Apple Mail -> data/jobright.json

    ./run jobright_mail.py            # last 8 days
    ./run jobright_mail.py --days 30

Why email instead of the site: the recommendations page is a logged-in SPA
that needs Jason's session, so it could only be read by driving his Chrome by
hand. The alert emails carry the same fields (company, match %, title, comp,
location, referrals, posted-ago, and a stable jobright.ai/jobs/info/<id> link)
and Mail is readable with AppleScript, so this runs unattended.
"""
import argparse, email, json, pathlib, re, subprocess
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from bs4 import BeautifulSoup

HERE = pathlib.Path(__file__).parent
OUT = HERE / "data/jobright.json"
SEP = "=====JRMSG====="

APPLESCRIPT = '''
-- Inbox only, and a long timeout: walking every mailbox in every account
-- took Mail past the 2-minute AppleEvent limit when launchd ran it (-1712).
with timeout of 900 seconds
  tell application "Mail"
    set cutoff to (current date) - (%d * days)
    set out to ""
    set msgs to (messages of inbox whose sender contains "jobright" and date received > cutoff)
    repeat with m in msgs
      set out to out & "%s" & linefeed & (source of m) & linefeed
    end repeat
    return out
  end tell
end timeout
'''

def fetch_sources(days):
    # 90s is generous for an inbox query that takes ~20s by hand. A hang here
    # means macOS is waiting for an Automation permission click for the
    # launching process (System Settings > Privacy & Security > Automation).
    try:
        r = subprocess.run(["osascript", "-e", APPLESCRIPT % (days, SEP)], capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        raise SystemExit("Mail did not answer in 90s. Likely an unanswered Automation permission prompt: "
                         "System Settings > Privacy & Security > Automation > allow 'sh'/'osascript' to control Mail.")
    if r.returncode != 0:
        raise SystemExit(f"AppleScript failed (Mail permission?): {r.stderr.strip()[:300]}")
    return [s for s in r.stdout.split(SEP) if s.strip()]

def ago_to_days(s):
    m = re.search(r"(\d+)\s*(minute|hour|day|week|month)", s or "")
    if not m: return None
    n, u = int(m.group(1)), m.group(2)
    return {"minute": n / 1440, "hour": n / 24, "day": n, "week": 7 * n, "month": 30 * n}[u]

def parse_message(raw):
    msg = email.message_from_string(raw.lstrip())   # a leading newline hides the headers from the parser
    try: received = parsedate_to_datetime(msg["Date"])
    except Exception: received = datetime.now(timezone.utc)
    html = next((p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "ignore")
                 for p in msg.walk() if p.get_content_type() == "text/html"), None)
    if not html: return []
    soup = BeautifulSoup(html, "html.parser")
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
        # shape: company, industry, "· stage", match, "%", title, [comp], location, [N+ referrals], "X ago", ...
        try:
            pct = next(i for i, l in enumerate(L) if l == "%")
        except StopIteration:
            continue
        company = L[0]; industry = L[1] if pct > 2 else ""
        stage = L[2].lstrip("· ").strip() if pct > 3 else ""
        match = int(L[pct - 1]) if L[pct - 1].isdigit() else None
        rest = L[pct + 1:]
        title = rest[0] if rest else ""
        comp = next((x for x in rest[1:4] if re.match(r"^\$\d", x)), None)
        network = next((x for x in rest if re.search(r"referral", x)), None)
        ago = next((x for x in rest if re.search(r"\bago\b", x)), None)
        loc_candidates = [x for x in rest[1:5] if x not in (comp, network, ago) and not re.search(r"ago|applicant|APPLY|^·$", x)]
        location = loc_candidates[0] if loc_candidates else ""
        d = ago_to_days(ago)
        posted = (received - timedelta(days=d)).date().isoformat() if d is not None else received.date().isoformat()
        jobs.append({
            "jr_id": jid, "url": f"https://jobright.ai/jobs/info/{jid}",
            "company": company, "title": title, "location": location,
            "workplace": "Remote" if re.search(r"remote", location, re.I) else None,
            "match": match, "comp": comp, "network": network, "posted": posted,
            "summary": f"{industry} · {stage}".strip(" ·"), "level": None, "applicants": None,
            "source_email": received.isoformat(timespec="minutes"),
        })
    return jobs

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--days", type=int, default=8)
    a = ap.parse_args()
    existing = json.loads(OUT.read_text()) if OUT.exists() else []
    by_key = {}
    for r in existing:
        by_key[r.get("jr_id") or f"{r['company']}|{r['title']}"] = r
    n_msgs, n_new = 0, 0
    for raw in fetch_sources(a.days):
        n_msgs += 1
        for j in parse_message(raw):
            k = j["jr_id"]
            if k not in by_key: n_new += 1; by_key[k] = j
            else:
                old = by_key[k]
                if (j["posted"] or "") > (old.get("posted") or ""): old["posted"] = j["posted"]
                for f in ("comp", "network", "match", "location"):
                    if j.get(f) and not old.get(f): old[f] = j[f]
    OUT.write_text(json.dumps(list(by_key.values()), indent=1))
    print(f"read {n_msgs} Jobright emails from the last {a.days} days; {n_new} new jobs; {len(by_key)} total in jobright.json")

if __name__ == "__main__":
    main()

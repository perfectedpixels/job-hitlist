#!/usr/bin/env python3
"""Score everything in data/jobs.json against config.yaml -> data/scored.json"""
import json, pathlib, re
from datetime import datetime, timezone, date
import yaml

HERE = pathlib.Path(__file__).parent
CFG = yaml.safe_load((HERE / "config.yaml").read_text())
jobs = json.loads((HERE / "data/jobs.json").read_text())

def days_since(iso):
    if not iso: return None
    try: d = date.fromisoformat(iso[:10])
    except ValueError: return None
    return (datetime.now(timezone.utc).date() - d).days

def score(j):
    t = (j.get("title") or "").lower()
    loc = (j.get("location") or "").lower()
    desc = (j.get("description") or "").lower()
    parts, notes = {}, []

    if not re.search(CFG["design_signal"], t) or re.search(CFG["design_exclude"], t):
        return None
    # Tier per track. A job is kept if it clears a tier on ANY track; the
    # non-tier parts (location, recency, AI) are shared, so each track's score
    # is tier + shared. render.py shows one tab per track.
    track_tiers, tier = {}, None
    for tname, tcfg in CFG["tracks"].items():
        if tcfg.get("exclude") and re.search(tcfg["exclude"], t): continue
        for name, v in tcfg["tiers"].items():
            if re.search(v["pattern"], t):
                track_tiers[tname] = (name, v["score"], v.get("note"))
                break
    if not track_tiers: return None
    # primary tier for the legacy single score = the best-scoring track
    best_t = max(track_tiers, key=lambda k: track_tiers[k][1])
    tier, parts["tier"], note = track_tiers[best_t]
    if note: notes.append(note)

    L = CFG["locations"]
    # Remote only counts when LinkedIn's own remote filter found it, or the
    # location/title says so. Sniffing "remote" out of descriptions matched
    # "no remote" and "not remote" and put Kansas City in the top ten.
    via_remote_filter = any(s.endswith("| United States") for s in j.get("sources", []))
    says_remote = bool(re.search(r"\bremote\b", loc + " " + t))
    if re.search(L["target"], loc): parts["location"] = L["target_score"]
    elif says_remote: parts["location"] = L["remote_score"]; notes.append("remote")
    elif via_remote_filter: parts["location"] = L["remote_filter_score"]; notes.append("remote per LinkedIn filter")
    else: parts["location"] = L["other_score"]

    d = days_since(j.get("posted_detail") or j.get("posted"))
    if d is not None:
        for r in CFG["recency"]:
            if d <= r["max_days"]: parts["recency"] = r["score"]; break
    else:
        parts["recency"] = 0
    if j.get("applicants") and re.search(r"first 25|fewer than", j["applicants"], re.I):
        parts["few_applicants"] = CFG["few_applicants_score"]

    ai_hits = len(re.findall(CFG["ai_signal"], desc))
    if ai_hits >= 2: parts["ai"] = CFG["ai_score"]
    for kb in CFG["keywords_bonus"]:
        if re.search(kb["pattern"], desc): parts.setdefault("keywords", 0); parts["keywords"] += kb["score"]

    if re.search(CFG["agency_pattern"], (j.get("company") or "").lower()):
        parts["agency"] = CFG["agency_score"]; notes.append("staffing agency / aggregator")

    sen = (j.get("seniority_level") or "").lower()
    if sen in ("entry level", "associate", "internship"): return None

    total = sum(parts.values())
    band = "strong" if total >= CFG["bands"]["strong"] else "good" if total >= CFG["bands"]["good"] else "weak"
    shared = total - parts["tier"]
    track_scores = {k: shared + v[1] for k, v in track_tiers.items()}
    track_tier = {k: v[0] for k, v in track_tiers.items()}
    return {**j, "score": total, "parts": parts, "tier": tier, "band": band,
            "days": d, "ai_hits": ai_hits, "notes": notes,
            "track_scores": track_scores, "track_tier": track_tier}

rows = [s for s in (score(j) for j in jobs.values()) if s]

# ---- collapse duplicates across sources -----------------------------------
# LinkedIn, Ladders, CareerBuilder and Jobright all carry the same postings
# under slightly different names ("Sr. UX Designer" / "Senior UX Designer",
# "Amazon Web Services (AWS)" / "Amazon"). Only LinkedIn and Jobright have
# stable ids, so grouping is by normalised company + fuzzy title.
import difflib
COMPANY_ALIAS = {"amazon web services": "amazon", "aws": "amazon", "amazon com": "amazon",
                 "amazon jobs": "amazon", "alphabet": "google", "meta platforms": "meta"}
def norm_company(c):
    c = re.sub(r"\(.*?\)", " ", (c or "").lower())
    c = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|company|plc|group|holdings|the)\b\.?", " ", c)
    c = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", c)).strip()
    return COMPANY_ALIAS.get(c, c)
def norm_title(t, company):
    t = (t or "").lower()
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"\bsr\.?\b", "senior", t); t = re.sub(r"\bjr\.?\b", "junior", t)
    t = re.sub(r"\bmgr\b", "manager", t); t = t.replace("&", " and ")
    c = norm_company(company)
    if c: t = re.sub(r"(,|-|–|\bat\b|\bfor\b)\s*" + re.escape(c) + r"\b.*$", " ", t)
    t = re.sub(r"\b(remote|hybrid|us|usa|united states)\b", " ", t)
    t = re.sub(r"\b[a-z]*\d{4,}[a-z0-9-]*\b", " ", t)          # req numbers
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()
def same_title(a, b):
    if a == b: return True
    if len(a) >= 15 and len(b) >= 15 and (a in b or b in a): return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.86

rows.sort(key=lambda r: -r["score"])
groups = []                     # each: {"key":(company, title), "rows":[...]}
for r in rows:
    c, t = norm_company(r.get("company")), norm_title(r.get("title"), r.get("company"))
    g = next((g for g in groups if g["c"] == c and same_title(g["t"], t)), None)
    if g is None: groups.append({"c": c, "t": t, "rows": [r]})
    else: g["rows"].append(r)

collapsed, merged = 0, []
for g in groups:
    keep, rest = g["rows"][0], g["rows"][1:]
    collapsed += len(rest)
    keep["all_ids"] = [x["id"] for x in g["rows"]]
    keep["also_in"] = sorted({x.get("location") for x in rest} - {keep.get("location"), None})
    seen_on = []
    for x in g["rows"]:
        for src in x.get("sources", []):
            name = "LinkedIn" if "|" in src else src.capitalize()
            if name not in seen_on: seen_on.append(name)
    keep["seen_on"] = seen_on
    for x in rest:
        for f in ("jobright_match", "jobright_network", "comp", "applicants", "description"):
            if x.get(f) and not keep.get(f): keep[f] = x[f]
        for k, v in (x.get("track_scores") or {}).items():
            if v > keep["track_scores"].get(k, -999): keep["track_scores"][k] = v; keep["track_tier"][k] = x["track_tier"][k]
    ages = [x["days"] for x in g["rows"] if x.get("days") is not None]
    if ages and keep.get("days") is not None and max(ages) - keep["days"] >= 5:
        keep["notes"].append(f"first seen {max(ages)}d ago on another source: likely reposted")
    if len(g["rows"]) > 1: keep["notes"].append(f"{len(seen_on)} sources")
    merged.append(keep)
rows = merged
print(f"collapsed {collapsed} duplicate rows into {len(rows)}")
rows.sort(key=lambda r: (-r["score"], r["days"] if r["days"] is not None else 99))
(HERE / "data/scored.json").write_text(json.dumps(rows, indent=1))
shown = [r for r in rows if r["score"] >= CFG["bands"]["show_min"]]
print(f"{len(jobs)} in store -> {len(rows)} design-leadership roles -> {len(shown)} at or above show_min")
for r in shown[:25]:
    print(f"  {r['score']:>4} {r['band']:<6} {str(r['days'])+'d':<4} {(r.get('company') or '?')[:24]:<24} {(r.get('title') or '?')[:52]:<52} {(r.get('location') or '')[:22]}")

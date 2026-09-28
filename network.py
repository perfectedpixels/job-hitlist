"""Match hitlist companies against a LinkedIn Connections.csv export.

Export: LinkedIn > Settings > Data privacy > Get a copy of your data >
Connections. Drop the file at data/Connections.csv. The file starts with a
few 'Notes:' lines before the real header, which this handles.
"""
import csv, pathlib, re

HERE = pathlib.Path(__file__).parent
CSV = HERE / "data" / "Connections.csv"
SUFFIX = re.compile(r"\b(inc|llc|ltd|corp|corporation|co|company|plc|group|holdings|technologies|technology|labs)\b\.?", re.I)

def norm(name):
    s = (name or "").lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = SUFFIX.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def load():
    if not CSV.exists(): return []
    lines = CSV.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("First Name")), 0)
    rows = list(csv.DictReader(lines[start:]))
    out = []
    for r in rows:
        out.append({
            "name": f"{r.get('First Name','').strip()} {r.get('Last Name','').strip()}".strip(),
            "url": r.get("URL", "").strip(),
            "company": r.get("Company", "").strip(),
            "position": r.get("Position", "").strip(),
            "connected": r.get("Connected On", "").strip(),
            "_n": norm(r.get("Company", "")),
        })
    return [c for c in out if c["_n"]]

def matches(connections, company):
    n = norm(company)
    if len(n) < 3: return []
    hits = []
    for c in connections:
        cn = c["_n"]
        if cn == n or (len(n) >= 4 and n in cn) or (len(cn) >= 4 and cn in n):
            hits.append(c)
    return hits

#!/usr/bin/env python3
"""Personalize the job hitlist for a new user.

    ./run setup.py                     # interactive
    ./run setup.py --answers me.json   # non-interactive (what /hitlist-setup uses)

Writes config.yaml and watchlist.yaml from the templates, optionally installs
the 7am scheduler and the local server as launchd agents, and runs the first
collection. The resume side (resume.yaml) is separate: copy
autofill/resume.template.yaml, fill it in, then `./run autofill/build_userscript.py`.
"""
import argparse, json, os, pathlib, re, subprocess, sys
import yaml

HERE = pathlib.Path(__file__).resolve().parent
HOME = pathlib.Path.home()

Q = [  # key, prompt, default, kind
    ("name",       "Your name (for the userscript label)", "", "str"),
    ("titles",     "Target job titles, comma-separated (e.g. Product Design Director, Head of Design)", "", "list"),
    ("also_titles","Weaker-fit titles to include at reduced weight, comma-separated (blank for none)", "", "list"),
    ("field_words","Words that mark a posting as your field, comma-separated (e.g. product design, ux, user experience)", "", "list"),
    ("exclude_words","Words that mean a posting is NOT your field even if it matches, comma-separated (e.g. for a designer: engineer, architect)", "intern, internship", "list"),
    ("cities",     "Target cities/regions, semicolon-separated (e.g. Seattle, Washington; Austin, Texas)", "", "list_semicolon"),
    ("remote",     "Include remote US roles? (y/n)", "y", "bool"),
    ("alerts",     "Read job-alert emails (Jobright/Ladders/CareerBuilder) from Apple Mail? (y/n)", "n", "bool"),
    ("schedule",   "Install the 7am scheduler and local server (macOS launchd)? (y/n)", "y", "bool"),
]

def ask(prompt, default):
    v = input(f"{prompt}{' [' + default + ']' if default else ''}: ").strip()
    return v or default

def parse(kind, v):
    if kind == "bool": return str(v).strip().lower() in ("y", "yes", "true", "1")
    if kind == "list": return [x.strip() for x in str(v).split(",") if x.strip()] if isinstance(v, str) else list(v)
    if kind == "list_semicolon": return [x.strip() for x in re.split(r"[;\n]", str(v)) if x.strip()] if isinstance(v, str) else list(v)
    return str(v).strip()

def word_re(words):
    """Regex alternation of whole words/phrases; spaces stay readable."""
    esc = lambda w: re.escape(w.lower()).replace("\\ ", " ")
    return r"\b(" + "|".join(esc(w) for w in words) + r")\b"

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--answers", help="JSON file of answers; skips the prompts")
    ap.add_argument("--no-run", action="store_true", help="write config only; do not collect")
    a = ap.parse_args()
    raw = json.loads(pathlib.Path(a.answers).read_text()) if a.answers else {}
    ans = {}
    for key, prompt, default, kind in Q:
        v = raw.get(key) if a.answers else ask(prompt, default)
        if v is None or v == "": v = default
        ans[key] = parse(kind, v)
    if not ans["titles"] or not ans["field_words"] or not ans["cities"]:
        sys.exit("titles, field_words and cities are required")

    # ---- config.yaml from the template
    t = (HERE / "config.template.yaml").read_text()
    keywords = ans["titles"] + [f"{w} {k}" for k in ("director", "manager", "lead") for w in ans["field_words"][:1]]
    tracks = {"primary": {"label": "Primary", "tiers": {
        "strong": {"pattern": word_re(ans["titles"]), "score": 100},
        **({"also": {"pattern": word_re(ans["also_titles"]), "score": 60}} if ans["also_titles"] else {}),
    }}}
    city_words = sorted({w.strip().lower() for c in ans["cities"] for w in c.split(",") if w.strip()})
    t = (t.replace("__KEYWORDS__", json.dumps(ans["titles"]))
          .replace("__LOCATIONS__", json.dumps(ans["cities"]))
          .replace("__REMOTE__", "true" if ans["remote"] else "false")
          .replace("__TRACKS__", "\n" + "\n".join("  " + l for l in yaml.safe_dump(tracks, sort_keys=False).splitlines()))
          .replace("__TARGET_RE__", word_re(city_words).replace("'", "''"))
          # a title the user asked for is in their field by definition
          .replace("__DESIGN_SIGNAL__", word_re(ans["field_words"] + ans["titles"] + ans["also_titles"]).replace("'", "''"))
          .replace("__DESIGN_EXCLUDE__", word_re(ans["exclude_words"] or ["internship"]).replace("'", "''"))
          .replace("__ALERTS__", "true" if ans["alerts"] else "false"))
    (HERE / "config.yaml").write_text(t)
    (HERE / "watchlist.yaml").write_text("# Companies to poll directly. Add Greenhouse/Lever/Ashby boards by slug.\nboards: []\nsites: []\n")
    print("wrote config.yaml and watchlist.yaml")

    # ---- resume.yaml starter
    rs = HERE / "resume.yaml"
    if not rs.exists():
        rs.write_text((HERE / "autofill/resume.template.yaml").read_text()); print("wrote resume.yaml from the template (fill it in, then ./run autofill/build_userscript.py)")

    # ---- launchd agents
    if ans["schedule"] and sys.platform == "darwin":
        py = HERE / "run"; la = HOME / "Library/LaunchAgents"; la.mkdir(parents=True, exist_ok=True)
        def plist(label, args, extra=""):
            return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>Label</key><string>{label}</string>
<key>ProgramArguments</key><array>{"".join(f"<string>{x}</string>" for x in args)}</array>
<key>EnvironmentVariables</key><dict><key>NO_OPEN</key><string>1</string><key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin</string></dict>
{extra}<key>StandardOutPath</key><string>{HERE}/data/launchd.log</string><key>StandardErrorPath</key><string>{HERE}/data/launchd.log</string>
</dict></plist>'''
        (HERE / "data").mkdir(exist_ok=True)
        agents = {
            "com.jobhitlist.daily": plist("com.jobhitlist.daily", ["/bin/sh", str(HERE / "daily.sh")],
                "<key>StartCalendarInterval</key><dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>\n"),
            "com.jobhitlist.server": plist("com.jobhitlist.server", [str(HOME / ".venvs/applications/bin/python"), str(HERE / "serve.py")],
                "<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>\n"),
        }
        uid = os.getuid()
        for label, body in agents.items():
            f = la / f"{label}.plist"; f.write_text(body)
            subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"], capture_output=True)
            r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(f)], capture_output=True, text=True)
            print(f"launchd {label}: {'ok' if r.returncode == 0 else r.stderr.strip()[:80]}")

    if a.no_run: return
    print("\nfirst collection (a few minutes)...")
    subprocess.run(["/bin/sh", str(HERE / "daily.sh")], cwd=HERE, env=dict(os.environ, NO_OPEN="1"))
    print("\nDone. Open http://localhost:8766/ (or hitlist.html). Next: fill in resume.yaml and run ./run autofill/build_userscript.py")

if __name__ == "__main__":
    main()

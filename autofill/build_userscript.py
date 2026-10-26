#!/usr/bin/env python3
"""Generate a Tampermonkey userscript that autofills Workday work history
and LinkedIn from resume.yaml.

The point of generating rather than hand-writing: resume.yaml stays the single
source of truth. Edit the YAML, re-run this, reinstall the script.

    python3 build_userscript.py            # writes workday-autofill.user.js

What the script fills (the deterministic parts):
    - every work history entry, with exact titles and dates
    - the LinkedIn URL

Education is deliberately NOT filled. Its school field is a lookup on some
requisitions, its Degree is a required dropdown, and its "Add" button collides
with Work Experience's. Three fields by hand beats a whole class of failure.

What it deliberately does NOT touch, matching the same rules Claude follows:
    - dropdowns and comboboxes (they need real events; one click for a human)
    - consent, terms, EEO, veteran, disability, DOB, SSN
    - file uploads
    - Submit
"""

import json, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
try:
    import yaml
except ImportError:
    sys.exit("Needs pyyaml:  python3 -m pip install --user pyyaml")

HERE = pathlib.Path(__file__).parent
# resume.yaml is private and gitignored. Look next to this script, then in the
# repo root, then one level above the repo (where Jason keeps his).
def _find_resume():
    if "--resume" in sys.argv:
        return pathlib.Path(sys.argv[sys.argv.index("--resume") + 1]).expanduser()
    for c in (HERE / "resume.yaml", HERE.parent / "resume.yaml", HERE.parent.parent / "resume.yaml"):
        if c.exists(): return c
    sys.exit("No resume.yaml found. Copy resume.template.yaml to resume.yaml and fill it in, or pass --resume PATH.")
RESUME = _find_resume()
data = yaml.safe_load(RESUME.read_text(encoding="utf-8"))
OUT_DIR = RESUME.parent

# Optional per-application overlay: overrides free description text only.
# Company, title, dates and location always stay locked to resume.yaml.
OVERLAY = {}
if "--overlay" in sys.argv:
    op = HERE / sys.argv[sys.argv.index("--overlay") + 1]
    if not op.exists():
        sys.exit(f"No such overlay: {op}")
    ov = yaml.safe_load(op.read_text(encoding="utf-8")) or {}
    OVERLAY = ov.get("work") or {}
    print(f"overlay: {op.name} ({len(OVERLAY)} roles)")


def ym(v):
    """resume.yaml dates are YYYY-MM (parsed as date or str). -> ('MM','YYYY')"""
    if v is None:
        return ("", "")
    s = str(v)
    parts = s.split("-")
    return (parts[1].lstrip("0") if len(parts) > 1 else "", parts[0])


def describe(w):
    ov = OVERLAY.get(w.get("id")) or {}
    if (ov.get("description") or {}).get("medium"):
        return ov["description"]["medium"]
    d = w.get("description") or {}
    body = d.get("long") or d.get("medium") or d.get("short") or ""
    body = " ".join(body.split())
    bullets = w.get("bullets") or []
    if bullets:
        body += "\n\n" + "\n".join("- " + " ".join(str(b).split()) for b in bullets)
    return body


def resolve_track(name):
    """Return the ordered work list for a track. `director` is the base list.
    Other tracks list items by id that inherit the base role and override the
    keys given; items without a base id must be complete."""
    base = {w["id"]: w for w in data.get("work", [])}
    t = (data.get("tracks") or {}).get(name) or {}
    if not t.get("work"):
        return list(data.get("work", []))
    out = []
    for item in t["work"]:
        merged = dict(base.get(item.get("id"), {}))
        merged.update(item)
        out.append(merged)
    return out

def role_rows(work):
    rows = []
    for w in work:
        sm, sy = ym(w.get("start"))
        em, ey = ym(w.get("end"))
        loc = w.get("location") or {}
        city = loc.get("city") or ""
        region = loc.get("state") or loc.get("country") or ""
        rows.append({
            "title": w.get("title", ""),
            "company": w.get("company", ""),
            "location": ", ".join(x for x in (city, region) if x),
            "current": bool(w.get("current")),
            "sm": sm, "sy": sy, "em": em, "ey": ey,
            "desc": describe(w),
        })
    return rows

TRACK_NAMES = list((data.get("tracks") or {"director": {}}).keys()) or ["director"]
tracks = {name: {"label": ((data.get("tracks") or {}).get(name) or {}).get("label", name),
                 "roles": role_rows(resolve_track(name))} for name in TRACK_NAMES}
roles = tracks[TRACK_NAMES[0]]["roles"]

linkedin = ((data.get("contact") or {}).get("links") or {}).get("linkedin", "")

contact_y = data.get("contact") or {}
name_y = contact_y.get("legal_name") or {}
loc_y = contact_y.get("location") or {}
links_y = contact_y.get("links") or {}
answers_y = data.get("application_answers") or {}
contact = {
    "first": name_y.get("first", ""),
    "last": name_y.get("last", ""),
    "preferred": name_y.get("preferred", ""),
    "full": f'{name_y.get("first","")} {name_y.get("last","")}'.strip(),
    "email": contact_y.get("email", ""),
    "phone": contact_y.get("phone", ""),
    "city": loc_y.get("city", ""),
    "state": loc_y.get("state", ""),
    "postal": loc_y.get("postal_code", ""),
    "address1": contact_y.get("address_line_1", ""),
    "location": ", ".join(x for x in [loc_y.get("city"), loc_y.get("state")] if x),
    "portfolio": links_y.get("portfolio", ""),
    "current_employer": next((w.get("company") for w in data.get("work", []) if w.get("current")), ""),
    "current_title": next((w.get("title") for w in data.get("work", []) if w.get("current")), ""),
    "how_heard": answers_y.get("how_did_you_hear", ""),
}

payload = json.dumps({"tracks": tracks, "linkedin": linkedin, "contact": contact},
                     indent=2, ensure_ascii=False)

SCRIPT = r"""// ==UserScript==
// @name         Workday autofill (__NAME__)
// @namespace    perfectpixels
// @version      1.3
// @description  Fill Workday work history and LinkedIn from resume.yaml. Generated by build_userscript.py -- do not hand-edit, edit the YAML.
// @match        *://*.myworkdayjobs.com/*
// @match        *://myworkdayjobs.com/*
// @match        *://*.myworkdaysite.com/*
// @match        *://myworkdaysite.com/*
// @match        *://*.greenhouse.io/*
// @match        *://*.lever.co/*
// @include      *://*myworkdayjobs.com/*
// @include      *://*myworkdaysite.com/*
// @include      *://*greenhouse.io/*
// @include      *://*lever.co/*
// @run-at       document-idle
// @grant        none
// ==/UserScript==
(function () {
  'use strict';

  console.log('[workday-autofill] loaded on ' + location.hostname);
  window.__workdayAutofillLoaded = true;

  const DATA = __PAYLOAD__;

  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // React ignores el.value =; it needs the native setter plus real events.
  function setVal(el, v) {
    if (!el) return false;
    const proto = el.tagName === 'TEXTAREA'
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return el.value === v;
  }

  const byId = id => document.getElementById(id);
  const emptyBlock = suffix => {
    const el = [...document.querySelectorAll('[id$="--' + suffix + '"]')].find(e => !e.value);
    return el ? el.id.match(/-(\\d+)--/)[1] : null;
  };
  const buttonNamed = txt =>
    [...document.querySelectorAll('button')].find(b => b.innerText.trim() === txt);

  // Report what IDs actually exist, so a failure names the cause.
  function idLandscape() {
    const ids = [...document.querySelectorAll('[id]')].map(e => e.id)
      .filter(id => /work|experience|educat|school|job|company|degree/i.test(id));
    return ids.length ? ids.slice(0, 8).join(', ') : '(no work/education ids on page)';
  }

  // Find the Add button that belongs to Work Experience, not to some other
  // section. Requisitions vary the heading text and more than one section can
  // offer an "Add", so anchor on the heading and take the next Add after it.
  function workAddButton() {
    const btns = [...document.querySelectorAll('button')]
      .filter(b => ['Add', 'Add Another'].includes(b.innerText.trim()));
    if (!btns.length) return null;
    const heading = [...document.querySelectorAll('h1,h2,h3,h4,h5,div,span,legend')]
      .find(e => e.children.length === 0 &&
                 /^work (experience|history)/i.test((e.textContent || '').trim()));
    if (!heading) return btns[0];
    return btns.find(b =>
      heading.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) || btns[0];
  }

  // Some requisitions pre-create an empty block; use it instead of adding another.
  async function addWorkBlock() {
    let n = emptyBlock('jobTitle');
    if (n) return n;
    const b = workAddButton();
    if (!b) return null;
    b.click();
    await sleep(1600);
    return emptyBlock('jobTitle');
  }

  // ---------- platform ----------
  const HOST = location.hostname;
  const PLATFORM =
      /myworkday(jobs|site)\.com/i.test(HOST) ? 'workday'
    : /greenhouse\.io/i.test(HOST)     ? 'greenhouse'
    : /lever\.co/i.test(HOST)          ? 'lever'
    : null;

  // Find a field by the text of its label. Greenhouse and Lever give custom
  // questions unstable ids (question_68878433) that differ per posting, so the
  // visible label is the only durable handle.
  function byLabel(re, tags) {
    tags = tags || 'input,textarea';
    for (const el of document.querySelectorAll(tags)) {
      if (el.type === 'hidden' || el.type === 'file' || el.disabled) continue;
      if (el.getAttribute('role') === 'combobox') continue;   // needs real events
      let text = '';
      if (el.id) {
        const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
        if (l) text = l.innerText;
      }
      if (!text) text = el.getAttribute('aria-label') || el.placeholder || '';
      if (!text) {
        const w = el.closest('div,fieldset,li');
        if (w) text = (w.innerText || '').trim().slice(0, 80);
      }
      if (re.test((text || '').trim())) return el;
    }
    return null;
  }

  function fillCommonQuestions(c, done) {
    const map = [
      [/linked\s*-?in/i,                      DATA.linkedin],
      [/portfolio|personal\s*(web)?site|website|url of your work/i, c.portfolio],
      [/^\s*full name|^\s*your name/i,        c.full],
      [/current (employer|company)/i,          c.current_employer],
      [/current (title|role|position)/i,       c.current_title],
      [/^\s*city|location \(city\)/i,         c.location],
    ];
    for (const [re, val] of map) {
      if (!val) continue;
      const el = byLabel(re);
      if (el && !el.value) { setVal(el, val); done.push(el.id || re.source.slice(0, 18)); }
    }
  }

  async function fillGreenhouse(report) {
    const c = DATA.contact, done = [], problems = [];
    const byId = id => document.getElementById(id);
    [['first_name', c.first], ['last_name', c.last], ['preferred_name', c.preferred],
     ['email', c.email], ['phone', c.phone]].forEach(([id, v]) => {
      const el = byId(id);
      if (el && v && !el.value) { setVal(el, v); done.push(id); }
    });
    fillCommonQuestions(c, done);
    report('Filled ' + done.length + ' fields');
    if (!done.length) problems.push('nothing matched -- this posting may use an embedded form');
    return { filled: done.length, problems,
             note: 'Greenhouse has no work-history fields. Location, country, dropdowns, uploads and Submit are yours.' };
  }

  async function fillLever(report) {
    const c = DATA.contact, done = [], problems = [];
    const q = n => document.querySelector('input[name="' + n + '"], textarea[name="' + n + '"]');
    [['name', c.full], ['email', c.email], ['phone', c.phone],
     ['org', c.current_employer],
     ['urls[LinkedIn]', DATA.linkedin], ['urls[Portfolio]', c.portfolio],
     ['urls[Website]', c.portfolio]].forEach(([n, v]) => {
      const el = q(n);
      if (el && v && !el.value) { setVal(el, v); done.push(n); }
    });
    fillCommonQuestions(c, done);
    report('Filled ' + done.length + ' fields');
    if (!done.length) problems.push('nothing matched -- Lever may have changed its field names');
    return { filled: done.length, problems,
             note: 'Lever has no work-history fields. Uploads, dropdowns and Submit are yours.' };
  }

  async function fillWorkday(report, track) {
    let filled = 0, problems = [];

    for (const r of track.roles) {
      const n = await addWorkBlock();
      if (!n) {
        problems.push('no jobTitle field after Add (' + r.company + '). IDs seen: ' + idLandscape());
        break;
      }
      const p = 'workExperience-' + n + '--';
      setVal(byId(p + 'jobTitle'), r.title);
      setVal(byId(p + 'companyName'), r.company);
      setVal(byId(p + 'location'), r.location);
      if (r.current) {
        const cb = byId(p + 'currentlyWorkHere');
        if (cb && !cb.checked) { cb.click(); await sleep(500); }
      }
      setVal(byId(p + 'startDate-dateSectionMonth-input'), r.sm);
      setVal(byId(p + 'startDate-dateSectionYear-input'), r.sy);
      if (!r.current) {
        setVal(byId(p + 'endDate-dateSectionMonth-input'), r.em);
        setVal(byId(p + 'endDate-dateSectionYear-input'), r.ey);
      }
      setVal(byId(p + 'roleDescription'), r.desc);
      filled++;
      report('Filled ' + filled + '/' + track.roles.length + ': ' + r.company);
      await sleep(350);
    }

    setVal(byId('socialNetworkAccounts--linkedInAccount'), DATA.linkedin);

    // Verify by reading back, never by trusting the writes.
    const check = [...document.querySelectorAll('[id$="--jobTitle"]')].map(e => e.value);
    const dupes = check.filter((v, i) => v && check.indexOf(v) !== i);
    if (dupes.length) problems.push('DUPLICATE entries: ' + [...new Set(dupes)].join(', '));

    return { filled, entries: check.length, problems };
  }

  const bar = document.createElement('div');
  // Bottom-LEFT on purpose: Jobright's Chrome extension pins its Autofill
  // panel over the right edge of every job page and hid this button under it
  // (23 Sep 2026). z-index at the maximum so no site chrome sits above it.
  bar.style.cssText = 'position:fixed;bottom:20px;left:20px;z-index:2147483647;font:13px/1.4 system-ui;' +
    'background:#0b5fff;color:#fff;padding:10px 14px;border-radius:8px;cursor:pointer;' +
    'box-shadow:0 4px 14px rgba(0,0,0,.25);max-width:320px';
  const LABEL = { workday: 'Fill work history',
                  greenhouse: 'Fill contact details',
                  lever: 'Fill contact details' };
  bar.textContent = LABEL[PLATFORM] || 'Fill';
  bar.title = 'Detected: ' + (PLATFORM || 'unknown platform');
  // Two resumes live in this script. Workday takes a full work history, so it
  // must ask which track before writing anything; the contact-only platforms
  // do not differ by track and skip the question.
  function chooseTrack() {
    return new Promise(resolve => {
      bar.textContent = '';
      const q = document.createElement('div');
      q.textContent = 'Which resume?';
      q.style.cssText = 'font-weight:600;margin-bottom:6px';
      bar.appendChild(q);
      for (const [key, t] of Object.entries(DATA.tracks)) {
        const b = document.createElement('button');
        b.textContent = t.label + ' (' + t.roles.length + ' roles)';
        b.style.cssText = 'display:block;width:100%;margin:4px 0;padding:6px 8px;border:0;' +
          'border-radius:6px;background:#fff;color:#0b5fff;font:inherit;cursor:pointer;text-align:left';
        b.onclick = ev => { ev.stopPropagation(); resolve([key, t]); };
        bar.appendChild(b);
      }
    });
  }

  let busy = false;
  bar.onclick = async () => {
    if (busy) return;
    busy = true;
    bar.style.cursor = 'default';
    const report = m => { bar.textContent = m; };
    try {
      let res, track = null;
      if (PLATFORM === 'workday') {
        const [key, t] = await chooseTrack();
        track = t;
        report('Filling ' + t.label + '...');
        res = await fillWorkday(report, track);
      }
      else if (PLATFORM === 'greenhouse') { report('Filling...'); res = await fillGreenhouse(report); }
      else if (PLATFORM === 'lever')      { report('Filling...'); res = await fillLever(report); }
      else { bar.style.background = '#b23c17';
             bar.textContent = 'Unrecognised platform: ' + HOST; return; }
      bar.style.background = res.problems.length ? '#b23c17' : '#1a7f37';
      if (res.problems.length) {
        bar.textContent = 'Done with problems: ' + res.problems.join(' | ');
      } else if (PLATFORM === 'workday') {
        bar.textContent = 'Filled ' + res.filled + ' roles (' + track.label +
          ') + LinkedIn. Education, skills, uploads and Submit are yours.';
      } else {
        bar.textContent = 'Filled ' + res.filled + ' fields. ' + res.note;
      }
    } catch (e) {
      bar.style.background = '#b23c17';
      bar.textContent = 'Error: ' + e.message;
    }
  };
  if (PLATFORM) document.body.appendChild(bar);
})();
"""

out = OUT_DIR / "workday-autofill.user.js"
out.write_text(SCRIPT.replace("__PAYLOAD__", payload).replace("__NAME__", contact["full"] or "job hitlist"), encoding="utf-8")
print(f"wrote {out}")
for name, t in tracks.items(): print(f"  {name:<9} {len(t['roles'])} roles  ({t['label']})")
print("  education intentionally excluded")
print(f"  {out.stat().st_size:,} bytes")

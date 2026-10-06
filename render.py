#!/usr/bin/env python3
"""Render data/scored.json (+ Connections.csv + data/enrich.json) -> hitlist.html"""
import html, json, pathlib, urllib.parse
from datetime import datetime
import yaml, network

HERE = pathlib.Path(__file__).parent
CFG = yaml.safe_load((HERE / "config.yaml").read_text())
rows = json.loads((HERE / "data/scored.json").read_text())
enrich = json.loads((HERE / "data/enrich.json").read_text()) if (HERE / "data/enrich.json").exists() else {}
conns = network.load()
decisions = json.loads((HERE / "data/decisions.json").read_text()) if (HERE / "data/decisions.json").exists() else {}
TRACKS = CFG["tracks"]
def band_for(score): return "strong" if score >= CFG["bands"]["strong"] else "good" if score >= CFG["bands"]["good"] else "weak"
rows = [r for r in rows if max(r.get("track_scores", {}).values(), default=-999) >= CFG["bands"]["show_min"]]

def e(s): return html.escape(str(s or ""))
def people_search(company, q="recruiter"):
    return "https://www.linkedin.com/search/results/people/?" + urllib.parse.urlencode({"keywords": f"{q} {company}", "origin": "GLOBAL_SEARCH_HEADER"})

out = [f"""<meta charset="utf-8"><title>Job Hitlist</title>
<style>
:root{{--ink:#1d1d1f;--mute:#6e6e73;--line:#e5e5ea;--strong:#0a7c3e;--good:#b7791f;--bg:#fff}}
body{{font:14px/1.45 -apple-system,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg);margin:0;padding:24px}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:var(--mute);margin-bottom:18px}}
table{{border-collapse:collapse;width:100%}} th,td{{text-align:left;vertical-align:top;padding:9px 10px;border-bottom:1px solid var(--line)}}
th{{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute);position:sticky;top:0;background:var(--bg)}}
.band{{display:inline-block;font-weight:600;font-size:12px;padding:2px 7px;border-radius:10px;color:#fff}}
.strong{{background:var(--strong)}} .good{{background:var(--good)}} .weak{{background:#999}}
.title a{{font-weight:600;color:#0b57d0;text-decoration:none}} .co{{color:var(--mute)}}
.fresh{{color:var(--strong);font-weight:600}} .old{{color:#c0392b}}
.tag{{display:inline-block;font-size:11px;background:#f2f2f7;border-radius:4px;padding:1px 6px;margin:1px 3px 1px 0;color:#3a3a3c}}
.who{{font-size:13px}} .who a{{color:#0b57d0;text-decoration:none}} .none{{color:#aaa}}
.wrap{{overflow-x:auto}}
.tabs{{display:flex;gap:0;margin:0 0 14px;border-bottom:2px solid var(--line)}}
.tab{{font:inherit;font-size:14px;font-weight:600;padding:8px 16px;border:0;border-bottom:2px solid transparent;margin-bottom:-2px;background:none;color:var(--mute);cursor:pointer;white-space:nowrap}}
.tab.on{{color:var(--ink);border-bottom-color:var(--ink)}} .tab b{{font-weight:500;opacity:.6;margin-left:4px}}
.bar{{display:flex;gap:8px;align-items:center;margin:0 0 12px}} .grow{{flex:1}}
.chip{{white-space:nowrap;font:inherit;font-size:13px;padding:5px 11px;border:1px solid var(--line);border-radius:14px;background:#fff;cursor:pointer;color:var(--ink)}}
.chip.on{{background:var(--ink);color:#fff;border-color:var(--ink)}} .sortlbl{{font-size:12px;color:var(--mute);margin-left:8px}} .chip b{{font-weight:600;margin-left:4px;opacity:.7}}
.acts{{white-space:nowrap}} .acts button{{font:inherit;font-size:12px;padding:3px 8px;margin:0 3px 3px 0;border:1px solid var(--line);border-radius:6px;background:#fff;cursor:pointer;color:var(--ink)}}
.acts button:hover{{border-color:var(--ink)}}
tr[data-s="applied"] .acts .b-applied,tr[data-s="follow"] .acts .b-follow,tr[data-s="notfit"] .acts .b-notfit{{background:var(--ink);color:#fff;border-color:var(--ink)}}
tr[data-s="notfit"]{{opacity:.45}} tr[data-s="applied"] td.title a{{color:var(--strong)}} tr[data-s="follow"]{{background:#fffbea}}
tr.hide{{display:none}}
</style>
<h1>Job Hitlist</h1>
<div class="sub">{len(rows)} roles at or above {CFG['bands']['show_min']} on at least one track &middot; rendered {datetime.now():%a %d %b %Y %H:%M} &middot; {len(conns)} connections loaded{' (no Connections.csv yet)' if not conns else ''}</div>
<div class="tabs">""" + "".join(f"<button class='tab' data-t='{tk}'>{e(tv['label'])} <b id='n-t-{tk}'></b></button>" for tk, tv in TRACKS.items()) + f"""</div>
<div class="bar">
  <button class="chip on" data-f="open">Open</button>
  <button class="chip" data-f="new">Unreviewed <b id="n-new">0</b></button>
  <button class="chip" data-f="follow">Follow up <b id="n-follow">0</b></button>
  <button class="chip" data-f="applied">Applied <b id="n-applied">0</b></button>
  <button class="chip" data-f="notfit">Not a fit <b id="n-notfit">0</b></button>
  <span class="grow"></span>
  <button class="chip" id="refresh" title="LinkedIn past 24h + alert mail + boards, ~5 min">Refresh</button>
  <button class="chip" id="refresh-full" title="LinkedIn past week, ~20 min">Full</button>
  <span id="rstatus" class="sortlbl"></span>
  <span class="sortlbl">Sort</span>
  <button class="chip on" data-sort="score">Score</button>
  <button class="chip" data-sort="days">Newest</button>
  <button class="chip" id="export">Export decisions</button>
</div>
<div class="wrap"><table><tr><th>Score</th><th>Role</th><th>Posted</th><th>Signals</th><th>People you know</th><th>Recruiter</th></tr>"""]

for r in rows:
    d = r["days"]; fresh = "fresh" if d is not None and d <= 3 else ("old" if d is not None and d > 10 else "")
    posted = f"<span class='{fresh}'>{d}d ago</span>" if d is not None else "?"
    if r.get("applicants"): posted += f"<br><span class='co'>{e(r['applicants'])}</span>"
    tags = ["<span class='tiertag'></span>"] + r["notes"]
    if r["ai_hits"] >= 2: tags.append(f"AI x{r['ai_hits']}")
    if r.get("seniority_level"): tags.append(r["seniority_level"])
    if r.get("also_in"): tags.append("also: " + ", ".join(r["also_in"][:3]))
    if len(r.get("seen_on", [])) > 1: tags.append("seen on " + ", ".join(r["seen_on"]))
    if r.get("needs_company") and not r.get("company"): tags.append("company unknown (Ladders omitted it)")
    if r.get("seen_on") in (["Ladders"], ["Careerbuilder"]) and len(r.get("seen_on", [])) == 1:
        src = r["seen_on"][0]
        if r.get("linkedin_found") is False: tags.append(f"{src} only: not found on LinkedIn")
        elif not r.get("verified_linkedin"): tags.append(f"{src} only: unverified")
    if r.get("jobright_match"): tags.append(f"Jobright {r['jobright_match']}%")
    if r.get("jobright_network"): tags.append(r["jobright_network"])
    if r.get("comp"): tags.append(r["comp"])
    kn = network.matches(conns, r.get("company"))
    who = "<br>".join(f"<a href='{e(c['url'])}' target=_blank>{e(c['name'])}</a> <span class='co'>{e(c['position'])}</span>" for c in kn[:6]) or "<span class='none'>—</span>"
    if len(kn) > 6: who += f"<br><span class='co'>+{len(kn)-6} more</span>"
    en = {}
    for jid in r.get("all_ids", [r["id"]]):          # recruiters may be keyed by either copy's id
        for key, val in enrich.get(jid, {}).items():
            if key == "recruiters": en.setdefault("recruiters", []).extend(val)
            else: en[key] = val
    rec = "<br>".join(f"<a href='{e(p.get('url'))}' target=_blank>{e(p.get('name'))}</a> <span class='co'>{e(p.get('title'))}</span>" for p in en.get("recruiters", []))
    rec += ("<br>" if rec else "") + f"<a href='{e(people_search(r.get('company')))}' target=_blank class='co'>search recruiters →</a>"
    if en.get("jobright"): tags.append("on Jobright")
    st = ""
    for k in r.get("all_ids", [r["id"]]) + ["g:" + r.get("gkey", "")]:
        if decisions.get(k, {}).get("status"): st = decisions[k]["status"]; break
    ts = r.get("track_scores", {})
    tattrs = " ".join(f"data-sc-{k}='{v}' data-b-{k}='{band_for(v)}' data-tier-{k}='{e(r.get('track_tier',{}).get(k,''))}'" for k, v in ts.items())
    out.append(f"""<tr data-id='{e(r['id'])}' data-ids='{e("|".join(r.get("all_ids", [r["id"]])))}' data-g='{e("g:" + r.get("gkey", ""))}' data-s='{e(st)}' data-days='{r['days'] if r['days'] is not None else 999}' {tattrs}><td><span class='band {r['band']}'>{r['score']}</span>
<div class='acts'><button class='b-applied' data-s='applied'>Applied</button><button class='b-follow' data-s='follow'>Follow up</button><button class='b-notfit' data-s='notfit'>Not a fit</button></div></td>
<td class='title'><a href='{e(r['url'])}' target=_blank>{e(r['title'])}</a><br><span class='co'>{e(r['company'])} · {e(r['location'])}</span></td>
<td>{posted}</td><td>{''.join(f"<span class='tag'>{t if t.startswith('<span') else e(t)}</span>" for t in tags)}</td>
<td class='who'>{who}</td><td class='who'>{rec}</td></tr>""")
out.append("""</table></div>
<script>
(function(){
  var KEY='hitlist.decisions', view='open', TKEY='hitlist.track', SKEY='hitlist.sort';
  var sortBy = (function(){ try { return localStorage.getItem(SKEY) || 'score'; } catch(e){ return 'score'; } })();
  var TRACKS=__TRACKS__, SHOW_MIN=__SHOW_MIN__;
  var track = (function(){ try { return localStorage.getItem(TKEY) || Object.keys(TRACKS)[0]; } catch(e){ return Object.keys(TRACKS)[0]; } })();
  if (!TRACKS[track]) track = Object.keys(TRACKS)[0];
  // Each row carries a score per track; the active tab decides which one
  // shows, whether the row is in range, and the sort order.
  function applyTrack(){
    var tbody=document.querySelector('table'); var rows=[].slice.call(document.querySelectorAll('tr[data-id]'));
    rows.forEach(function(tr){
      var sc=tr.getAttribute('data-sc-'+track); tr.dataset.ontrack = (sc!==null && +sc>=SHOW_MIN) ? '1' : '';
      var badge=tr.querySelector('.band'); if(sc!==null){ badge.textContent=sc; badge.className='band '+tr.getAttribute('data-b-'+track); }
      var tt=tr.querySelector('.tiertag'); if(tt) tt.textContent='tier: '+(tr.getAttribute('data-tier-'+track)||'');
    });
    var sc = function(tr){ return +(tr.getAttribute('data-sc-'+track)||-999); };
    rows.sort(function(a,b){
      if (sortBy==='days') { var d=(+a.dataset.days)-(+b.dataset.days); if (d) return d; }   // newest first, score breaks ties
      return sc(b)-sc(a);
    }).forEach(function(tr){ tbody.appendChild(tr); });
    document.querySelectorAll('.chip[data-sort]').forEach(function(c){ c.classList.toggle('on', c.dataset.sort===sortBy); });
    Object.keys(TRACKS).forEach(function(k){
      var n=rows.filter(function(tr){ var v=tr.getAttribute('data-sc-'+k); return v!==null && +v>=SHOW_MIN && (d[tr.dataset.id]||{}).status!=='notfit'; }).length;
      var el=document.getElementById('n-t-'+k); if(el) el.textContent=n;
    });
    document.querySelectorAll('.tab').forEach(function(t){ t.classList.toggle('on', t.dataset.t===track); });
  }
  var d={}; try{ d=JSON.parse(localStorage.getItem(KEY)||'{}'); }catch(e){}
  // A decision can live under any id the group has ever had, or under the
  // group key. Resolve it to the current primary id so reposts keep marks.
  function keysOf(tr){ return (tr.dataset.ids||tr.dataset.id).split('|').concat([tr.dataset.g]); }
  document.querySelectorAll('tr[data-id]').forEach(function(tr){
    var id=tr.dataset.id;
    if(!d[id]){ var k=keysOf(tr).find(function(k){ return d[k] && d[k].status; }); if(k) d[id]=d[k]; }
    if(!d[id] && tr.dataset.s) d[id]={status:tr.dataset.s, at:''};
    if(d[id] && tr.dataset.g && !d[tr.dataset.g]) d[tr.dataset.g]=d[id];
  });
  var REMOTE = window.REMOTE || null;                       // hosted copy: presigned S3 URLs baked in by publish.py
  var SERVED = !!REMOTE || location.protocol==='http:';
  function save(){ try{ localStorage.setItem(KEY, JSON.stringify(d)); }catch(e){}
    if(REMOTE){ fetch(REMOTE.decisionsPut,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}).catch(function(){}); }
    else if(SERVED){ fetch('/decisions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}).catch(function(){}); } }
  // Served copy: merge decisions saved on disk (by this page or by an export
  // from the old file:// copy), so marks survive a browser reset or a move.
  if(SERVED){ fetch('/decisions.json',{cache:'no-store'}).then(function(r){return r.json();}).then(function(disk){
    var changed=false; Object.keys(disk||{}).forEach(function(k){ if(!d[k]){ d[k]=disk[k]; changed=true; } });
    if(changed){ try{ localStorage.setItem(KEY, JSON.stringify(d)); }catch(e){} paint(); }
  }).catch(function(){}); }
  var rs=document.getElementById('rstatus');
  function pollStatus(){
    if(REMOTE){ fetch('/status.json',{cache:'no-store'}).then(function(r){return r.json();}).then(function(st){
        if(st.state==='requested'){ rs.textContent='Refresh requested, waiting for the Mac…'; setTimeout(pollStatus, 5000); }
        else if(st.state==='running'){ rs.textContent='Refreshing… '+(st.last||''); setTimeout(pollStatus, 5000); }
        else if(st.state==='done' && st.at && !sessionStorage.getItem('reloaded-'+st.at)){ sessionStorage.setItem('reloaded-'+st.at,'1'); rs.textContent='Done, reloading…'; setTimeout(function(){ location.reload(); }, 800); }
        else rs.textContent='';
      }).catch(function(){ rs.textContent=''; }); return; }
    fetch('/status').then(function(r){return r.json();}).then(function(st){
    if(st.running){ rs.textContent='Refreshing… '+(st.last||''); setTimeout(pollStatus, 2500); }
    else if(st.exit!==null && st.started && Date.now()/1000-st.started<600 && !sessionStorage.getItem('reloaded-'+st.started)){
      sessionStorage.setItem('reloaded-'+st.started,'1'); rs.textContent='Done, reloading…'; setTimeout(function(){ location.reload(); }, 800); }
    else rs.textContent='';
  }).catch(function(){ rs.textContent=''; }); }
  function startRefresh(window){ if(!SERVED){ rs.textContent='Open http://localhost:8766/ to refresh'; return; }
    if(REMOTE){ fetch(REMOTE.refreshPut,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({window:window,at:new Date().toISOString()})})
      .then(function(){ rs.textContent='Refresh requested, waiting for the Mac…'; setTimeout(pollStatus, 5000); })
      .catch(function(){ rs.textContent='Could not reach S3 (presigned link expired? republish from the Mac)'; }); return; }
    fetch('/refresh?window='+window,{method:'POST'}).then(function(r){return r.json();}).then(function(j){ rs.textContent=j.error||'Starting…'; setTimeout(pollStatus, 1500); }); }
  if(SERVED) pollStatus();
  function paint(){
    var n={follow:0,applied:0,notfit:0,new:0};
    document.querySelectorAll('tr[data-id]').forEach(function(tr){
      var s=(d[tr.dataset.id]||{}).status||''; tr.dataset.s=s; if(n[s]!==undefined) n[s]++;
      if(!s && tr.dataset.ontrack==='1') n.new++;
      var show = (view==='open' ? s!=='notfit' : view==='new' ? !s : s===view) && tr.dataset.ontrack==='1';
      tr.classList.toggle('hide', !show);
    });
    ['follow','applied','notfit','new'].forEach(function(k){ document.getElementById('n-'+k).textContent=n[k]; });
    document.querySelectorAll('.chip[data-f]').forEach(function(c){ c.classList.toggle('on', c.dataset.f===view); });
  }
  document.addEventListener('click', function(ev){
    var b=ev.target.closest('.acts button'); if(b){
      var tr=b.closest('tr'), id=tr.dataset.id, s=b.dataset.s, g=tr.dataset.g;
      if((d[id]||{}).status===s){ delete d[id]; if(g) delete d[g]; }
      else { var v={status:s, at:new Date().toISOString().slice(0,10)}; d[id]=v; if(g) d[g]=v; }
      save(); paint(); return;
    }
    var c=ev.target.closest('.chip[data-f]'); if(c){ view=c.dataset.f; paint(); return; }
    var sb=ev.target.closest('.chip[data-sort]'); if(sb){ sortBy=sb.dataset.sort; try{ localStorage.setItem(SKEY, sortBy); }catch(e){} applyTrack(); paint(); return; }
    var tb=ev.target.closest('.tab'); if(tb){ track=tb.dataset.t; try{ localStorage.setItem(TKEY, track); }catch(e){} applyTrack(); paint(); return; }
    if(ev.target.closest('#refresh')){ startRefresh('r86400'); return; }
    if(ev.target.closest('#refresh-full')){ startRefresh('r604800'); return; }
    if(ev.target.closest('#export')){
      var blob=new Blob([JSON.stringify(d,null,1)],{type:'application/json'});
      var a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='decisions.json'; a.click();
    }
  });
  applyTrack(); paint();
})();
</script>""".replace("__TRACKS__", json.dumps({k: v["label"] for k, v in TRACKS.items()})).replace("__SHOW_MIN__", str(CFG["bands"]["show_min"])))
(HERE / "hitlist.html").write_text("\n".join(out), encoding="utf-8")
print(f"wrote hitlist.html with {len(rows)} rows")

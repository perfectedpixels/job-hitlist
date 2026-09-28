#!/usr/bin/env python3
"""Local server for the hitlist: serves hitlist.html and adds two things a
static file cannot do.

    POST /refresh?window=r86400   run daily.sh (24h window; r604800 = week)
    GET  /status                  {running, last, exit, started}
    POST /decisions               save the page's Applied/Follow-up/Not-a-fit
                                  marks to data/decisions.json
    GET  /decisions.json          read them back

Bound to 127.0.0.1 only. Kept alive by the LaunchAgent
com.perfectpixels.jobhitlist-server. Open http://localhost:8766/
"""
import json, os, pathlib, subprocess, sys, threading, time
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = pathlib.Path(__file__).parent.resolve()
DATA = HERE / "data"; DATA.mkdir(exist_ok=True)
LOG = DATA / "refresh.log"
PORT = 8766
state = {"proc": None, "started": None, "exit": None, "window": None}
lock = threading.Lock()

def run_refresh(window):
    env = dict(os.environ, NO_OPEN="1", PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin")
    with LOG.open("w") as f:
        p = subprocess.Popen(["/bin/sh", str(HERE / "daily.sh"), window], cwd=HERE, stdout=f, stderr=subprocess.STDOUT, env=env)
    state.update(proc=p, started=time.time(), exit=None, window=window)
    p.wait(); state["exit"] = p.returncode

# ---- cloud sync: the hosted copy writes refresh.request and decisions.json
# straight to S3 (presigned PUTs); this loop is the Mac's side of that.
CLOUD = json.loads((DATA / "cloud.json").read_text()) if (DATA / "cloud.json").exists() else None
def cloud_loop():
    import boto3
    s3 = boto3.client("s3", region_name="us-east-1"); B = CLOUD["bucket"]
    last_req = None
    def put_status(st):
        try: s3.put_object(Bucket=B, Key="status.json", Body=json.dumps(st).encode(), ContentType="application/json", CacheControl="no-store")
        except Exception: pass
    while True:
        try:
            # 1. decisions: union of local and remote, newest mark wins
            local_f = DATA / "decisions.json"; local = json.loads(local_f.read_text()) if local_f.exists() else {}
            try: remote = json.loads(s3.get_object(Bucket=B, Key="decisions.json")["Body"].read() or b"{}")
            except s3.exceptions.NoSuchKey: remote = {}
            merged = dict(local)
            for k, v in remote.items():
                if k not in merged or (v.get("at", "") > merged[k].get("at", "")): merged[k] = v
            if merged != local: local_f.write_text(json.dumps(merged, indent=1))
            if merged != remote: s3.put_object(Bucket=B, Key="decisions.json", Body=json.dumps(merged, indent=1).encode(), ContentType="application/json", CacheControl="no-store")
            # 2. refresh requests
            try:
                obj = s3.get_object(Bucket=B, Key="refresh.request"); req = json.loads(obj["Body"].read() or b"{}"); stamp = obj["LastModified"].isoformat()
            except s3.exceptions.NoSuchKey: req, stamp = None, None
            if req and stamp != last_req and not (state["proc"] and state["proc"].poll() is None):
                last_req = stamp
                window = req.get("window") if req.get("window") in ("r86400", "r604800") else "r86400"
                put_status({"state": "running", "at": stamp, "last": "starting"})
                t = threading.Thread(target=run_refresh, args=(window,), daemon=True); t.start()
                while t.is_alive():
                    last = ""
                    if LOG.exists():
                        lines = [l for l in LOG.read_text(errors="ignore").splitlines() if l.strip()]; last = lines[-1][:100] if lines else ""
                    put_status({"state": "running", "at": stamp, "last": last}); time.sleep(5)
                s3.delete_object(Bucket=B, Key="refresh.request")
                subprocess.run([sys.executable, str(HERE / "publish.py")], cwd=HERE, timeout=300)
                put_status({"state": "done", "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        except Exception as e:
            (DATA / "server.log").open("a").write(f"cloud_loop: {type(e).__name__}: {e}\n")
        time.sleep(30)

class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=str(HERE), **k)
    def log_message(self, *a): pass
    def _json(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def end_headers(self):
        self.send_header("Cache-Control", "no-store"); super().end_headers()
    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", ""): self.path = "/hitlist.html"
        if u.path == "/status":
            p = state["proc"]; running = bool(p and p.poll() is None)
            last = ""
            if LOG.exists():
                lines = [l for l in LOG.read_text(errors="ignore").splitlines() if l.strip()]
                last = lines[-1][:120] if lines else ""
            return self._json(200, {"running": running, "last": last, "exit": state["exit"], "started": state["started"], "window": state["window"]})
        if u.path == "/decisions.json":
            f = DATA / "decisions.json"; return self._json(200, json.loads(f.read_text()) if f.exists() else {})
        return super().do_GET()
    def do_POST(self):
        u = urlparse(self.path); n = int(self.headers.get("Content-Length") or 0); body = self.rfile.read(n) if n else b""
        if u.path == "/refresh":
            with lock:
                p = state["proc"]
                if p and p.poll() is None: return self._json(409, {"error": "already running"})
                window = (parse_qs(u.query).get("window") or ["r86400"])[0]
                if window not in ("r86400", "r604800"): window = "r86400"
                threading.Thread(target=run_refresh, args=(window,), daemon=True).start()
            return self._json(202, {"started": True, "window": window})
        if u.path == "/decisions":
            try: d = json.loads(body or b"{}"); assert isinstance(d, dict)
            except Exception: return self._json(400, {"error": "bad json"})
            (DATA / "decisions.json").write_text(json.dumps(d, indent=1)); return self._json(200, {"saved": len(d)})
        return self._json(404, {"error": "no such endpoint"})

if __name__ == "__main__":
    if CLOUD: threading.Thread(target=cloud_loop, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()

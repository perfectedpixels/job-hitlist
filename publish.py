#!/usr/bin/env python3
"""Publish the hitlist to S3 behind CloudFront.

    ./run publish.py

Uploads hitlist.html (with presigned PUT URLs baked in so the hosted page can
save marks and request a refresh without any server), decisions.json and
status.json. Presigned URLs last 7 days; every publish renews them, and the
page is republished after every run, so they only go stale if the Mac stops
running the pipeline for a week.
"""
import json, pathlib, re, sys
from datetime import datetime, timezone
import boto3

HERE = pathlib.Path(__file__).parent
CLOUD = json.loads((HERE / "data/cloud.json").read_text())
B = CLOUD["bucket"]
s3 = boto3.client("s3", region_name="us-east-1")

def presign_put(key, content_type):
    return s3.generate_presigned_url("put_object", Params={"Bucket": B, "Key": key, "ContentType": content_type},
                                     ExpiresIn=7 * 24 * 3600, HttpMethod="PUT")

def main(status=None):
    html = (HERE / "hitlist.html").read_text(encoding="utf-8")
    remote = {"decisionsPut": presign_put("decisions.json", "application/json"),
              "refreshPut": presign_put("refresh.request", "application/json"),
              "publishedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    tag = "<script>window.REMOTE=" + json.dumps(remote) + ";</script>"
    html = re.sub(r"<script>window\.REMOTE=.*?</script>", "", html, flags=re.S)
    html = html.replace("<style>", tag + "\n<style>", 1)
    s3.put_object(Bucket=B, Key="hitlist.html", Body=html.encode("utf-8"), ContentType="text/html; charset=utf-8", CacheControl="no-store")
    dec = HERE / "data/decisions.json"
    s3.put_object(Bucket=B, Key="decisions.json", Body=(dec.read_text() if dec.exists() else "{}").encode(), ContentType="application/json", CacheControl="no-store")
    st = status or {"state": "idle", "at": remote["publishedAt"]}
    s3.put_object(Bucket=B, Key="status.json", Body=json.dumps(st).encode(), ContentType="application/json", CacheControl="no-store")
    print(f"published hitlist.html ({len(html):,} chars), decisions.json, status.json -> s3://{B}")

if __name__ == "__main__":
    main()

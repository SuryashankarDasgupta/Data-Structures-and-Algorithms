"""Titans Told reach (thumbnail impressions + CTR per video) from the YouTube Reporting API.
Owner decision 15 Nov 2026 (copied from how BMP does it; Titans Told's own OAuth app and token, never BMP's).
Env (never print them): TT_YT_RPT_CLIENT_ID, TT_YT_RPT_CLIENT_SECRET, TT_YT_RPT_REFRESH_TOKEN
(scope yt-analytics.readonly, consented on the Titans Told brand channel).

usage:
  python3 tt_reach.py check            # token works + which channel it reads (views of the last 14 days)
  python3 tt_reach.py setup            # create the channel_reach_basic_a1 job once (no duplicates); prints job id
  python3 tt_reach.py pull [--days N] [--json reach.json]
      downloads every available daily report (first files ~24-48 h after the job is created, ~2-day lag,
      kept ~60 days), aggregates per video: impressions (sum) and CTR (impression-weighted), prints a table.
Exit 3 = no reports yet (use the Studio "CTR report" in Drive instead)."""
import csv, io, json, os, sys, urllib.parse, urllib.request
from datetime import date, timedelta

REPORT = "channel_reach_basic_a1"


def env(k):
    v = os.environ.get(k)
    if not v:
        sys.exit(f"{k} is not set in this environment")
    return v


def token():
    data = urllib.parse.urlencode({"client_id": env("TT_YT_RPT_CLIENT_ID"), "client_secret": env("TT_YT_RPT_CLIENT_SECRET"),
                                   "refresh_token": env("TT_YT_RPT_REFRESH_TOKEN"), "grant_type": "refresh_token"}).encode()
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=data), timeout=60))
    except urllib.error.HTTPError as e:
        sys.exit("token refresh failed: " + e.read().decode()[:200])
    return d["access_token"]


def api(method, url, tok, body=None, raw=False):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            b = r.read()
            return 200, (b if raw else (json.loads(b) if b.strip() else {}))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="ignore")[:400]


def jobs(tok):
    c, d = api("GET", "https://youtubereporting.googleapis.com/v1/jobs", tok)
    if c != 200:
        sys.exit(f"jobs.list failed: {c} {d}")
    return [j for j in d.get("jobs", []) if j.get("reportTypeId") == REPORT]


def cmd_check():
    tok = token()
    end = date.today(); start = end - timedelta(days=14)
    q = urllib.parse.urlencode({"ids": "channel==MINE", "startDate": start.isoformat(), "endDate": end.isoformat(),
                                "metrics": "views", "dimensions": "video", "sort": "-views", "maxResults": "5"})
    c, d = api("GET", "https://youtubeanalytics.googleapis.com/v2/reports?" + q, tok)
    print("analytics check:", c, d.get("rows") if isinstance(d, dict) else d)
    c, d = api("GET", "https://youtubereporting.googleapis.com/v1/reportTypes", tok)
    ok = c == 200 and any(t.get("id") == REPORT for t in d.get("reportTypes", []))
    print("reporting API:", c, f"{REPORT} available" if ok else d)


def cmd_setup():
    tok = token(); existing = jobs(tok)
    if existing:
        print("job already exists:", existing[0]["id"], existing[0].get("createTime")); return
    c, d = api("POST", "https://youtubereporting.googleapis.com/v1/jobs", tok, {"reportTypeId": REPORT, "name": "Titans Told reach"})
    if c != 200:
        sys.exit(f"job create failed: {c} {d}")
    print("job created:", d["id"], d.get("createTime"), "| first daily files usually 24-48 h later")


def cmd_pull():
    tok = token(); js = jobs(tok)
    if not js:
        sys.exit("no reach job yet: run setup")
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 0
    since = (date.today() - timedelta(days=days)).isoformat() if days else ""
    reports, url = [], f"https://youtubereporting.googleapis.com/v1/jobs/{js[0]['id']}/reports"
    while url:
        c, d = api("GET", url, tok)
        if c != 200:
            sys.exit(f"reports.list failed: {c} {d}")
        reports += d.get("reports", [])
        url = (f"https://youtubereporting.googleapis.com/v1/jobs/{js[0]['id']}/reports?pageToken={d['nextPageToken']}"
               if d.get("nextPageToken") else None)
    if not reports:
        print("no reach reports yet (first files ~24-48 h after the job was created)"); sys.exit(3)
    agg = {}
    for rp in reports:
        if since and rp.get("startTime", "")[:10] < since:
            continue
        c, b = api("GET", rp["downloadUrl"], tok, raw=True)
        if c != 200:
            print("download failed", rp.get("startTime"), c); continue
        for row in csv.DictReader(io.StringIO(b.decode("utf-8", "ignore"))):
            vid = row.get("video_id") or ""
            if not vid:
                continue
            imp = float(row.get("video_thumbnail_impressions") or 0)
            ctr = float(row.get("video_thumbnail_impressions_ctr") or 0)
            ctr = ctr / 100 if ctr > 1 else ctr
            a = agg.setdefault(vid, {"impressions": 0.0, "clicks": 0.0, "days": set()})
            a["impressions"] += imp; a["clicks"] += imp * ctr; a["days"].add(row.get("date", ""))
    out = {v: {"impressions": int(a["impressions"]), "ctr_pct": round(100 * a["clicks"] / a["impressions"], 2) if a["impressions"] else 0.0,
               "days": len(a["days"])} for v, a in agg.items()}
    for v, a in sorted(out.items(), key=lambda x: -x[1]["impressions"]):
        print(f"{v}  impressions {a['impressions']:>7}  CTR {a['ctr_pct']:>5}%  days {a['days']}")
    if "--json" in sys.argv:
        json.dump(out, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=1)


if __name__ == "__main__":
    {"check": cmd_check, "setup": cmd_setup, "pull": cmd_pull}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()

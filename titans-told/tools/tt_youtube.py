#!/usr/bin/env python3
"""Titans Told YouTube tool (Data API v3). Uses ONLY TT_YT_CLIENT_ID / TT_YT_CLIENT_SECRET / TT_YT_REFRESH_TOKEN.
Never prints secrets. Never uses BMP's YT_* variables.

  tt_youtube.py check                         -> which env vars exist + channel the token belongs to
  tt_youtube.py device-start                  -> starts OAuth device flow, prints user code + URL, saves device state
  tt_youtube.py device-poll                   -> polls; on success writes refresh token to ./tt_refresh_token.txt (chmod 600)
                                                 (owner then stores it as TT_YT_REFRESH_TOKEN; file is deleted after)
  tt_youtube.py update meta.json VIDEO_ID     -> SEO refresh of title/description/tags (+ playlist description)
  tt_youtube.py upload meta.json              -> resumable upload, scheduled (private + publishAt), thumbnail, captions, playlist
     meta.json: {"file","title","description","tags":[],"categoryId":"28","publishAt":"2026-11-10T14:00:00Z",
                 "thumbnail":"thumb.png","captions":"captions.srt","playlist":"Company Histories"}
  tt_youtube.py status VIDEO_ID               -> privacy/publishAt/processing
"""
import json, os, sys, time, urllib.parse, urllib.request

CHANNEL_ID = "UCP-awmDwPon4WBDW4898Hlw"  # Titans Told
SCOPES = "https://www.googleapis.com/auth/youtube"  # device flow allows only youtube / youtube.readonly


def env(n):
    v = os.environ.get(n)
    if not v:
        sys.exit(f"missing env var {n}")
    return v


def post_form(url, data):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode())
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"{}")


def token():
    d = post_form("https://oauth2.googleapis.com/token", {
        "client_id": env("TT_YT_CLIENT_ID"), "client_secret": env("TT_YT_CLIENT_SECRET"),
        "refresh_token": env("TT_YT_REFRESH_TOKEN"), "grant_type": "refresh_token"})
    if "access_token" not in d:
        sys.exit("token refresh failed: " + d.get("error", "?") + " " + d.get("error_description", ""))
    return d["access_token"]


def api(method, url, tok, body=None, ctype="application/json", raw=None, headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Authorization": "Bearer " + tok}
    if data is not None:
        h["Content-Type"] = ctype
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            txt = r.read()
            return r.status, (json.loads(txt) if txt.strip().startswith(b"{") else txt), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="ignore")[:800], e.headers


def check():
    for n in ("TT_YT_CLIENT_ID", "TT_YT_CLIENT_SECRET", "TT_YT_REFRESH_TOKEN"):
        print(n, "present" if os.environ.get(n) else "MISSING")
    if os.environ.get("TT_YT_REFRESH_TOKEN"):
        tok = token()
        c, d, _ = api("GET", "https://youtube.googleapis.com/youtube/v3/channels?part=snippet&mine=true", tok)
        for it in (d.get("items", []) if isinstance(d, dict) else []):
            ok = "OK" if it["id"] == CHANNEL_ID else "WRONG CHANNEL"
            print("token channel:", it["id"], it["snippet"]["title"], ok)


def device_start():
    d = post_form("https://oauth2.googleapis.com/device/code", {"client_id": env("TT_YT_CLIENT_ID"), "scope": SCOPES})
    if "device_code" not in d:
        sys.exit("device flow failed: " + json.dumps(d))
    json.dump(d, open(".tt_device.json", "w"))
    os.chmod(".tt_device.json", 0o600)
    print("Go to:", d["verification_url"], " code:", d["user_code"], " (expires in", d["expires_in"] // 60, "min)")


def device_poll():
    d = json.load(open(".tt_device.json"))
    end = time.time() + d["expires_in"]
    while time.time() < end:
        r = post_form("https://oauth2.googleapis.com/token", {
            "client_id": env("TT_YT_CLIENT_ID"), "client_secret": env("TT_YT_CLIENT_SECRET"),
            "device_code": d["device_code"], "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        if "refresh_token" in r:
            open("tt_refresh_token.txt", "w").write(r["refresh_token"])
            os.chmod("tt_refresh_token.txt", 0o600)
            os.remove(".tt_device.json")
            tok = r["access_token"]
            c, ch, _ = api("GET", "https://youtube.googleapis.com/youtube/v3/channels?part=snippet&mine=true", tok)
            for it in ch.get("items", []):
                print("authorized channel:", it["id"], it["snippet"]["title"], "OK" if it["id"] == CHANNEL_ID else "WRONG CHANNEL")
            print("refresh token saved to tt_refresh_token.txt (not printed)")
            return
        if r.get("error") not in ("authorization_pending", "slow_down"):
            sys.exit("device poll failed: " + json.dumps(r))
        time.sleep(d.get("interval", 5) + (5 if r.get("error") == "slow_down" else 0))
    sys.exit("device code expired")


def upload(meta_path):
    m = json.load(open(meta_path))
    root = os.path.dirname(os.path.abspath(meta_path))
    P = lambda p: p if os.path.isabs(p) else os.path.join(root, p)
    tok = token()
    c, ch, _ = api("GET", "https://youtube.googleapis.com/youtube/v3/channels?part=id&mine=true", tok)
    if not isinstance(ch, dict) or not any(i["id"] == CHANNEL_ID for i in ch.get("items", [])):
        sys.exit("token is not for the Titans Told channel; refusing to upload")
    body = {"snippet": {"title": m["title"][:100], "description": m["description"][:5000], "tags": fit_tags(m.get("tags", [])),
                        "categoryId": m.get("categoryId", "28"), "defaultLanguage": "en", "defaultAudioLanguage": "en"},
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                       "containsSyntheticMedia": bool(m.get("containsSyntheticMedia", False))}}
    if m.get("publishAt"):
        body["status"]["publishAt"] = m["publishAt"]
    f = P(m["file"]); size = os.path.getsize(f)
    c, _, h = api("POST", "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status&notifySubscribers=true",
                  tok, body, "application/json; charset=UTF-8", headers={"X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    if c != 200:
        sys.exit(f"init failed {c} {_}")
    loc = h["Location"]; chunk = 64 * 1024 * 1024; pos = 0; vid = None
    with open(f, "rb") as fh:
        while pos < size:
            fh.seek(pos); data = fh.read(chunk); end = pos + len(data) - 1
            for attempt in range(5):
                c, d, hh = api("PUT", loc, tok, raw=data, ctype="video/mp4", headers={"Content-Range": f"bytes {pos}-{end}/{size}"})
                if c in (200, 201, 308):
                    break
                time.sleep(2 ** attempt * 2)
            if c in (200, 201):
                vid = d["id"]; break
            if c != 308:
                sys.exit(f"upload failed {c} {d}")
            rng = hh.get("Range"); pos = int(rng.split("-")[1]) + 1 if rng else pos
            print(f"uploaded {pos * 100 // size}%", flush=True)
    print("video id:", vid)
    if m.get("thumbnail"):
        tp = P(m["thumbnail"]); ct = "image/png" if tp.endswith(".png") else "image/jpeg"
        c, d, _ = api("POST", f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}", tok, raw=open(tp, "rb").read(), ctype=ct)
        print("thumbnail:", c)
    if m.get("captions"):
        meta = json.dumps({"snippet": {"videoId": vid, "language": "en", "name": "English", "isDraft": False}}).encode()
        bnd = "ttbnd"
        payload = (f"--{bnd}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n").encode() + meta + \
                  (f"\r\n--{bnd}\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + open(P(m["captions"]), "rb").read() + f"\r\n--{bnd}--".encode()
        c, d, _ = api("POST", "https://www.googleapis.com/upload/youtube/v3/captions?uploadType=multipart&part=snippet", tok, raw=payload,
                      ctype=f"multipart/related; boundary={bnd}")
        if c in (200, 201):
            print("captions: uploaded")
        else:
            print(f"captions: skipped ({c}); the device-flow token has only the youtube scope, captions.insert needs youtube.force-ssl. YouTube automatic captions are used; captions.srt stays in Drive.")
    if m.get("playlist"):
        c, d, _ = api("GET", "https://youtube.googleapis.com/youtube/v3/playlists?part=snippet&mine=true&maxResults=50", tok)
        pl = next((i["id"] for i in d.get("items", []) if i["snippet"]["title"].lower() == m["playlist"].lower()), None)
        if not pl:
            c, d, _ = api("POST", "https://youtube.googleapis.com/youtube/v3/playlists?part=snippet,status", tok,
                          {"snippet": {"title": m["playlist"]}, "status": {"privacyStatus": "public"}})
            pl = d.get("id") if isinstance(d, dict) else None
        if pl:
            c, d, _ = api("POST", "https://youtube.googleapis.com/youtube/v3/playlistItems?part=snippet", tok,
                          {"snippet": {"playlistId": pl, "resourceId": {"kind": "youtube#video", "videoId": vid}}})
            print("playlist:", c)
    json.dump({"videoId": vid, "url": f"https://youtu.be/{vid}", "publishAt": m.get("publishAt")}, open(P("upload_result.json"), "w"))


def fit_tags(tags):
    tags = list(tags)
    while tags and tag_chars(tags) > 500:
        tags.pop()
    return tags


def tag_chars(tags):
    """YouTube's 500-character tag budget: multi-word tags count their quotes, plus a comma between tags."""
    return sum(len(t) + (2 if " " in t else 0) for t in tags) + max(0, len(tags) - 1)


def update(meta_path, vid):
    """Re-write title/description/tags/category/language of an uploaded video (SEO refresh). Keeps status and schedule."""
    m = json.load(open(meta_path))
    tags = list(m.get("tags", []))
    while tags and tag_chars(tags) > 500:
        tags.pop()
    tok = token()
    body = {"id": vid, "snippet": {"title": m["title"][:100], "description": m["description"][:5000], "tags": tags,
                                   "categoryId": m.get("categoryId", "28"), "defaultLanguage": "en", "defaultAudioLanguage": "en"}}
    c, d, _ = api("PUT", "https://youtube.googleapis.com/youtube/v3/videos?part=snippet", tok, body)
    print("snippet update:", c, (d.get("snippet", {}).get("title") if isinstance(d, dict) else d), "| tags", len(tags), "chars", tag_chars(tags))
    if m.get("playlist") and m.get("playlistDescription"):
        c, d, _ = api("GET", "https://youtube.googleapis.com/youtube/v3/playlists?part=snippet&mine=true&maxResults=50", tok)
        it = next((i for i in d.get("items", []) if i["snippet"]["title"].lower() == m["playlist"].lower()), None)
        if it:
            c, d, _ = api("PUT", "https://youtube.googleapis.com/youtube/v3/playlists?part=snippet", tok,
                          {"id": it["id"], "snippet": {"title": it["snippet"]["title"], "description": m["playlistDescription"][:5000], "defaultLanguage": "en"}})
            print("playlist description:", c)


def status(vid):
    tok = token()
    c, d, _ = api("GET", f"https://youtube.googleapis.com/youtube/v3/videos?part=status,processingDetails,snippet&id={vid}", tok)
    for it in d.get("items", []):
        print(it["snippet"]["title"], json.dumps(it["status"]), it.get("processingDetails", {}).get("processingStatus"))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "update": update(sys.argv[2], sys.argv[3])
    {"check": check, "device-start": device_start, "device-poll": device_poll}.get(cmd, lambda: None)()
    if cmd == "upload": upload(sys.argv[2])
    if cmd == "status": status(sys.argv[2])

#!/usr/bin/env python3
"""Titans Told animated key moments with Google Veo on Vertex AI (owner decision 18 Nov 2026: "Check CEOzoned videos. They
have moving characters like in a movie" / "Carry on animating key moments 45/50/60/... whatever required to make it
compelling"). Our own approved illustration is the first frame; Veo animates it (people move, talk, gesture, react) as a
4-second 1080p clip with no audio. Paid from the same Google Cloud credits as the Gemini images (network secret for
aiplatform.googleapis.com; never print it).

usage (run in work/ after the illustrations pass QA, before tt_cues):
  python3 ../tools/tt_veo.py anim.txt [--img img] [--out anim] [--workers 4] [--model veo-3.1-lite-generate-001]
      anim.txt: one line per key moment: "sNN_slug | what moves: the people's actions, expressions and one camera move"
      writes anim/sNN_slug.mp4 (1920x1080, 4 s). Skips clips that already exist (resumable). tt_compose then plays the
      clip instead of the still for that shot automatically.
Exit codes: 0 all done; 8 some failed or were filtered (listed; those shots keep the still with its camera move).
Writes veo_log.json (clips, seconds, est. INR) for the record and the credit watch.
"""
import base64, concurrent.futures as cf, json, os, sys, time, urllib.request

PROJECT = "gen-lang-client-0745268634"
BASE = f"https://aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/global/publishers/google/models/"
EST_INR_PER_SEC = 8.5   # rough estimate until the Billing report gives the real Veo 3.1 Lite 1080p rate (update it)
STYLE = ("Smooth 2D cartoon animation in exactly the same hand-drawn art style, colours and lighting as the image. Keep every "
         "person's face, hair, glasses and clothes identical to the image, keep the place and objects the same. Natural, "
         "lively character acting (talking, gesturing, reacting, walking), small secondary motion (hair, steam, papers, "
         "crowd). One gentle camera move at most. No text, letters, numbers, logos or subtitles appearing anywhere. No "
         "new people entering unless described.")


def arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


MODEL = arg("--model", "veo-3.1-lite-generate-001")


def post(path, body, timeout=120):
    req = urllib.request.Request(BASE + MODEL + path, data=json.dumps(body).encode(),
                                 headers={"x-goog-api-key": "injected-by-proxy", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def animate(img_path, prompt, out):
    body = {"instances": [{"prompt": prompt.rstrip(". ") + ". " + STYLE,
                           "image": {"bytesBase64Encoded": base64.b64encode(open(img_path, "rb").read()).decode(),
                                     "mimeType": "image/png"}}],
            "parameters": {"sampleCount": 1, "durationSeconds": 4, "aspectRatio": "16:9", "resolution": "1080p",
                           "generateAudio": False}}
    op, last = None, ""
    for attempt in range(6):
        try:
            op = post(":predictLongRunning", body)["name"]; break
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode(errors='ignore')[:160]}"
            if e.code not in (429, 500, 502, 503, 504):
                break
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(20 * (attempt + 1))
    if not op:
        raise RuntimeError("submit failed: " + last)
    for _ in range(90):   # up to ~15 minutes
        time.sleep(10)
        try:
            d = post(":fetchPredictOperation", {"operationName": op}, timeout=60)
        except Exception:
            continue
        if d.get("done"):
            if d.get("error"):
                raise RuntimeError("veo error: " + json.dumps(d["error"])[:200])
            vids = d.get("response", {}).get("videos", [])
            if not vids or not vids[0].get("bytesBase64Encoded"):
                raise RuntimeError("no video (filtered=%s)" % d.get("response", {}).get("raiMediaFilteredCount"))
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            open(out, "wb").write(base64.b64decode(vids[0]["bytesBase64Encoded"]))
            return out
    raise RuntimeError("timed out waiting for the clip")


def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
        print(__doc__); return
    imgdir, outdir = arg("--img", "img"), arg("--out", "anim")
    jobs = []
    for ln in open(sys.argv[1], encoding="utf-8"):
        if "|" not in ln or ln.lstrip().startswith("#"):
            continue
        sid, prompt = [x.strip() for x in ln.split("|", 1)]
        src = os.path.join(imgdir, sid + ".png"); dst = os.path.join(outdir, sid + ".mp4")
        if not os.path.exists(src):
            print("missing image, skipped:", src); continue
        if not os.path.exists(dst):
            jobs.append((src, prompt, dst))
    done, failed = 0, []
    with cf.ThreadPoolExecutor(int(arg("--workers", "4"))) as ex:
        futs = {ex.submit(animate, *j): j for j in jobs}
        for f in cf.as_completed(futs):
            try:
                f.result(); done += 1
            except Exception as e:
                failed.append(f"{os.path.basename(futs[f][2])}: {str(e)[:140]}")
    log = json.load(open("veo_log.json")) if os.path.exists("veo_log.json") else {"model": MODEL, "clips": 0, "seconds": 0, "est_inr": 0.0}
    log["clips"] += done; log["seconds"] += 4 * done; log["est_inr"] += 4 * done * EST_INR_PER_SEC
    json.dump(log, open("veo_log.json", "w"), indent=1)
    total = len([f for f in os.listdir(outdir)]) if os.path.isdir(outdir) else 0
    print(f"veo: {done} new clips ({total} in {outdir}/) | this video {log['clips']} clips, {log['seconds']} s, est. INR {log['est_inr']:.0f}")
    if failed:
        print("not animated (shot keeps its still):\n- " + "\n- ".join(failed)); sys.exit(8)


if __name__ == "__main__":
    main()

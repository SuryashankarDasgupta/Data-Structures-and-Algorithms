"""Titans Told illustrations with Google Gemini (owner decision 15 Nov 2026: "Approved, go ahead with Gemini").
Replaces Canva as the FIRST source of new illustrations (Canva stays the fallback). The API key is injected by the
environment's network secret for generativelanguage.googleapis.com (header x-goog-api-key); never print or store it.

BACKENDS (owner, 15 Nov 2026): Vertex AI FIRST (project "Titans Told Images", paid from the Google Cloud trial credits
of INR 28,569 valid to 14 Feb 2027; network secret for aiplatform.googleapis.com, header x-goog-api-key), real-time 1K.
Fallback (owner, 15 Nov 2026: "Keep the Canva as fallback from Nov 28. AI studio has no balance"): when Vertex fails the
tool exits 10 (VERTEX_UNAVAILABLE) and production draws the rest with Canva. AI Studio is used only with --studio
(manual, if the owner tops it up); its batch commands stay available for that case.
Owner decision 15 Nov 2026 (cost): "Go ahead with 1k plus batches" -> scenes at 1K through the Batch API (about half price,
results within hours); real-time 1K only for BREAKING videos or when a batch is late; thumbnails at 2K (one still).

usage (run in work/):
  python3 ../tools/tt_gemini.py batch-submit plan.txt [--state batches.json] [--chunk 20]
      submits the missing subjects as Batch API jobs (1K); writes batches.json {batch name: [subject ids]}.
      SAVE the batch names to Drive right away (the container is temporary): file "gemini batches.md" in the draft folder.
  python3 ../tools/tt_gemini.py batch-fetch [--state batches.json] --out img
      fetches finished batches into img/sNN_slug.png (1920x1080). Exit 0 = all done; 9 = some still running; 8 = some failed.
  python3 ../tools/tt_gemini.py plan.txt --out img [--workers 4] [--size 1K]      (real-time; BREAKING or late batches)
      plan.txt: one subject per line, "sNN_slug | what to draw" (from the metadata.md visual plan).
      Writes img/sNN_slug.png at 1920x1080 (16:9 cover crop of the 2K render). Skips files that already exist, so it
      is resumable; re-run with --redo sNN_slug,sMM_slug to redraw rejected images (QA). Max 2 redraws per subject.
  python3 ../tools/tt_gemini.py --thumb "<full Style T thumbnail prompt>" --out thumbs/baseT.png
Exit codes: 0 ok; 7 = prepaid credits depleted (402) -> stop, fall back to Canva, email the owner
"Titans Told – Gemini credits low"; 8 = some subjects failed after retries (listed; draw them with Canva).
Writes gemini_log.json: images made, redraws, model, estimated cost (INR) for the voice/credit log and the record."""
import base64, concurrent.futures as cf, io, json, os, sys, time, urllib.request
from PIL import Image

STYLE = ("Editorial comic-book documentary illustration, bold clean ink outlines, flat cel shading with subtle paper "
         "grain, limited palette of deep navy #1F2A44, warm cream #F2E8D5, mustard gold #D4A017 and brown #7B4B2A, "
         "cinematic 16:9 composition, dramatic lighting, full-bleed (scene continues to every edge). ABSOLUTELY NO TEXT "
         "anywhere: no letters, words, numbers, digits, signage lettering, code on screens, logos or brand marks; every "
         "sign, screen, poster, box, label and document is blank or shows only abstract shapes. Real people only as "
         "generic stylized figures unless the prompt describes a look.")
EST_INR = {"2K": 17.0, "1K": 4.5, "4K": 30.0}   # real-time; batch = half (observed 15 Nov: ~INR 17 per 2K image)
BATCH_FACTOR = 0.5   # rough estimate per image; the AI Studio Spend page is the truth


def arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


MODEL = arg("--model", "gemini-3.1-flash-image")
SIZE = arg("--size", "2K" if "--thumb" in sys.argv else "1K")


class Depleted(Exception):
    pass


def req_body(prompt, size=None):
    return {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "16:9", "imageSize": size or SIZE}}}


def rest(method, path, body=None):
    req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"x-goog-api-key": "injected-by-proxy", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return 200, json.load(r)
    except urllib.error.HTTPError as e:
        txt = e.read().decode(errors="ignore")
        if e.code == 402 or "prepayment credits are depleted" in txt:
            raise Depleted()
        return e.code, txt[:300]


def read_plan(plan, outdir):
    items = []
    for line in open(plan):
        if "|" not in line or line.strip().startswith("#"):
            continue
        sid, subj = [x.strip() for x in line.split("|", 1)]
        items.append((sid, subj, os.path.join(outdir, sid + ".png")))
    return items


def batch_submit():
    plan, state = sys.argv[2], arg("--state", "batches.json"); outdir = arg("--out", "img"); chunk = int(arg("--chunk", "20"))
    st = json.load(open(state)) if os.path.exists(state) else {}
    queued = {s for v in st.values() for s in v}
    todo = [(sid, subj) for sid, subj, out in read_plan(plan, outdir) if not os.path.exists(out) and sid not in queued]
    try:
        for i in range(0, len(todo), chunk):
            part = todo[i:i + chunk]
            body = {"batch": {"display_name": f"titans-told-{int(time.time())}-{i}", "input_config": {"requests": {"requests": [
                {"request": req_body(subj.rstrip(". ") + ". " + STYLE, "1K"), "metadata": {"key": sid}} for sid, subj in part]}}}}
            c, d = rest("POST", f"models/{MODEL}:batchGenerateContent", body)
            if c != 200:
                print(f"batch submit failed ({c}): {d}"); json.dump(st, open(state, "w"), indent=1); sys.exit(8)
            st[d["name"]] = [sid for sid, _ in part]; json.dump(st, open(state, "w"), indent=1)
            print("submitted", d["name"], len(part), "subjects")
    except Depleted:
        print("GEMINI_CREDITS_DEPLETED"); sys.exit(7)
    print(f"{len(todo)} subjects queued in batches; save {state} names to Drive now")


def _find_responses(d):
    """Return [(key, response)] from a finished batch, whatever the nesting."""
    out = []
    def walk(x):
        if isinstance(x, dict):
            if "response" in x and isinstance(x.get("metadata"), dict) and "key" in x["metadata"]:
                out.append((x["metadata"]["key"], x["response"])); return
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    walk(d.get("response", d)); return out


def batch_fetch():
    state, outdir = arg("--state", "batches.json"), arg("--out", "img")
    if not os.path.exists(state):
        sys.exit("no batches.json: download 'gemini batches.md' from Drive into it first (lines: batches/<id> | sid,sid,...)")
    st = json.load(open(state)); log = load_log(); pending = failed = got = 0
    for name, sids in list(st.items()):
        try:
            c, d = rest("GET", name)
        except Depleted:
            print("GEMINI_CREDITS_DEPLETED"); sys.exit(7)
        if c != 200:
            print(name, "status error", c, d); pending += 1; continue
        state_s = json.dumps(d.get("metadata", {}).get("state", "")) + str(d.get("state", ""))
        if not d.get("done") and "SUCCEEDED" not in state_s:
            print(name, "still running", state_s); pending += 1; continue
        if any(x in state_s for x in ("FAILED", "CANCELLED", "EXPIRED")):
            print(name, "ended:", state_s); failed += len(sids); del st[name]; continue
        done_here = set()
        for key, resp in _find_responses(d):
            for p in resp.get("candidates", [{}])[0].get("content", {}).get("parts", []):
                if "inlineData" in p:
                    save_1080(base64.b64decode(p["inlineData"]["data"]), os.path.join(outdir, key + ".png")); done_here.add(key); got += 1; break
        miss = [s for s in sids if s not in done_here]
        if miss:
            print(name, "no image for:", ",".join(miss)); failed += len(miss)
        del st[name]
    json.dump(st, open(state, "w"), indent=1)
    log["images"] += got; log["est_inr"] = round(log["est_inr"] + got * EST_INR["1K"] * BATCH_FACTOR, 1); log["batch"] = True
    json.dump(log, open("gemini_log.json", "w"), indent=1)
    print(f"batch fetch: {got} images saved, {pending} batches still running, {failed} subjects failed")
    sys.exit(9 if pending else (8 if failed else 0))


VERTEX_FAILED = []


def call_vertex(prompt):
    body = req_body(prompt); body["contents"][0]["role"] = "user"
    req = urllib.request.Request(f"https://aiplatform.googleapis.com/v1/publishers/google/models/{MODEL}:generateContent",
                                 data=json.dumps(body).encode(),
                                 headers={"x-goog-api-key": "injected-by-proxy", "Content-Type": "application/json"})
    last = ""
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                d = json.load(r)
            for p in d.get("candidates", [{}])[0].get("content", {}).get("parts", []):
                if "inlineData" in p:
                    return base64.b64decode(p["inlineData"]["data"])
            last = "no image (" + str(d.get("candidates", [{}])[0].get("finishReason", "?")) + ")"
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode(errors='ignore')[:160]}"
            if e.code not in (429, 500, 502, 503, 504):
                break
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(8 * (attempt + 1))
    raise RuntimeError("vertex: " + last)


def call(prompt):
    if "--studio" not in sys.argv and not VERTEX_FAILED:
        try:
            return call_vertex(prompt)
        except RuntimeError as e:
            if "HTTP 4" in str(e) and "HTTP 429" not in str(e):   # auth/billing/model problem: stop, Canva takes over
                VERTEX_FAILED.append(str(e)); print("VERTEX_UNAVAILABLE:", str(e)[:200])
            raise
    if VERTEX_FAILED:
        raise RuntimeError("vertex unavailable")
    return call_studio(prompt)


def call_studio(prompt):
    body = req_body(prompt)
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
                                 data=json.dumps(body).encode(),
                                 headers={"x-goog-api-key": "injected-by-proxy", "Content-Type": "application/json"})
    last = ""
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                d = json.load(r)
            for p in d.get("candidates", [{}])[0].get("content", {}).get("parts", []):
                if "inlineData" in p:
                    return base64.b64decode(p["inlineData"]["data"])
            last = "no image in response (" + str(d.get("candidates", [{}])[0].get("finishReason", "?")) + ")"
        except urllib.error.HTTPError as e:
            txt = e.read().decode(errors="ignore")
            if e.code == 402 or "prepayment credits are depleted" in txt:
                raise Depleted()
            last = f"HTTP {e.code}: {txt[:160]}"
            if e.code not in (429, 500, 502, 503, 504):
                break
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(8 * (attempt + 1))
    raise RuntimeError(last)


def save_1080(raw, out):
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = im.size; tw, th = 1920, 1080
    s = max(tw / w, th / h); im = im.resize((round(w * s), round(h * s)), Image.LANCZOS)
    l, t = (im.width - tw) // 2, (im.height - th) // 2
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    im.crop((l, t, l + tw, t + th)).save(out)


def load_log():
    return json.load(open("gemini_log.json")) if os.path.exists("gemini_log.json") else {"model": MODEL, "size": SIZE, "images": 0, "redraws": {}, "est_inr": 0.0}


def main():
    log = load_log()
    if "--thumb" in sys.argv:
        out = arg("--out", "thumbs/baseT.png")
        try:
            save_1080(call(arg("--thumb")), out)
        except Depleted:
            print("GEMINI_CREDITS_DEPLETED"); sys.exit(7)
        except RuntimeError as e:
            print("VERTEX_UNAVAILABLE:" if VERTEX_FAILED else "FAILED:", str(e)[:200]); sys.exit(10 if VERTEX_FAILED else 8)
        log["images"] += 1; log["est_inr"] += EST_INR.get(SIZE, 10.0)
        json.dump(log, open("gemini_log.json", "w"), indent=1); print("thumbnail ->", out); return
    plan, outdir = sys.argv[1], arg("--out", "img")
    redo = set(filter(None, (arg("--redo", "") or "").split(",")))
    items = []
    for line in open(plan):
        if "|" not in line or line.strip().startswith("#"):
            continue
        sid, subj = [x.strip() for x in line.split("|", 1)]
        out = os.path.join(outdir, sid + ".png")
        if sid in redo:
            if log["redraws"].get(sid, 0) >= 2:
                print(f"{sid}: 2 redraws already used -> draw it with Canva"); continue
            log["redraws"][sid] = log["redraws"].get(sid, 0) + 1
        elif os.path.exists(out):
            continue
        items.append((sid, subj, out))
    done, failed, depleted = 0, [], False

    def work(it):
        sid, subj, out = it
        save_1080(call(subj.rstrip(". ") + ". " + STYLE), out)
        return sid

    with cf.ThreadPoolExecutor(int(arg("--workers", "4"))) as ex:
        futs = {ex.submit(work, it): it for it in items}
        for f in cf.as_completed(futs):
            sid = futs[f][0]
            try:
                f.result(); done += 1
            except Depleted:
                depleted = True; failed.append(sid)
            except Exception as e:
                failed.append(sid); print(f"{sid}: failed: {e}")
    log["images"] += done; log["backend"] = "studio" if (VERTEX_FAILED or "--studio" in sys.argv) else "vertex (Cloud credits)"
    log["est_inr"] = round(log["est_inr"] + done * EST_INR.get(SIZE, 10.0), 1)
    json.dump(log, open("gemini_log.json", "w"), indent=1)
    print(f"gemini: {done} new images -> {outdir}/ | total this video {log['images']} | est. INR {log['est_inr']}")
    if VERTEX_FAILED:
        print("VERTEX_UNAVAILABLE: draw the rest with Canva (section 4):", ",".join(sorted(failed))); sys.exit(10)
    if depleted:
        print("GEMINI_CREDITS_DEPLETED: top up in AI Studio; draw the rest with Canva:", ",".join(sorted(failed))); sys.exit(7)
    if failed:
        print("FAILED (draw with Canva or retry):", ",".join(sorted(failed))); sys.exit(8)


if __name__ == "__main__":
    {"batch-submit": batch_submit, "batch-fetch": batch_fetch}.get(sys.argv[1] if len(sys.argv) > 1 else "", main)()

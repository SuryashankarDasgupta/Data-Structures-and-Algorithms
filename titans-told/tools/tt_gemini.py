"""Titans Told illustrations with Google Gemini (owner decision 15 Nov 2026: "Approved, go ahead with Gemini").
Replaces Canva as the FIRST source of new illustrations (Canva stays the fallback). The API key is injected by the
environment's network secret for generativelanguage.googleapis.com (header x-goog-api-key); never print or store it.

usage (run in work/):
  python3 ../tools/tt_gemini.py plan.txt --out img [--workers 4] [--model gemini-3.1-flash-image] [--size 2K]
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
EST_INR = {"2K": 10.0, "1K": 4.0, "4K": 20.0}   # rough estimate per image; the AI Studio Spend page is the truth


def arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


MODEL = arg("--model", "gemini-3.1-flash-image")
SIZE = arg("--size", "2K")


class Depleted(Exception):
    pass


def call(prompt):
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "16:9", "imageSize": SIZE}}}
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
    log["images"] += done; log["est_inr"] = round(log["est_inr"] + done * EST_INR.get(SIZE, 10.0), 1)
    json.dump(log, open("gemini_log.json", "w"), indent=1)
    print(f"gemini: {done} new images -> {outdir}/ | total this video {log['images']} | est. INR {log['est_inr']}")
    if depleted:
        print("GEMINI_CREDITS_DEPLETED: top up in AI Studio; draw the rest with Canva:", ",".join(sorted(failed))); sys.exit(7)
    if failed:
        print("FAILED (draw with Canva or retry):", ",".join(sorted(failed))); sys.exit(8)


if __name__ == "__main__":
    main()

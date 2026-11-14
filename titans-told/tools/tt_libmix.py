"""Titans Told library + Canva mix (owner decision 14 Nov 2026: "keep every video fresh in look and feel and keep
the viewers hooked for the entire time").

usage (run in work/):
  python3 ../tools/tt_libmix.py recent usage/            # list library ids used in the last 8 videos (do not pick these)
  python3 ../tools/tt_libmix.py vary picks.txt --look <look> --video <NN> [--lib DIR] [--new DIR] [--out img4k]
      picks.txt: one library id per line (catalog ids like nv_n001, or new-library file stems like n09_s45_slug).
      Writes img4k/lib_<id>.png (2400x1350): each reused image gets its OWN crop window, zoom, optional mirror and
      this video's colour look, so it never looks the same as in an earlier video. Use the ids "lib_<id>" in pools.
      Refuses ids used in the last 8 videos (usage/ = the downloaded "TT library usage" files).
  python3 ../tools/tt_libmix.py check cues.py vo/timeline.json --twist "<first words of the twist line>"
      [--callback "<first words of the callback payoff>"]
      PASS needs: library images <= 60% of image shots; none in the first 60 s; none within 8 s of the twist
      and callback lines; never more than 2 library images in a row; every library shot <= 3.6 s.
  python3 ../tools/tt_libmix.py grade img4k --look <look>   # same look at half strength on the new Canva images
      (in place, skips lib_* files) so every shot of the video shares one colour feel
  python3 ../tools/tt_libmix.py usage-line picks.txt     # the line to save in the "TT library usage" Drive folder
Looks: neon, noir, cold, warm, clinical, gold, ember, steel, dusk (pick the one that fits the story; vary it from
the previous video's look).
"""
import hashlib, json, os, re, runpy, sys
from PIL import Image, ImageEnhance, ImageOps

LOOKS = {   # tint colour, tint strength, contrast, saturation, brightness
    "neon": ((214, 60, 160), 0.14, 1.10, 1.12, 0.98), "noir": ((30, 40, 70), 0.20, 1.16, 0.80, 0.92),
    "cold": ((70, 120, 190), 0.14, 1.06, 0.95, 1.00), "warm": ((220, 150, 70), 0.13, 1.04, 1.05, 1.02),
    "clinical": ((150, 200, 205), 0.13, 1.08, 0.85, 1.04), "gold": ((212, 160, 23), 0.15, 1.06, 1.06, 1.02),
    "ember": ((200, 70, 40), 0.14, 1.10, 1.04, 0.97), "steel": ((120, 135, 150), 0.16, 1.10, 0.82, 0.98),
    "dusk": ((150, 90, 160), 0.14, 1.06, 1.00, 0.98)}
GAP = 8           # a library image may not come back within the next 8 videos
OUT_W, OUT_H = 2400, 1350


def args_after(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def recent_ids(udir):
    """usage files: one per video, first line '<NN> | <ids comma-separated>'; newest GAP videos count."""
    if not udir or not os.path.isdir(udir):
        return set()
    rows = []
    for f in os.listdir(udir):
        txt = open(os.path.join(udir, f), errors="ignore").read().strip()
        m = re.match(r"\s*(\d+)\s*\|\s*(.*)", txt, re.S)
        if m:
            rows.append((int(m.group(1)), [i.strip() for i in m.group(2).replace("\n", ",").split(",") if i.strip()]))
    rows.sort(reverse=True)
    return {i for _, ids in rows[:GAP] for i in ids}


def find_src(i, dirs):
    for d in dirs:
        for ext in ("jpg", "png", "jpeg"):
            p = os.path.join(d, f"{i}.{ext}")
            if os.path.exists(p):
                return p
    return None


def vary(src, dst, seed, look):
    h = hashlib.sha256(seed.encode()).digest()
    r = [b / 255 for b in h]
    im = Image.open(src).convert("RGB")
    if r[0] < 0.5:
        im = ImageOps.mirror(im)
    z = 0.80 + 0.12 * r[1]                               # keep 80-92% of the frame
    iw, ih = im.size
    cw, ch = iw * z, ih * z
    cx = cw / 2 + (iw - cw) * r[2]
    cy = ch / 2 + (ih - ch) * r[3]
    im = im.crop((int(cx - cw / 2), int(cy - ch / 2), int(cx + cw / 2), int(cy + ch / 2))).resize((OUT_W, OUT_H), Image.LANCZOS)
    col, k, con, sat, bri = LOOKS[look]
    k = k * (0.85 + 0.3 * r[4])
    im = Image.blend(im, Image.new("RGB", im.size, col), k)
    im = ImageEnhance.Contrast(im).enhance(con)
    im = ImageEnhance.Color(im).enhance(sat)
    im = ImageEnhance.Brightness(im).enhance(bri)
    im.save(dst, optimize=True)


def cmd_vary():
    picks = [l.strip() for l in open(sys.argv[2]) if l.strip() and not l.startswith("#")]
    look = args_after("--look") or sys.exit("--look required: " + ", ".join(LOOKS))
    if look not in LOOKS:
        sys.exit("unknown look; choose from " + ", ".join(LOOKS))
    video = args_after("--video") or sys.exit("--video NN required")
    dirs = [args_after("--lib", "lib"), args_after("--new", "newlib")]
    out = args_after("--out", "img4k"); os.makedirs(out, exist_ok=True)
    bad = sorted(set(picks) & recent_ids(args_after("--usage", "usage")))
    if bad:
        sys.exit(f"used in the last {GAP} videos, pick others: {', '.join(bad)}")
    if len(set(picks)) != len(picks):
        sys.exit("duplicate ids in picks.txt (each image once per video)")
    miss = []
    for i in picks:
        s = find_src(i, dirs)
        if not s:
            miss.append(i); continue
        vary(s, os.path.join(out, f"lib_{i}.png"), f"{video}:{i}", look)
    print(f"varied {len(picks) - len(miss)} library images with look '{look}' -> {out}/lib_<id>.png")
    if miss:
        sys.exit("missing source files: " + ", ".join(miss))


def cmd_check():
    cues = runpy.run_path(sys.argv[2])["CUES"]
    tl = json.load(open(sys.argv[3]))
    norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
    words = [(norm(w["w"]), w["s"]) for s in tl for w in s["words"] if norm(w["w"])]

    def at(ph, after=0.0):
        toks = [norm(t) for t in ph.split() if norm(t)][:4]
        for i in range(len(words)):
            if words[i][1] >= after - 0.01 and all(i + k < len(words) and words[i + k][0] == toks[k] for k in range(len(toks))):
                return words[i][1]
        return None
    shots, t = [], 0.0
    for ph, sc in cues:
        s = at(ph, t)
        if s is None:
            continue
        s = 0.0 if not shots else max(s, t + 0.3)
        shots.append([s, None, sc]); t = s
    for a, b in zip(shots, shots[1:]):
        a[1] = b[0]
    if shots:
        shots[-1][1] = tl[-1]["end"] + 1.5
    imgs = [x for x in shots if x[2].get("type") == "image"]
    islib = lambda x: "/lib_" in str(x[2].get("src", ""))
    lib = [x for x in imgs if islib(x)]
    errs = []
    share = len(lib) / max(1, len(imgs))
    if share > 0.60:
        errs.append(f"library share {share:.0%} > 60%")
    for x in lib:
        if x[0] < 60:
            errs.append(f"library image in the first 60 s at {x[0]:.1f}s ({x[2]['src']})")
        if x[1] - x[0] > 3.6:
            errs.append(f"library shot {x[1] - x[0]:.1f}s > 3.6 s at {x[0]:.1f}s")
    for flag in ("--twist", "--callback"):
        ph = args_after(flag)
        if ph:
            tt = at(ph)
            if tt is None:
                errs.append(f"{flag} phrase not found: {ph!r}")
            else:
                errs += [f"library image within 8 s of {flag[2:]} at {x[0]:.1f}s" for x in lib if abs(x[0] - tt) < 8]
    run = 0
    for x in shots:
        run = run + 1 if (x[2].get("type") == "image" and islib(x)) else 0
        if run > 2:
            errs.append(f"more than 2 library images in a row at {x[0]:.1f}s"); run = 0
    print(f"images {len(imgs)} | library {len(lib)} ({share:.0%}) | new {len(imgs) - len(lib)}")
    if errs:
        print("FAIL\n- " + "\n- ".join(errs[:40])); sys.exit(3)
    print("PASS")


def cmd_grade():
    d = sys.argv[2]; look = args_after("--look")
    if look not in LOOKS:
        sys.exit("--look required: " + ", ".join(LOOKS))
    col, k, con, sat, bri = LOOKS[look]
    n = 0
    for f in sorted(os.listdir(d)):
        if f.startswith("lib_") or not f.lower().endswith((".png", ".jpg")):
            continue
        p = os.path.join(d, f); im = Image.open(p).convert("RGB")
        im = Image.blend(im, Image.new("RGB", im.size, col), k * 0.5)
        im = ImageEnhance.Contrast(im).enhance(1 + (con - 1) * 0.5)
        im = ImageEnhance.Color(im).enhance(1 + (sat - 1) * 0.5)
        im.save(p); n += 1
    print(f"graded {n} new images with look '{look}' (half strength)")


def cmd_usage_line():
    picks = [l.strip() for l in open(sys.argv[2]) if l.strip() and not l.startswith("#")]
    nn = args_after("--video", "NN")
    print(f"{nn} | " + ", ".join(picks))


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else ""
    if c == "recent":
        print("\n".join(sorted(recent_ids(sys.argv[2] if len(sys.argv) > 2 else "usage"))))
    elif c == "vary":
        cmd_vary()
    elif c == "check":
        cmd_check()
    elif c == "grade":
        cmd_grade()
    elif c == "usage-line":
        cmd_usage_line()
    else:
        print(__doc__)

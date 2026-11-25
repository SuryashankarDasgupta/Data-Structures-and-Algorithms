"""tt_plan.py — auto shot planner (run in work/: needs vo/timeline.json and specials.py defining SPECIALS, POOLS, TRACKER, PUNCH_EVERY, FX).
Images: TT_IMG_DIR (default img4k) / <id>.TT_IMG_EXT (default png); the breaking lane uses the library (jpg).
Original: Auto shot planner for Titans Told: fixed graphics at anchor phrases, images from per-section pools in between,
cut points snapped to word starts so tt_cues' pacing rules hold. Writes cues.py."""
import json, re, math
tl = json.load(open("vo/timeline.json"))
W = [w for s in tl for w in s["words"]]
norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
WN = [norm(w["w"]) for w in W]
END = tl[-1]["end"] + 1.5
SEC = {s["section"]: (s["start"], s["end"]) for s in tl}

def find(phrase, after=0.0):
    toks = [norm(t) for t in phrase.split() if norm(t)]
    for i in range(len(W)):
        if W[i]["s"] < after - 0.01:
            continue
        if all(i + k < len(W) and WN[i + k] == toks[k] for k in range(len(toks))):
            return i
    raise SystemExit(f"anchor not found: {phrase!r} after {after}")

TGT = 4.3
exec(open("specials.py").read())   # defines SPECIALS [(phrase, scene)], POOLS {section: [ids]}, SPARE [ids], TRACKER, PUNCH_EVERY
GLIM = dict(image=4.3, quote=6.8, headline=5.8, bars=7.8, linechart=7.8, timeline=7.8, checklist=7.8, document=5.8,
            counter=5.8, card=5.8, split=5.8, place=5.8)
GTARGET = dict(image=2.4, quote=5.0, headline=3.2, bars=5.0, checklist=7.5, document=5.0, counter=3.0, card=2.8, split=4.0, place=3.0)

def sec_of(t):
    for name, (a, b) in SEC.items():
        if a - 0.6 <= t < b + 0.6:
            return name
    return "OUTRO"

# fixed cut points
fixed = []
t = 0.0
for ph, sc in SPECIALS:
    i = find(ph, t)
    fixed.append((i, sc)); t = W[i]["s"]
starts = [W[i]["s"] for i, _ in fixed]

def wi_near(t, lo, hi):
    """index of the word whose start (-0.15) is nearest t, within [lo, hi] seconds."""
    best = None
    for i, w in enumerate(W):
        s = w["s"] - 0.15
        if lo <= s <= hi and (best is None or abs(s - t) < abs(W[best]["s"] - 0.15 - t)):
            best = i
    return best

cuts = []   # (word_index or None for 0, scene or 'IMG')
fixed_set = {i: sc for i, sc in fixed}
fi = [i for i, _ in fixed]
# segment boundaries: 0, fixed..., END
bounds = [(0 if fi[0] != 0 else None)] if fi and fi[0] != 0 else []
points = ([0.0] if not fi or W[fi[0]]["s"] > 0.3 else []) + [max(0.0, W[i]["s"] - 0.15) if k else 0.0 for k, i in enumerate(fi)] + [END]
kinds = (["IMG"] if not fi or W[fi[0]]["s"] > 0.3 else []) + [fixed_set[i] for i in fi]
anchor_idx = ([0] if not fi or W[fi[0]]["s"] > 0.3 else []) + fi
plan = []
for k in range(len(kinds)):
    a, b = points[k], points[k + 1]
    sc = kinds[k]
    hook = a < 30
    tgt, mx, mn = (2.3, 2.5, 2.05) if hook else (TGT, 4.3, 2.05)
    cur = a; cur_idx = anchor_idx[k]
    if sc != "IMG":
        typ = sc["type"]
        lim = 4.4 if (typ == "checklist" and "done" in sc) else GLIM.get(typ, 5.8)
        if hook:
            lim = min(lim, 2.55)
        want = min(lim, (b - a) if (b - a) <= lim else min(GTARGET.get(typ, 3.5), lim))
        if (b - a) - want < mn and (b - a) <= lim:
            want = b - a
        plan.append((cur_idx, sc))
        e = a + want
        if b - e < mn - 0.01:
            if b - a <= lim:
                continue
            e = b - mn - 0.05
        j = wi_near(e, a + 2.0, b - mn)
        if j is None:
            continue
        cur = W[j]["s"] - 0.15; cur_idx = j
    else:
        plan.append((cur_idx, "IMG"))
        cur_idx = None
    # fill [cur, b] with images
    rem = b - cur
    if sc == "IMG":
        n = max(1, round(rem / tgt), math.ceil(rem / mx))
        seg_from = a
        first_done = True
    else:
        n = max(1, round(rem / tgt), math.ceil(rem / mx)) if rem >= mn else 0
        seg_from = cur
        if n:
            plan.append((cur_idx, "IMG"))
    if n <= 1:
        continue
    step = rem / n
    prev = seg_from
    for m in range(1, n):
        tt = seg_from + step * m
        j = wi_near(tt, prev + mn, b - mn)
        if j is None:
            continue
        plan.append((j, "IMG")); prev = W[j]["s"] - 0.15

import os as _os
exec(open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "tt_plan_repair.py")).read())
plan.sort(key=lambda x: (W[x[0]]["s"] if x[0] is not None else 0))
# assign images: global story order, spread evenly over the image slots (Anthropic rebuild)
used_sp = set(re.findall(r'/([A-Za-z0-9_-]+)\.(?:png|jpg)', repr(SPECIALS)))
ordered = [i for v in POOLS.values() for i in v if i not in used_sp]
slots = [k for k, (idx, sc) in enumerate(plan) if sc == "IMG"]
pick = {}
if slots:
    n, m = len(ordered), len(slots)
    for j, k in enumerate(slots):
        pick[k] = ordered[min(n - 1, round(j * (n - 1) / max(1, m - 1)))] if m <= n else (ordered[j] if j < n else "MISSING")
used = set(); out = []; last_punch = -999
for k, (idx, sc) in enumerate(plan):
    t0 = W[idx]["s"] if idx is not None else 0.0
    if sc == "IMG":
        sec = sec_of(t0); img = pick[k]; used.add(img)
        fx = FX.get(sec, "dust"); motion = "in"
        if t0 >= 30 and t0 - last_punch >= PUNCH_EVERY:
            motion = "punch"; last_punch = t0
        sc = dict(type="image", src=f"{_os.environ.get('TT_IMG_DIR', 'img4k')}/{img}.{_os.environ.get('TT_IMG_EXT', 'png')}", motion=motion, fx=fx)
    phrase = " ".join(W[i]["w"] for i in range(idx, min(idx + 3, len(W)))) if idx is not None else W[0]["w"] + " " + W[1]["w"]
    out.append((phrase, sc))
print("image slots", len(slots), "available", len(ordered))
with open("cues.py", "w") as f:
    f.write("# auto-planned by plan.py\nTRACKER = " + repr(TRACKER) + "\nCUES = [\n")
    for ph, sc in out:
        f.write(f"({ph!r}, {sc!r}),\n")
    f.write("]\n")
print(len(out), "cues;", sum(1 for _, s in out if s.get("type") == "image"), "images; missing:",
      sum(1 for _, s in out if "MISSING" in str(s)), "; unused:", sorted(set(i for v in POOLS.values() for i in v) - used))

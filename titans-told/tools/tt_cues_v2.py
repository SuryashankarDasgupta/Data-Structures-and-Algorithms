"""Resolve cue phrases against vo/timeline.json -> spec.json"""
import json, re, sys, runpy
cues_py, timeline_p, out = sys.argv[1:4]
CUES = runpy.run_path(cues_py)["CUES"]
tl = json.load(open(timeline_p))
norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
words = [(norm(w["w"]), w["s"]) for sec in tl for w in sec["words"]]
words = [w for w in words if w[0]]
# whisper writes numbers as digits; also build from script text: map by sequence on whisper words
def find(phrase, after):
    toks = [norm(t) for t in phrase.split() if norm(t)][:3]
    for i in range(len(words)):
        if words[i][1] < after - 0.01: continue
        if all(i + k < len(words) and words[i + k][0] == toks[k] for k in range(len(toks))):
            return words[i][1]
    return None
scenes, t = [], 0.0
total = tl[-1]["end"] + 1.5
for ph, sc in CUES:
    s = find(ph, t)
    if s is None: print(f"cue not found: {ph!r} after {t}"); continue
    s = 0.0 if not scenes else max(s - 0.15, t + 0.5)
    sc = dict(sc, start=round(s, 2)); scenes.append(sc); t = s
for a, b in zip(scenes, scenes[1:]): a["end"] = b["start"]
scenes[-1]["end"] = total
# VARIETY RULES (owner, 6 Nov 2026: "same footage keeps coming consecutively"):
#  - an illustration may fill at most 2 consecutive shots (the 2nd is a different framing), max 8 s in total
#  - an illustration may appear at most twice in the whole video (deliberate callback)
#  - long scenes are NOT padded with an earlier picture; the cue sheet must add a new visual instead
MOVES = {"in": "right", "out": "left", "left": "in", "right": "out", "up": "in", "down": "out", "still": "in"}
FOCI2 = [[0.3, 0.4], [0.7, 0.45], [0.5, 0.35], [0.4, 0.6], [0.65, 0.6]]
problems = []
out_sc = []
for idx, sc in enumerate(scenes):
    d = sc["end"] - sc["start"]
    if sc.get("type") == "image" and d > 4.6:
        mid = round(sc["start"] + d / 2, 2)
        a_ = dict(sc, end=mid)
        b_ = dict(sc, start=mid, motion=MOVES.get(sc.get("motion", "in"), "in"), focus=FOCI2[idx % len(FOCI2)], sub=1)
        for o in ("kinetic", "kicker"):
            b_.pop(o, None)
        out_sc += [a_, b_]
        if d > 8.5:
            problems.append(f"IMAGE TOO LONG {d:.1f}s at {sc['start']:.1f}s ({sc['src']}): add another visual cue inside it")
    else:
        lim = {"checklist": 13, "timeline": 13, "linechart": 13, "bars": 13, "quote": 9.5, "headline": 9.0}.get(sc.get("type"), 8.5)
        if sc.get("type") != "image" and d > lim:
            problems.append(f"GRAPHIC TOO LONG {d:.1f}s at {sc['start']:.1f}s ({sc.get('type')}): add another visual cue inside it")
        out_sc.append(sc)
scenes = out_sc
from collections import Counter
uses = Counter()
prev = None
for sc in scenes:
    src = sc.get("src") if sc.get("type") in ("image", "frame3d") else None
    if src and src != prev:
        uses[src] += 1
    prev = src
for src, n in uses.items():
    if n > 2:
        problems.append(f"IMAGE USED {n} TIMES (max 2): {src}")
spec = {"narration": "vo/narration.wav", "music": "music/bed.mp3", "music_gain_db": -22, "duration": total, "scenes": scenes}
# chapter tracker (cues.py: TRACKER = [("THE IDEA", "ACT 1"), ...]; shown from the first chapter until the OUTRO starts)
TR = runpy.run_path(cues_py).get("TRACKER")
if TR:
    sec_start = {}
    for sec in tl:
        sec_start.setdefault(sec["section"], sec["start"])
    starts = [sec_start[s_] for _, s_ in TR]
    spec["tracker"] = {"items": [l for l, _ in TR], "starts": starts, "end": sec_start.get("OUTRO", total)}
    print("tracker:", ", ".join(f"{l}@{s0:.0f}s" for (l, _), s0 in zip(TR, starts)))
json.dump(spec, open(out, "w"), indent=1)
d = [round(s["end"] - s["start"], 1) for s in scenes]
print(len(scenes), "scenes; min", min(d), "max", max(d), "avg", round(sum(d) / len(d), 1))
print("unique illustrations:", len(uses))
for p_ in problems: print("FIX:", p_)
if not problems: print("variety rules: PASS")

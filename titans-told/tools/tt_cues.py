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
# VARIETY RULES (owner, 6 Nov 2026: "same footage keeps coming consecutively" and later "don't use the same
# visual twice in the video"):
#  - every illustration appears ONCE in the whole video (image, frame3d or split panel) — no callbacks, no
#    second framings, never back to back
#  - one illustration shot lasts at most 6.0 s (Ken Burns keeps it moving); longer beats get a NEW visual cue
#  - graphics have their own limits (quote 9.5, headline 9, checklist/timeline/charts 13, others 8.5 s)
IMG_MAX = 6.0
problems = []
from collections import Counter
uses = Counter()
for sc in scenes:
    d = sc["end"] - sc["start"]
    if sc.get("type") == "image":
        if d > IMG_MAX:
            problems.append(f"IMAGE TOO LONG {d:.1f}s at {sc['start']:.1f}s ({sc['src']}): add another visual cue inside it")
    else:
        lim = {"checklist": 13, "timeline": 13, "linechart": 13, "bars": 13, "quote": 9.5, "headline": 9.0}.get(sc.get("type"), 8.5)
        if d > lim:
            problems.append(f"GRAPHIC TOO LONG {d:.1f}s at {sc['start']:.1f}s ({sc.get('type')}): add another visual cue inside it")
    if d < 2.0 and sc is not scenes[0]:
        problems.append(f"SHOT TOO SHORT {d:.1f}s at {sc['start']:.1f}s ({sc.get('type')}): merge or move the cue")
    for o in (sc, sc.get("left") or {}, sc.get("right") or {}):
        if o.get("src"):
            uses[o["src"]] += 1
for src, n in uses.items():
    if n > 1:
        problems.append(f"IMAGE USED {n} TIMES (max 1): {src}")
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

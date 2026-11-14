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
# PACING RULES (owner, 10 Nov 2026, from the vidIQ reviews of Tesla/Nike: static hook, scoreboard held too long,
# slow explainer stretches, "visual fatigue"):
#  1. first 30 s: every shot <= 2.6 s (a cut at least every ~2.5 s; images there move faster in tt_compose)
#  2. the running thread graphic (checklist with "done") <= 4.5 s, and every return shows a NEW state
#  3. images <= 4.5 s anywhere; text graphics shorter (quote 7, headline 6, charts/timelines/plain checklists 8, others 6)
#  4. a visual re-hook (image with motion "punch", counter, headline or split) at least every 90 s from 0:30 to the outro
IMG_MAX = 4.5
HOOK_END, HOOK_MAX, THREAD_MAX, REHOOK_GAP = 30.0, 2.6, 4.5, 90.0
problems = []
from collections import Counter
uses = Counter()
for sc in scenes:
    d = sc["end"] - sc["start"]
    if sc.get("type") == "clip":   # owner plan 12 Nov 2026: one 5 s AI hero clip in the hook
        if d > 5.2:
            problems.append(f"HERO CLIP TOO LONG {d:.1f}s at {sc['start']:.1f}s: max 5 s")
    elif sc.get("type") == "image":
        if d > IMG_MAX:
            problems.append(f"IMAGE TOO LONG {d:.1f}s at {sc['start']:.1f}s ({sc['src']}): add another visual cue inside it")
    else:
        lim = {"checklist": 8, "timeline": 8, "linechart": 8, "bars": 8, "quote": 7.0, "headline": 6.0}.get(sc.get("type"), 6.0)
        if sc.get("type") == "checklist" and "done" in sc:
            lim = THREAD_MAX
        if d > lim:
            problems.append(f"GRAPHIC TOO LONG {d:.1f}s at {sc['start']:.1f}s ({sc.get('type')}, max {lim}s): add another visual cue inside it")
    if sc["start"] < HOOK_END and d > HOOK_MAX and sc.get("type") != "clip":
        problems.append(f"HOOK SHOT TOO LONG {d:.1f}s at {sc['start']:.1f}s ({sc.get('type')}): in the first 30 s cut at least every {HOOK_MAX}s")
    if d < 2.0 and sc is not scenes[0]:
        problems.append(f"SHOT TOO SHORT {d:.1f}s at {sc['start']:.1f}s ({sc.get('type')}): merge or move the cue")
    for o in (sc, sc.get("left") or {}, sc.get("right") or {}):
        if o.get("src"):
            uses[o["src"]] += 1
    if sc.get("clip"):
        uses[sc["clip"]] += 1
seen_states = set()
for sc in scenes:
    if sc.get("type") == "checklist" and "done" in sc:
        st = (sc.get("title"), tuple(sc.get("items", [])), json.dumps(sc.get("done")), json.dumps(sc.get("active")))
        if st in seen_states:
            problems.append(f"THREAD GRAPHIC REPEATED WITH NO CHANGE at {sc['start']:.1f}s: tick a new item or move 'active'")
        seen_states.add(st)
outro_t = next((sec["start"] for sec in tl if sec["section"] == "OUTRO"), total)
rehooks = [sc["start"] for sc in scenes if sc.get("motion") == "punch" or sc.get("type") in ("counter", "headline", "split", "clip")]
marks = [HOOK_END] + [r for r in rehooks if HOOK_END <= r <= outro_t] + [outro_t]
for a_, b_ in zip(marks, marks[1:]):
    if b_ - a_ > REHOOK_GAP:
        problems.append(f"NO RE-HOOK for {b_ - a_:.0f}s between {a_:.0f}s and {b_:.0f}s: add a punch-in image, counter, headline or split")
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

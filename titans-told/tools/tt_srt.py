"""timeline.json -> captions.srt using script words (exact) timed by aligned whisper words."""
import json, re, sys, difflib
tl = json.load(open(sys.argv[1])); out = sys.argv[2]
norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
def ts(x):
    h, r = divmod(x, 3600); m, s = divmod(r, 60); return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"
cues = []
for sec in tl:
    sw = sec["text"].split(); ww = sec["words"]
    a = [norm(w) for w in sw]; b = [norm(w["w"]) for w in ww]
    times = [None] * len(sw)
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            for k in range(i2 - i1): times[i1 + k] = (ww[j1 + k]["s"], ww[j1 + k]["e"])
        elif j2 > j1:  # spread replaced span over whisper span
            s0, e0 = ww[j1]["s"], ww[j2 - 1]["e"]; n = i2 - i1
            for k in range(n): times[i1 + k] = (s0 + (e0 - s0) * k / n, s0 + (e0 - s0) * (k + 1) / n)
    last = sec["start"]
    for k in range(len(times)):
        if times[k] is None: times[k] = (last, last + 0.2)
        last = times[k][1]
    line, st = [], None
    for w, (s, e) in zip(sw, times):
        if not line: st = s
        line.append(w)
        if len(" ".join(line)) > 38 or re.search(r"[.?!]$", w):
            cues.append((st, e, " ".join(line))); line = []
    if line: cues.append((st, times[-1][1], " ".join(line)))
with open(out, "w") as f:
    for i, (s, e, t) in enumerate(cues, 1):
        f.write(f"{i}\n{ts(s)} --> {ts(max(e, s + 0.6))}\n{t}\n\n")
print(len(cues), "captions")

"""List sentence spans (1-6 sentences) whose length fits a range, to choose Short clips.
usage: tt_short_pick.py timeline.json [max_start_s] [min_len] [max_len]
default range 7.5-10 s (old style); owner plan 12 Nov 2026: use 18.2 38.2 (+1.8 s end card = 20-40 s)."""
import json, re, sys
tl = json.load(open(sys.argv[1])); lim = float(sys.argv[2]) if len(sys.argv) > 2 else 1e9
lo = float(sys.argv[3]) if len(sys.argv) > 3 else 7.5
hi = float(sys.argv[4]) if len(sys.argv) > 4 else 10.0
words = [w for s in tl for w in s.get("words", [])]
sents, cur = [], []
for w in words:
    cur.append(w)
    if re.search(r"[.?!]$", w["w"]): sents.append(cur); cur = []
if cur: sents.append(cur)
for i in range(len(sents)):
    for k in range(1, 7):
        span = [w for s in sents[i:i + k] for w in s]
        if not span or span[0]["s"] > lim: continue
        d = span[-1]["e"] - span[0]["s"] + 0.37
        if lo <= d <= hi:
            print(f"{span[0]['s']:7.2f} {d:5.2f}s | " + " ".join(w["w"] for w in span))

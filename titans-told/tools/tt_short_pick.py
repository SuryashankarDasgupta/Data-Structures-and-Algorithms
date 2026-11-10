"""List sentence spans (and 2-sentence spans) of 7.5-10 s from a timeline, to choose Short clips."""
import json, re, sys
tl = json.load(open(sys.argv[1])); lim = float(sys.argv[2]) if len(sys.argv) > 2 else 1e9
words = [w for s in tl for w in s.get("words", [])]
sents, cur = [], []
for w in words:
    cur.append(w)
    if re.search(r"[.?!]$", w["w"]): sents.append(cur); cur = []
if cur: sents.append(cur)
for i in range(len(sents)):
    for k in (1, 2):
        span = [w for s in sents[i:i + k] for w in s]
        if not span or span[0]["s"] > lim: continue
        d = span[-1]["e"] - span[0]["s"] + 0.37
        if 7.5 <= d <= 10.0:
            print(f"{span[0]['s']:7.2f} {d:5.2f}s | " + " ".join(w["w"] for w in span))

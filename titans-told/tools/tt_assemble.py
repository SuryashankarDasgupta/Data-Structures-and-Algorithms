"""Assemble takes -> narration.wav with per-section tempo x per-paragraph pace ({fast}/{steady}/{slow}),
pauses ([[pause]] 1.0 s, [[beat]] 0.5 s); write timeline.json (absolute word times).
Opening rule (owner, 6 Nov 2026: "no long pauses in first 30 sec — viewers leave"): in the HOOK and QUESTION
sections (and the gap into the first act) every silence is trimmed to at most TIGHT_CAP seconds; only truly
quiet audio is cut, so no word is clipped."""
import json, subprocess, sys, os
vo = sys.argv[1]; tempo = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
PACE = {"fast": 1.06, "steady": 1.0, "slow": 0.92}
TIGHT_SECTIONS = ("HOOK", "QUESTION"); TIGHT_CAP = 0.25
man = json.load(open(f"{vo}/manifest.json"))
SR = 44100; files = []; t = 0.0; timeline = []; prev = None
def sil(d, name):
    p = f"{vo}/{name}.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=mono", "-t", str(d), p]); return p
def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]))
def piece(src, a, b, f, out, trim_start, trim_end):
    flt = [f"atrim={a}:{b}" if b else f"atrim=start={a}", "asetpts=PTS-STARTPTS", f"atempo={f}"]
    if trim_start: flt.append("silenceremove=start_periods=1:start_threshold=-50dB")
    if trim_end: flt += ["areverse", "silenceremove=start_periods=1:start_threshold=-50dB", "areverse"]
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-af", ",".join(flt), "-ar", str(SR), "-ac", "1", out])
    return out
for k, c in enumerate(man):
    if "pause" in c:
        files.append(sil(c["pause"], f"sil_p{k}")); t += c["pause"]; continue
    if prev is not None and prev != c["section"]:
        files.append(sil(0.45, f"sil_s{k}")); t += 0.45
    base = tempo.get(c["section"], 1.0)
    src = f"{vo}/{c['file']}"; W = c.get("words", [])
    starts = c.get("para_starts") or [0]
    paces = [p["pace"] for p in c.get("paras", [{"pace": "steady"}])]
    # cut points: just before the first word of each paragraph (middle of the preceding gap)
    cuts = [0.0]
    for j in starts[1:]:
        if 0 < j < len(W):
            cuts.append(round((W[j - 1]["e"] + W[j]["s"]) / 2, 3))
    cuts.append(None)
    segs = []
    for i in range(len(cuts) - 1):
        f = max(0.88, min(1.12, base * PACE.get(paces[min(i, len(paces) - 1)], 1.0)))
        out = piece(src, cuts[i], cuts[i + 1], f, f"{vo}/proc_{k:02d}_{i:02d}.wav", i == 0, i == len(cuts) - 2)
        segs.append((cuts[i], cuts[i + 1], f, out, dur(out)))
    # word times: map each word into its segment, scaled by that segment's tempo
    lead = None; words = []; seg_t0 = 0.0; offs = []
    for (a, b, f, out, d) in segs:
        offs.append(seg_t0); seg_t0 += d
    first_cut_lead = W[0]["s"] if W else 0.0
    for w in W:
        si = max(i for i, s_ in enumerate(segs) if w["s"] >= s_[0] - 1e-6)
        a, b, f, out, d = segs[si]
        sub = first_cut_lead if si == 0 else a
        words.append({"w": w["w"], "s": round(t + offs[si] + max(0.0, w["s"] - sub) / f, 2),
                      "e": round(t + offs[si] + max(0.0, w["e"] - sub) / f, 2)})
    total = sum(s_[4] for s_ in segs)
    timeline.append({"section": c["section"], "start": round(t, 2), "end": round(t + total, 2),
                     "text": c.get("ref", c["text"]), "words": words})
    files += [s_[3] for s_ in segs]; t += total; prev = c["section"]
open(f"{vo}/list.txt", "w").write("".join(f"file '{os.path.abspath(p)}'\n" for p in files))
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", f"{vo}/list.txt", "-c:a", "pcm_s16le", f"{vo}/narration.wav"])
# --- opening tightener: cap every silence in the first sections (incl. the gap into the first act) ---
import numpy as np
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", f"{vo}/narration.wav", "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                     capture_output=True).stdout
x = np.frombuffer(raw, np.int16).copy()
allw = [(si, w) for si, sec in enumerate(timeline) for w in sec["words"]]
ntight = next((k for k, (si, w) in enumerate(allw) if timeline[si]["section"] not in TIGHT_SECTIONS), len(allw))
win = int(0.02 * SR)
cuts = []
# energy-based: every quiet run (< -38 dBFS, 20 ms windows) before the first word of the first act is trimmed to TIGHT_CAP
limit = allw[ntight][1]["s"] if ntight < len(allw) else len(x) / SR
seg = x[:int(limit * SR)].astype(np.float32) / 32768
n = len(seg) // win
rms = np.sqrt((seg[:n * win].reshape(n, win) ** 2).mean(1)) if n else np.zeros(0)
q = list(rms < 10 ** (-38 / 20)) + [False]
cur = None
for k, v in enumerate(q):
    if v and cur is None: cur = k
    if not v and cur is not None:
        r0, r1 = cur * win / SR, k * win / SR
        if r0 < 0.01:                       # leading silence: keep 0.05 s
            if r1 > 0.05: cuts.append((0.0, r1 - 0.05))
        elif r1 - r0 > TIGHT_CAP:
            mid = (r0 + r1) / 2; ex = (r1 - r0) - TIGHT_CAP
            cuts.append((mid - ex / 2, mid + ex / 2))
        cur = None
removed = 0.0
if cuts:
    keep_parts, last = [], 0
    for c0, c1 in cuts:
        keep_parts.append(x[last:int(c0 * SR)]); last = int(c1 * SR)
    keep_parts.append(x[last:]); x = np.concatenate(keep_parts)
    def shift(tt):
        return tt - sum(min(max(tt - c0, 0), c1 - c0) for c0, c1 in cuts)
    for sec in timeline:
        sec["start"] = round(shift(sec["start"]), 2); sec["end"] = round(shift(sec["end"]), 2)
        for w in sec["words"]:
            w["s"] = round(shift(w["s"]), 2); w["e"] = round(shift(w["e"]), 2)
    removed = sum(c1 - c0 for c0, c1 in cuts); t -= removed
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "-", "-c:a", "pcm_s16le",
                    f"{vo}/narration.wav"], input=x.tobytes())
print(f"opening tightener: {len(cuts)} pauses trimmed to <= {TIGHT_CAP}s, {removed:.2f}s removed")
json.dump(timeline, open(f"{vo}/timeline.json", "w"), indent=1)
words = sum(len(x["words"]) for x in timeline)
print(f"total {t/60:.2f} min, {words} words, {words/(t/60):.0f} wpm")
for x in timeline: print(x["section"], x["start"], x["end"])

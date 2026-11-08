"""Transcribe each take, compare with script text (word-level diff, audio tags ignored), save word timestamps
and the Whisper word index where each paragraph starts (for per-paragraph pace in tt_assemble)."""
import json, sys, re, difflib, subprocess
import numpy as np
def load(p):
    raw = subprocess.run(["ffmpeg","-v","error","-i",p,"-f","s16le","-ac","1","-ar","16000","-"],capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768
from faster_whisper import WhisperModel
vo = sys.argv[1]
man = json.load(open(f"{vo}/manifest.json"))
m = WhisperModel("base.en", device="cpu", compute_type="int8")
TAG = re.compile(r"\[[^\[\]]{1,40}\]")
norm = lambda t: re.findall(r"[a-z0-9]+", TAG.sub(" ", t).lower().replace("’", "'").replace("'", ""))
for c in man:
    if "text" not in c: continue
    segs, _ = m.transcribe(load(f"{vo}/{c['file']}"), word_timestamps=True)
    words = [{"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)} for s in segs for w in s.words]
    c["words"] = words
    ref = c.get("ref", c["text"])
    a = norm(ref)
    hw = [norm(x["w"]) for x in words]                       # tokens per whisper word
    b = [t for x in hw for t in x]
    owner = [i for i, x in enumerate(hw) for _ in x]          # token -> whisper word index
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    c["match"] = round(sm.ratio(), 3)
    bad = [(op, " ".join(a[i1:i2]), " ".join(b[j1:j2])) for op, i1, i2, j1, j2 in sm.get_opcodes()
           if op != "equal" and (i2 - i1 > 2 or j2 - j1 > 2)]
    if c.get("paras"):
        amap = {}
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            for k in range(i2 - i1):
                amap[i1 + k] = j1 + min(k, max(0, j2 - j1 - 1)) if j2 > j1 else j1
        starts, ai = [], 0
        for p in c["paras"]:
            j = min(amap.get(ai, len(b) - 1), len(b) - 1)
            starts.append(owner[j] if b else 0)
            ai += len(norm(p["ref"]))
        c["para_starts"] = starts
    print(c["file"], c["section"], c["match"], bad[:6], flush=True)
json.dump(man, open(f"{vo}/manifest.json", "w"), indent=1)

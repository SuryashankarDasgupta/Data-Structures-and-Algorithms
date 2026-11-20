"""Prosody stats for a voice take: pitch range/variation, loudness variation, phrase-rate variation.
Usage: python3 tt_prosody.py take.mp3 [...]   (flat delivery = low pitch std & low rate std)"""
import subprocess, sys, numpy as np
from faster_whisper import WhisperModel
def load(p, sr=16000):
    raw = subprocess.run(["ffmpeg","-v","error","-i",p,"-f","s16le","-ac","1","-ar",str(sr),"-"],capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768
def f0_track(x, sr=16000, fl=640, hop=160, fmin=70, fmax=300):
    out = []
    for i in range(0, len(x) - fl, hop):
        fr = x[i:i+fl] * np.hanning(fl)
        if np.sqrt((fr**2).mean()) < 0.01: continue
        ac = np.correlate(fr, fr, "full")[fl-1:]
        lo, hi = sr // fmax, sr // fmin
        k = lo + np.argmax(ac[lo:hi])
        if ac[k] / (ac[0] + 1e-9) > 0.45: out.append(sr / k)
    return np.array(out)
m = WhisperModel("base.en", compute_type="int8")
for p in sys.argv[1:]:
    x = load(p); f0 = f0_track(x)
    f0 = np.array([np.median(f0[max(0, i-4):i+5]) for i in range(len(f0))])   # median filter
    st = 12 * np.log2(f0 / np.median(f0)); st = st[np.abs(st) < 9]   # drop octave errors
    hop = 1600; rms = np.array([np.sqrt((x[i:i+hop]**2).mean()) for i in range(0, len(x)-hop, hop)])
    db = 20*np.log10(rms[rms > 0.01] + 1e-9)
    segs, _ = m.transcribe(x, word_timestamps=True)
    segs = list(segs); rates = []
    ws = [w for s in segs for w in s.words]
    # phrases = runs of words split at gaps > 0.25 s (pauses); rate inside each phrase
    ph, cur = [], [ws[0]]
    for a, b in zip(ws, ws[1:]):
        if b.start - a.end > 0.25: ph.append(cur); cur = [b]
        else: cur.append(b)
    ph.append(cur)
    pauses = sum(1 for a, b in zip(ws, ws[1:]) if b.start - a.end > 0.25)
    for c in ph:
        d = c[-1].end - c[0].start
        if len(c) >= 4 and d > 0.8: rates.append(len(c) / d * 60)
    text = " ".join(s.text.strip() for s in segs)
    print(f"{p}: dur {len(x)/16000:.1f}s | pitch std {st.std():.2f} st, range(5-95%) {np.percentile(st,95)-np.percentile(st,5):.1f} st | "
          f"loudness std {db.std():.1f} dB | phrase wpm mean {np.mean(rates):.0f} std {np.std(rates):.0f} (min {min(rates):.0f}, max {max(rates):.0f}) | pauses>0.25s: {pauses}")
    print("   transcript:", text[:400])

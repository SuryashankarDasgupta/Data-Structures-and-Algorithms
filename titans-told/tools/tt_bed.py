"""Procedural original ambient documentary bed (royalty-free). Usage: tt_bed.py out.wav seconds [seed]"""
import sys, numpy as np, wave
out, secs = sys.argv[1], float(sys.argv[2]); seed = int(sys.argv[3]) if len(sys.argv) > 3 else 1
SR = 44100; rng = np.random.default_rng(seed)
n = int(secs * SR); t = np.arange(n) / SR
mid = lambda m: 440 * 2 ** ((m - 69) / 12)
prog = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]]  # Am F C G
bar = 8.0  # seconds per chord
L = np.zeros(n); R = np.zeros(n)
def env(length, a, r):
    e = np.ones(length); ai = int(a * SR); ri = int(r * SR)
    e[:ai] = np.linspace(0, 1, ai); e[-ri:] = np.linspace(1, 0, ri); return e
k = 0
while k * bar < secs:
    ch = prog[k % 4]; s0 = int(k * bar * SR); length = min(int((bar + 2) * SR), n - s0)
    if length <= 0: break
    tt = np.arange(length) / SR; e = env(length, 2.5, 3.0)
    for i, m in enumerate(ch + [ch[0] - 12]):
        f = mid(m); det = 1 + 0.002 * (i - 1.5)
        v = (np.sin(2 * np.pi * f * det * tt) + 0.3 * np.sin(2 * np.pi * 2 * f * tt + i)) * e * 0.08
        pan = 0.3 + 0.4 * (i / 3)
        L[s0:s0 + length] += v * (1 - pan); R[s0:s0 + length] += v * pan
    # soft piano-like notes (arpeggio, every 1s)
    for j in range(8):
        if rng.random() < 0.65:
            m = ch[rng.integers(0, 3)] + 12 * rng.integers(0, 2); f = mid(m)
            p0 = s0 + int(j * SR); pl = min(int(3 * SR), n - p0)
            if pl <= 0: continue
            pt = np.arange(pl) / SR
            v = (np.sin(2 * np.pi * f * pt) + 0.4 * np.sin(4 * np.pi * f * pt) * np.exp(-pt * 3)) * np.exp(-pt * 1.6) * 0.07
            L[p0:p0 + pl] += v * 0.55; R[p0:p0 + pl] += v * 0.45
    k += 1
# low pulse (heartbeat-ish), subtle
pulse = np.sin(2 * np.pi * 55 * t) * np.exp(-((t % 1.0) * 6)) * 0.05
L += pulse; R += pulse
# simple reverb via feedback delays
for d, g in [(0.113, 0.35), (0.271, 0.25), (0.419, 0.18)]:
    di = int(d * SR); L[di:] += g * R[:-di]; R[di:] += g * L[:-di]
fade = int(3 * SR); 
for ch_ in (L, R): ch_[:fade] *= np.linspace(0, 1, fade); ch_[-fade:] *= np.linspace(1, 0, fade)
st = np.stack([L, R], 1); st = st / np.abs(st).max() * 0.6
w = wave.open(out, "wb"); w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
w.writeframes((st * 32767).astype(np.int16).tobytes()); w.close()

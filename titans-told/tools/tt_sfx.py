#!/usr/bin/env python3
"""Titans Told sound effects track (owner decision 17 Nov 2026: "Yes, build all into the routines including SFX",
after the end-to-end scan of CEOzoned's NVIDIA and Coca-Cola videos: whooshes on transitions, cash-register dings on
money moments, stamps/thuds on headlines, all light and under the voice).

The effects are synthesised here (numpy, no downloads, no licences needed) and placed from spec.json:
  - whoosh   : every chapter change (tracker starts) and every 3rd cut between image shots (soft)
  - pop      : a scene with a kinetic number or kicker text (the text pop)
  - ding     : a "card" scene (era / year card) and the end of each counter's count-up
  - cash     : a counter, bars or linechart scene whose prefix/unit is money ($ or B/M/T with $)
  - thud     : a "headline" or "document" scene
  - tick     : a "timeline" scene
Never within 0.35 s of another effect, never in the first 0.5 s.

usage (run in work/ after tt_cues/tt_score, before tt_compose):
  python3 ../tools/tt_sfx.py spec.json vo/voice.mp3 [--gain -4] [--out sfx.wav]
Writes sfx.wav (48 kHz stereo, same length as the narration) and sets spec["sfx"]="sfx.wav" and
spec["sfx_gain_db"] (default -4) so tt_compose mixes it under the voice. Check: `ffmpeg -i final.mp4 -af ebur128`.
"""
import json, os, subprocess, sys, wave
import numpy as np

SR = 48000
RNG = np.random.default_rng(11)


def env(n, a=0.01, r=0.2):
    t = np.arange(n) / SR
    e = np.minimum(1.0, t / max(a, 1e-4)) * np.exp(-np.maximum(0, t - a) / max(r, 1e-4))
    return e


def lowpass(x, k):
    k = max(1, int(k))
    return np.convolve(x, np.ones(k) / k, mode="same")


def whoosh():
    n = int(0.55 * SR); t = np.arange(n) / SR
    noise = RNG.normal(0, 1, n)
    # sweep: blend a heavy and a light low-pass so the sound rises then falls in brightness
    lo, hi = lowpass(noise, 40), lowpass(noise, 6)
    sweep = np.sin(np.pi * t / t[-1])
    x = lo * (1 - sweep) + hi * sweep
    x *= np.sin(np.pi * t / t[-1]) ** 2
    return 0.10 * x / (np.abs(x).max() + 1e-9)


def ding(f=1318.5):
    n = int(0.9 * SR); t = np.arange(n) / SR
    x = (np.sin(2 * np.pi * f * t) + 0.4 * np.sin(2 * np.pi * 2 * f * t) + 0.15 * np.sin(2 * np.pi * 3.01 * f * t))
    return 0.14 * x * env(n, 0.003, 0.28) / 1.55


def cash():
    a = ding(2093.0) * 0.8
    b = np.concatenate([np.zeros(int(0.11 * SR)), ding(2637.0)])
    click = np.zeros(int(0.03 * SR)); click[:200] = RNG.normal(0, 0.25, 200)
    x = np.zeros(max(len(a), len(b)) + len(click))
    x[:len(click)] += click; x[:len(a)] += a; x[:len(b)] += b
    return 0.9 * x


def pop():
    n = int(0.12 * SR); t = np.arange(n) / SR
    f = 900 * np.exp(-t * 18) + 200
    x = np.sin(2 * np.pi * np.cumsum(f) / SR)
    return 0.12 * x * env(n, 0.002, 0.04)


def thud():
    n = int(0.45 * SR); t = np.arange(n) / SR
    x = np.sin(2 * np.pi * (70 + 40 * np.exp(-t * 20)) * t) + 0.3 * lowpass(RNG.normal(0, 1, n), 30)
    return 0.22 * x * env(n, 0.003, 0.12)


def tick():
    n = int(0.05 * SR)
    x = lowpass(RNG.normal(0, 1, n), 2) * env(n, 0.0005, 0.008)
    return 0.15 * x / (np.abs(x).max() + 1e-9)


FX = {"whoosh": whoosh(), "ding": ding(), "cash": cash(), "pop": pop(), "thud": thud(), "tick": tick()}


def probe(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p],
                                capture_output=True, text=True).stdout.strip())


def is_money(sc):
    s = " ".join(str(sc.get(k, "")) for k in ("prefix", "unit", "suffix", "title", "label"))
    return "$" in s


def plan(spec):
    ev = []
    scenes = sorted(spec["scenes"], key=lambda s: s["start"])
    for st in (spec.get("tracker") or {}).get("starts", [])[1:]:
        ev.append((st - 0.15, "whoosh"))
    img_cut = 0
    for i, sc in enumerate(scenes):
        t, typ = sc["start"], sc.get("type", "image")
        if typ == "image" and i > 0 and scenes[i - 1].get("type", "image") == "image":
            img_cut += 1
            if img_cut % 3 == 0:
                ev.append((t - 0.12, "whoosh"))
        if typ == "card":
            ev.append((t + 0.1, "ding"))
        if typ in ("headline", "document"):
            ev.append((t + 0.15, "thud"))
        if typ == "timeline":
            ev.append((t + 0.1, "tick"))
        if typ in ("counter", "bars", "linechart"):
            ev.append((t + 0.2, "cash" if is_money(sc) else "pop"))
            if typ == "counter":
                ev.append((t + min(2.2, (sc["end"] - sc["start"]) * 0.6), "ding"))
        if sc.get("kinetic") or sc.get("kicker"):
            ev.append((t + 0.25, "pop"))
    ev.sort()
    out, last = [], -9.0
    for t, k in ev:
        if t >= 0.5 and t - last >= 0.35:
            out.append((t, k)); last = t
    return out


def main():
    spec_path, narr = sys.argv[1], sys.argv[2]
    gain = float(sys.argv[sys.argv.index("--gain") + 1]) if "--gain" in sys.argv else -4.0
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "sfx.wav"
    spec = json.load(open(spec_path))
    dur = probe(narr)
    buf = np.zeros(int(dur * SR) + SR)
    events = plan(spec)
    for t, k in events:
        x = FX[k]; i = int(t * SR)
        j = min(len(buf), i + len(x))
        if i < len(buf):
            buf[i:j] += x[:j - i]
    buf = np.clip(buf[:int(dur * SR)], -0.95, 0.95)
    pcm = (np.stack([buf, buf], 1) * 32767).astype(np.int16)
    with wave.open(out, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
    spec["sfx"] = os.path.relpath(os.path.abspath(out), os.path.dirname(os.path.abspath(spec_path)))
    spec["sfx_gain_db"] = gain
    json.dump(spec, open(spec_path, "w"), indent=1)
    counts = {}
    for _, k in events:
        counts[k] = counts.get(k, 0) + 1
    print(f"sfx: {len(events)} effects over {dur / 60:.1f} min ({len(events) / max(dur / 60, 0.1):.0f}/min) {counts} -> {out}")


if __name__ == "__main__":
    main()

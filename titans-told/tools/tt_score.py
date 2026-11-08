"""Titans Told score — continuous tension music (owner-approved 7 Nov 2026).
Owner: "keep the effect to retain the tension in the viewers' minds; not sudden effects here and there.
Keep a tension/hooking background music all across." (Earlier tries with booms/whooshes and with scattered foley
were rejected.) So: ONE continuous suspense score under the whole video, generated with ElevenLabs Music, one track
per chapter from the same tension base (TENSION_BASE) and crossfaded over 4 s so it sounds like one piece. The
chapter mood only changes intensity/colour: tense | dark | driving | triumph | reflective (hook + question = tense,
outro = reflective). Music is auto-levelled MUSIC_UNDER_DB (16 dB) under the narration; tt_compose ducks it gently
(duck_ratio 3) while the narrator speaks; it dips softly before each cliffhanger line and at chapter breaks (never
silence). NO sound effects are added unless a scene explicitly carries "sfx" (not used by default).
Any Music API failure falls back to the built-in synth score (printed as "synth").

Usage:  python3 tt_score.py spec.json vo/timeline.json --moods '{"<TRACKER LABEL>":"tense",...}' [--seed N] [--synth]
Writes music/score.wav (+ music/sfx.wav, silent by default) and updates spec.json: music, music_gain_db, duck_ratio=3.
Cache: music/score_parts (per chapter, keyed by mood prompt and length).
"""
import json, os, re, sys, wave, urllib.request
import numpy as np

SR = 44100
MUSIC_UNDER_DB = 16.0  # continuous tension score: present but always under the voice (owner, 7 Nov 2026)
ACTION_UNDER_DB = 14.0  # foley actions 12-18 dB under the voice
AMB_UNDER_DB = 22.0     # ambience beds
rng = np.random.default_rng(7)
mid = lambda m: 440.0 * 2 ** ((m - 69) / 12)


def db(x):
    return 10 ** (x / 20)


def adsr(n, a, r):
    e = np.ones(n); ai = max(1, min(n, int(a * SR))); ri = max(1, min(n, int(r * SR)))
    e[:ai] = np.linspace(0, 1, ai); e[n - ri:] *= np.linspace(1, 0, ri); return e


def tone(f, n, harm=(1.0, 0.3, 0.12), det=0.0):
    t = np.arange(n) / SR
    return sum(a * np.sin(2 * np.pi * f * (k + 1) * (1 + det) * t + k) for k, a in enumerate(harm))


def lowpass(x, fc):
    a = np.exp(-2 * np.pi * fc / SR); y = np.empty_like(x); s = 0.0
    for i in range(len(x)):
        s = (1 - a) * x[i] + a * s; y[i] = s
    return y


def lp_fast(x, fc):
    # FFT brick-ish low-pass (fast for long signals)
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 / (1 + (f / fc) ** 4); return np.fft.irfft(X, len(x))


def hp_fast(x, fc):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 / (1 + (fc / np.maximum(f, 1)) ** 4); return np.fft.irfft(X, len(x))


def band_sweep(n, f0, f1, width=0.5):
    """noise whose spectral band slides from f0 to f1 (STFT mask)."""
    hop, win = 256, 1024
    x = rng.standard_normal(n + win); out = np.zeros(n + win); w = np.hanning(win)
    frames = (n) // hop + 1; freqs = np.fft.rfftfreq(win, 1 / SR); lf = np.log(np.maximum(freqs, 20))
    for i in range(frames):
        p = i / max(1, frames - 1); fc = np.exp(np.log(f0) + (np.log(f1) - np.log(f0)) * p)
        m = np.exp(-((lf - np.log(fc)) ** 2) / (2 * width ** 2))
        seg = x[i * hop:i * hop + win] * w
        out[i * hop:i * hop + win] += np.fft.irfft(np.fft.rfft(seg) * m, win) * w
    return out[:n] / (np.abs(out[:n]).max() + 1e-9)


# ---------------------------------------------------------------- music moods
MOODS = {
    #           root-chords (midi)                                   bpm   pad  bass  arp  kick hat  lp(Hz)
    "tense":     ([[57, 60, 64], [57, 60, 64], [53, 57, 60], [52, 56, 59]], 112, .55, .9, .35, .25, .18, 2600),
    "dark":      ([[50, 53, 57], [46, 50, 53], [43, 46, 50], [45, 49, 52]], 72, .7, .8, .0, .35, .0, 1500),
    "driving":   ([[48, 52, 55], [43, 47, 50], [45, 48, 52], [41, 45, 48]], 116, .45, .7, .6, .45, .3, 5000),
    "triumph":   ([[53, 57, 60], [48, 52, 55], [55, 59, 62], [57, 60, 64]], 104, .65, .75, .55, .5, .25, 6500),
    "reflective": ([[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]], 76, .7, .4, .0, .0, .0, 3000),
}


def mood_track(mood, secs, seed):
    chords, bpm, pad_g, bass_g, arp_g, kick_g, hat_g, lpf = MOODS[mood]
    r = np.random.default_rng(seed); n = int(secs * SR); L = np.zeros(n); R = np.zeros(n)
    beat = 60 / bpm; bar = beat * 4 * (2 if mood in ("dark", "reflective") else 1)
    k = 0
    while k * bar < secs:
        ch = chords[k % 4]; s0 = int(k * bar * SR); ln = min(int((bar + 1.5) * SR), n - s0)
        if ln <= 0: break
        e = adsr(ln, 0.8 if mood != "driving" else 0.3, 1.5)
        for i, m in enumerate(ch + [ch[0] + 12]):  # pad
            v = tone(mid(m), ln, (1, .25, .1, .05), det=0.0015 * (i - 1.5)) * e * 0.06 * pad_g
            pan = 0.25 + 0.5 * (i / 3); L[s0:s0 + ln] += v * (1 - pan); R[s0:s0 + ln] += v * pan
        nb = int(round(bar / beat))
        for b in range(nb):  # bass + kick + hats + arp per beat
            p = s0 + int(b * beat * SR)
            if p >= n: break
            if bass_g:
                steps = 2 if mood in ("tense", "driving") else 1
                for s in range(steps):
                    q = p + int(s * beat / steps * SR); bl = min(int(beat / steps * 0.9 * SR), n - q)
                    if bl > 0:
                        v = tone(mid(ch[0] - 24), bl, (1, .5, .2)) * adsr(bl, .005, .08) * 0.11 * bass_g
                        L[q:q + bl] += v; R[q:q + bl] += v
            if kick_g and (mood != "dark" or b % 2 == 0):
                kl = min(int(0.35 * SR), n - p); tt = np.arange(kl) / SR
                v = np.sin(2 * np.pi * (45 + 60 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 9) * 0.22 * kick_g
                L[p:p + kl] += v; R[p:p + kl] += v
            if hat_g:
                for s in range(2):
                    q = p + int(s * beat / 2 * SR); hl = min(int(0.04 * SR), n - q)
                    if hl > 0:
                        v = r.standard_normal(hl) * np.exp(-np.arange(hl) / SR * 120) * 0.03 * hat_g
                        L[q:q + hl] += v * 0.7; R[q:q + hl] += v
            if arp_g:
                for s in range(4 if mood == "driving" else 2):
                    q = p + int(s * beat / (4 if mood == "driving" else 2) * SR); al = min(int(0.5 * SR), n - q)
                    if al > 0:
                        m = ch[(b * 4 + s) % 3] + 12 * (1 + (s % 2 if mood == "triumph" else 0))
                        v = tone(mid(m), al, (1, .35, .1)) * np.exp(-np.arange(al) / SR * 7) * 0.045 * arp_g
                        pan = 0.3 + 0.4 * r.random(); L[q:q + al] += v * (1 - pan); R[q:q + al] += v * pan
        if mood in ("dark", "reflective"):  # sparse piano
            for j in range(int(bar)):
                if r.random() < (0.45 if mood == "reflective" else 0.25):
                    q = s0 + int(j * SR); pl = min(int(3 * SR), n - q)
                    if pl > 0:
                        m = ch[r.integers(0, 3)] + (12 if mood == "reflective" else 0); pt = np.arange(pl) / SR
                        v = (np.sin(2 * np.pi * mid(m) * pt) + .4 * np.sin(4 * np.pi * mid(m) * pt) * np.exp(-pt * 3)) * np.exp(-pt * 1.4) * 0.06
                        L[q:q + pl] += v * .55; R[q:q + pl] += v * .45
        if mood == "tense":  # high string drone, ticking clock feel
            q = s0; dl = ln; v = tone(mid(ch[2] + 24), dl, (1, .2)) * e * 0.012
            L[q:q + dl] += v; R[q:q + dl] += v * 0.9
        k += 1
    if mood == "dark":
        t = np.arange(n) / SR; sub = np.sin(2 * np.pi * mid(chords[0][0] - 24) * t) * 0.05; L += sub; R += sub
    L = lp_fast(L, lpf); R = lp_fast(R, lpf)
    for d, g in [(0.113, 0.3), (0.271, 0.22), (0.419, 0.15)]:  # small-room reverb
        di = int(d * SR); L[di:] += g * R[:-di]; R[di:] += g * L[:-di]
    st = np.stack([L, R], 1)
    rms = np.sqrt((st ** 2).mean()) + 1e-9
    lvl = {"triumph": 1.12, "reflective": 0.9, "dark": 0.95}.get(mood, 1.0)
    return st / rms * 0.08 * lvl


# Owner, 7 Nov 2026: "keep the effect to retain the tension in the viewers' minds; not sudden effects here and there.
# Keep a tension/hooking background music all across." -> one continuous suspense score; chapters only change its
# intensity and colour, never its tension. No scattered sound effects.
TENSION_BASE = ("suspenseful hooking documentary underscore that keeps the listener on edge, steady hypnotic pulse, "
                "soft ticking percussion, low string ostinato, muted synth bass, sparse felt piano, minor key, slowly building, unresolved")
MOOD_PROMPTS = {
    "tense": TENSION_BASE + ", medium intensity, 100 bpm, ticking clock feel",
    "dark": TENSION_BASE + ", darker and lower, deep drones under the pulse, slower 84 bpm, ominous",
    "driving": TENSION_BASE + ", curious and forward-moving, plucked arpeggio over the pulse, 108 bpm, intrigue rather than fear",
    "triumph": TENSION_BASE + ", determined and rising, strings swelling over the pulse but still unresolved, 104 bpm",
    "reflective": TENSION_BASE + ", quieter and reflective, pulse thinning out, lingering unresolved chords, 80 bpm",
}


def el_music(mood, secs, cache, idx):
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key or "--synth" in sys.argv: return None
    os.makedirs(cache, exist_ok=True); parts = []; left = secs; k = 0
    while left > 0.5:
        ln = min(left, 290.0); import hashlib; hp = hashlib.md5(MOOD_PROMPTS[mood].encode()).hexdigest()[:6]
        p = os.path.join(cache, f"{idx:02d}_{mood}_{hp}_{k}_{int(ln)}.mp3")
        if not os.path.exists(p):
            body = json.dumps({"prompt": "Instrumental documentary underscore for narration: " + MOOD_PROMPTS[mood]
                               + ", instrumental background for a YouTube documentary voice-over, no vocals, no prominent lead melody, no big drops, builds or booms, consistent gentle energy",
                               "music_length_ms": int(max(10.0, ln + 1) * 1000)}).encode()
            req = urllib.request.Request("https://api.elevenlabs.io/v1/music", data=body, method="POST",
                                         headers={"xi-api-key": key, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=600) as r: open(p, "wb").write(r.read())
            except Exception as e:
                print("music API failed, using synth:", str(e)[:120]); return None
        wav = p[:-4] + ".wav"; os.system(f'ffmpeg -v error -y -i "{p}" -ar {SR} -ac 2 "{wav}"')
        w = wave.open(wav); a = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, 2) / 32768.0
        parts.append(a); left -= ln; k += 1
    out = parts[0]
    for a in parts[1:]:  # 2 s crossfade between parts
        x = int(2 * SR); f = np.linspace(0, 1, x)[:, None]
        out = np.concatenate([out[:-x], out[-x:] * (1 - f) + a[:x] * f, a[x:]])
    rms = np.sqrt((out ** 2).mean()) + 1e-9
    lvl = {"triumph": 1.12, "reflective": 0.9, "dark": 0.95}.get(mood, 1.0)
    return out / rms * 0.08 * lvl


# ---------------------------------------------------------------- build
def place(buf, snd, t, gain_db):
    s = int(max(0, t) * SR); e = min(len(buf), s + len(snd))
    if e > s: buf[s:e] += snd[: e - s] * db(gain_db)


def _unused_text_of(sc):
    parts = [str(sc.get(k, "")) for k in ("title", "sub", "caption", "kinetic", "kicker", "label", "text", "prefix", "who", "dateline")]
    for side in ("left", "right"):
        if isinstance(sc.get(side), dict): parts += [str(v) for v in sc[side].values()]
    return " ".join(parts)


def main():
    spec_p, tl_p = sys.argv[1], sys.argv[2]
    moods_arg = json.loads(sys.argv[sys.argv.index("--moods") + 1]) if "--moods" in sys.argv else {}
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 1
    root = os.path.dirname(os.path.abspath(spec_p)); spec = json.load(open(spec_p)); secs = json.load(open(tl_p))
    T = float(spec.get("duration") or secs[-1]["end"] + 1.0); n = int(T * SR) + SR
    tr = spec.get("tracker") or {}; labels, starts = tr.get("items", []), tr.get("starts", [])
    # ---- music: segments by chapter
    defaults = ["driving", "tense", "dark", "triumph", "tense", "driving"]
    q_end = starts[0] if starts else min(30.0, T)
    segs = [(0.0, q_end, "tense")]
    for i, (lab, st) in enumerate(zip(labels, starts)):
        en = starts[i + 1] if i + 1 < len(starts) else tr.get("end", T)
        segs.append((st, en, moods_arg.get(lab, defaults[i % len(defaults)])))
    if tr.get("end", T) < T - 1: segs.append((tr["end"], T, "reflective"))
    music = np.zeros((n, 2)); xf = 4.0; music_src = []
    for k, (a, b, mood) in enumerate(segs):
        a2 = max(0.0, a - xf / 2); b2 = min(T, b + xf / 2)
        trk = el_music(mood, b2 - a2 + 0.5, os.path.join(root, "music", "score_parts"), k)
        music_src.append("elevenlabs" if trk is not None else "synth")
        if trk is None: trk = mood_track(mood, b2 - a2 + 0.5, seed + k)
        ln = int((b2 - a2) * SR)
        if len(trk) < ln: trk = np.concatenate([trk, np.zeros((ln - len(trk), 2))])
        trk = trk[:ln]; e = np.ones(ln); xi = int(xf * SR)
        if k > 0: e[:xi] = np.linspace(0, 1, xi)
        if k < len(segs) - 1: e[-xi:] = np.linspace(1, 0, xi)
        s = int(a2 * SR); music[s:s + ln] += trk * e[:, None]
    # dips under cliffhangers: last ~2.2 s of every section that is followed by a different section
    g = np.ones(n)
    for i, s in enumerate(secs[:-1]):
        if secs[i + 1]["section"] != s["section"] and s["end"] - s["start"] > 8:
            a = int((s["end"] - 2.2) * SR); b = int((s["end"] + 0.4) * SR); r_ = int(0.6 * SR)
            g[a:b] = np.minimum(g[a:b], db(-9)); g[max(0, a - r_):a] = np.minimum(g[max(0, a - r_):a], np.linspace(1, db(-9), a - max(0, a - r_)))
            g[b:b + r_] = np.minimum(g[b:b + r_], np.linspace(db(-9), 1, len(g[b:b + r_])))
    for st in starts:  # brief drop-out at chapter breaks
        a = int((st - 0.5) * SR); b = int((st + 0.7) * SR); r_ = int(0.4 * SR)
        g[a:b] = np.minimum(g[a:b], db(-5)); g[max(0, a - r_):a] = np.minimum(g[max(0, a - r_):a], np.linspace(1, db(-5), a - max(0, a - r_)))
        g[b:b + r_] = np.minimum(g[b:b + r_], np.linspace(db(-5), 1, len(g[b:b + r_])))
    music *= g[:, None]
    fo = int(3 * SR); music[-fo:] *= np.linspace(1, 0, fo)[:, None]; music[: int(0.3 * SR)] *= np.linspace(0, 1, int(0.3 * SR))[:, None]
    # ---- SFX: scene-matched foley (no booms, stings, risers or whooshes)
    cache = os.path.join(root, "music", "sfx_lib"); os.makedirs(cache, exist_ok=True)
    def lufs_arr(a_):
        tmp = os.path.join(cache, "_m.wav"); w = wave.open(tmp, "wb"); w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(a_, -1, 1) * 32767).astype(np.int16).tobytes()); w.close()
        o = os.popen(f'ffmpeg -nostats -i "{tmp}" -af apad=pad_dur=0.5,ebur128=framelog=quiet -f null - 2>&1').read()
        v = re.findall(r"I:\s+(-?[\d.]+) LUFS", o); return float(v[-1]) if v else -70.0
    narr_l = None
    o = os.popen(f'ffmpeg -nostats -i "{os.path.join(root, spec.get("narration", "vo/narration.wav"))}" -af ebur128=framelog=quiet -f null - 2>&1').read()
    narr_l = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", o)[-1])
    def gen(prompt, d):
        import hashlib
        h = hashlib.md5(f"{prompt}|{d}".encode()).hexdigest()[:10]; p = os.path.join(cache, h + ".mp3")
        key = os.environ.get("ELEVENLABS_API_KEY")
        if not os.path.exists(p):
            if not key or "--synth" in sys.argv: return None
            body = json.dumps({"text": prompt + ", realistic foley, clean recording, no music", "duration_seconds": max(0.5, min(22.0, d)), "prompt_influence": 0.55}).encode()
            req = urllib.request.Request("https://api.elevenlabs.io/v1/sound-generation", data=body, method="POST", headers={"xi-api-key": key, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r: open(p, "wb").write(r.read())
            except Exception as e:
                print("sfx failed:", prompt[:40], str(e)[:80]); return None
        wav = p[:-4] + ".wav"
        if not os.path.exists(wav): os.system(f'ffmpeg -v error -y -i "{p}" -ar {SR} -ac 2 "{wav}"')
        w = wave.open(wav); return np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, 2) / 32768.0
    fx = np.zeros((n, 2)); counts = {"action": 0, "amb": 0, "chapter": 0}
    for sc in spec["scenes"]:
        sf = sc.get("sfx")
        if not sf: continue
        if isinstance(sf, str): sf = {"p": sf}
        dur = sc.get("end", sc["start"] + 3) - sc["start"]
        kind = sf.get("kind") or ("amb" if re.search(r"ambien|street|room tone|crowd murmur|traffic|rain|wind|birds|hum\b|night", sf["p"], re.I) else "action")
        d = float(sf.get("d", min(dur, 6.0) if kind == "amb" else 1.0))
        a_ = gen(sf["p"], d)
        if a_ is None: continue
        a_ = a_[: int(d * SR)].copy(); fi = int(0.01 * SR) if kind == "action" else int(0.4 * SR); fo = min(len(a_) // 2, int((0.15 if kind == "action" else 0.6) * SR))
        a_[:fi] *= np.linspace(0, 1, fi)[:, None]; a_[-fo:] *= np.linspace(1, 0, fo)[:, None]
        l = lufs_arr(a_); target = narr_l - (ACTION_UNDER_DB if kind == "action" else AMB_UNDER_DB)
        place(fx, a_, sc["start"] + float(sf.get("at", 0.08 if kind == "action" else 0.0)), max(-40, min(12, target - l)))
        counts[kind] += 1
    thud = gen("soft muffled low felt thud, subtle, like a drum mallet on a soft surface", 1.2) if spec.get("chapter_thud") else None
    if thud is not None:
        l = lufs_arr(thud)
        for st in starts:
            place(fx, thud, st, max(-40, narr_l - 16 - l)); counts["chapter"] += 1
    srcs = "elevenlabs"
    fx = np.clip(fx, -1, 1)
    md = os.path.join(root, "music"); os.makedirs(md, exist_ok=True)
    for name, arr in (("score.wav", music), ("sfx.wav", fx)):
        a = arr[: int(T * SR)]; a = a / max(1.0, np.abs(a).max() / 0.95)
        w = wave.open(os.path.join(md, name), "wb"); w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((a * 32767).astype(np.int16).tobytes()); w.close()
    # auto-level: music sits MUSIC_UNDER_DB below the narration (integrated loudness), before ducking
    def lufs(path):
        o = os.popen(f'ffmpeg -nostats -i "{path}" -af ebur128=framelog=quiet -f null - 2>&1').read()
        return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", o)[-1])
    narr = os.path.join(root, spec.get("narration", "vo/narration.wav"))
    gain = round(lufs(narr) - MUSIC_UNDER_DB - lufs(os.path.join(md, "score.wav")), 1)
    print(f"music level: {gain} dB gain -> {MUSIC_UNDER_DB} dB under the voice (plus gentle ducking while he speaks)")
    spec.update(music="music/score.wav", music_gain_db=gain, duck_ratio=3,
                sfx="music/sfx.wav", sfx_gain_db=spec.get("sfx_gain_db", 0))
    json.dump(spec, open(spec_p, "w"))
    print("moods:", " | ".join(f"{a:.0f}-{b:.0f}s {m}" for a, b, m in segs))
    print("music source:", music_src)
    print("sfx placed:", counts, "| per minute:", round((counts["action"] + counts["amb"]) / max(1, T / 60), 1))


if __name__ == "__main__":
    main()

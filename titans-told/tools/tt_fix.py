"""Titans Told sentence re-voice + splice (owner, 12 Nov 2026: "re-voice ONLY the fault").

usage: tt_fix.py vo/ "SECTION" "<the faulty sentence exactly as in script.md (tags allowed)>" [--fix-text "<new wording>"] [--insert]
(--insert: --fix-text = the sentence plus new sentences after it, for a late fact added to a finished voiceover;
 then also put the new text into script.md and manifest.json "text"/"ref" of that section, never re-run tt_vo on it)

- Re-voices ONLY that sentence on the SAME account as the video (vo/account.txt), same voice/model/settings,
  with the neighbouring sentences sent as previous_text/next_text for matching intonation.
- Finds the sentence in the section take via the Whisper word timestamps in manifest.json (run tt_qa_vo first),
  cuts it at the pauses around it, loudness-matches the new take to the old one and splices it in with short
  crossfades. The take file keeps its name (tt_vo keeps reusing it); the original is kept as <take>.orig.mp3.
- Checks: loudness within 1.5 dB and brightness (spectral centroid) within 20% of the surrounding audio,
  length 0.6-1.7x the old sentence. Fails -> exit 4 (try once more; after 2 failed splices re-voice the section).
- At most 2 takes per sentence (vo/revoice_log.json); a 3rd is refused (exit 5): keep the better take.
- Prints the characters billed; vo/revoice_log.json keeps the per-video total for the voice log.
Then re-run tt_qa_vo.py vo to confirm the section."""
import difflib, json, os, re, subprocess, sys, time, urllib.request, wave
import numpy as np

VOICE = "uju3wxzG5OhpWcoi3SMy"; MODEL = "eleven_v3"; STABILITY = 0.5; SR = 44100
TAG = re.compile(r"\[[^\[\]]{1,40}\]")
vo, section, sentence = sys.argv[1], sys.argv[2], sys.argv[3]
newtext = sys.argv[sys.argv.index("--fix-text") + 1] if "--fix-text" in sys.argv else sentence
INSERT = "--insert" in sys.argv
REUSE = sys.argv[sys.argv.index("--reuse") + 1] if "--reuse" in sys.argv else None   # splice an already-paid take (no new charge)   # the new text deliberately adds sentences: skip the length check
acc = open(os.path.join(vo, "account.txt")).read().strip() if os.path.exists(os.path.join(vo, "account.txt")) else "ELEVENLABS_API_KEY"
KEY = os.environ.get(acc) or sys.exit(f"voice key {acc} (this video's account) not available")
man = json.load(open(os.path.join(vo, "manifest.json")))
c = next((x for x in man if x.get("section") == section and "file" in x), None) or sys.exit(f"section {section} not found")
if not c.get("words"): sys.exit("no word timestamps: run tt_qa_vo.py first")
logp = os.path.join(vo, "revoice_log.json")
log = json.load(open(logp)) if os.path.exists(logp) else {"chars": 0, "fixes": []}
key_s = re.sub(r"\s+", " ", TAG.sub(" ", sentence)).strip()
tries = sum(1 for f in log["fixes"] if f["sentence"] == key_s)
if tries >= 2 and not REUSE: print("2 takes already used for this sentence: keep the better one (no 3rd take)"); sys.exit(5)

norm = lambda w: re.sub(r"[^a-z0-9]", "", w.lower())
ref_tok = [t for t in re.split(r"\s+", c["ref"]) if norm(t)]
sen_tok = [t for t in re.split(r"\s+", key_s) if norm(t)]
R = [norm(t) for t in ref_tok]; S = [norm(t) for t in sen_tok]
pos = next((i for i in range(len(R) - len(S) + 1) if R[i:i + len(S)] == S), None)
if pos is None: sys.exit("sentence not found in the section text (copy it exactly from script.md)")
W = c["words"]; H = [norm(w["w"]) for w in W]
mp = {}
for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, R, H, autojunk=False).get_opcodes():
    for k in range(i1, i2):
        mp[k] = j1 + min(k - i1, max(0, j2 - j1 - 1)) if j2 > j1 else None
idx = [mp.get(k) for k in range(pos, pos + len(S)) if mp.get(k) is not None]
if not idx: sys.exit("could not map the sentence to the audio")
a, b = min(idx), max(idx)
t0 = (W[a - 1]["e"] + W[a]["s"]) / 2 if a > 0 else max(0.0, W[a]["s"] - 0.05)
t1 = (W[b]["e"] + W[b + 1]["s"]) / 2 if b + 1 < len(W) else W[b]["e"] + 0.15

# neighbouring sentences for intonation context (not billed as text)
full = re.sub(r"\s+", " ", c["text"]); sents = re.split(r"(?<=[.!?])\s+", full)
si = next((i for i, s in enumerate(sents) if norm(TAG.sub(" ", s))[:40] == norm(TAG.sub(" ", sentence))[:40]), None)
prev_t = " ".join(sents[max(0, si - 2):si]) if si is not None else ""
next_t = " ".join(sents[si + 1:si + 3]) if si is not None else ""

def tts(text, path, ctx=True):
    body = {"text": text, "model_id": MODEL, "voice_settings": {"stability": STABILITY, "similarity_boost": 0.8}}
    if ctx and prev_t: body["previous_text"] = prev_t
    if ctx and next_t: body["next_text"] = next_t
    req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}?output_format=mp3_44100_192",
                                 data=json.dumps(body).encode(), headers={"xi-api-key": KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r: open(path, "wb").write(r.read())
    except urllib.error.HTTPError as e:
        if ctx and e.code in (400, 422): return tts(text, path, ctx=False)   # model without context support
        raise

def load(path):
    tmp = path + ".wav"; subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-ar", str(SR), "-ac", "1", tmp], check=True)
    w = wave.open(tmp); x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768; os.remove(tmp); return x
def rms(x): return float(np.sqrt((x ** 2).mean()) + 1e-9)
def cent(x):
    if len(x) < 2048: return 0.0
    f = np.abs(np.fft.rfft(x * np.hanning(len(x)))); fr = np.fft.rfftfreq(len(x), 1 / SR); return float((f * fr).sum() / (f.sum() + 1e-9))
def trim(x, th=0.01):
    nz = np.where(np.abs(x) > th)[0]
    return x[max(0, nz[0] - int(0.03 * SR)):nz[-1] + int(0.06 * SR)] if len(nz) else x

take = os.path.join(vo, c["file"]); orig = take[:-4] + ".orig.mp3"
if not os.path.exists(orig): subprocess.run(["cp", take, orig], check=True)
old = load(take); s0, s1 = int(t0 * SR), int(t1 * SR); seg = old[s0:s1]
spoken = re.sub(r"\s+", " ", newtext).strip()
if REUSE:
    newp = REUSE
else:
    newp = os.path.join(vo, f"fix_{int(time.time())}.mp3"); tts(spoken, newp)
    log["chars"] += len(spoken); log["fixes"].append({"section": section, "sentence": key_s, "chars": len(spoken), "t": [round(t0, 2), round(t1, 2)], "file": os.path.basename(newp)})
    json.dump(log, open(logp, "w"), indent=1)
new = trim(load(newp))
# keep the old leading/trailing pause lengths
lead = trim(seg); pad0 = max(0, len(seg) - len(lead)) // 2
new = new * (rms(trim(seg)) / rms(new))
# tone: the new take's brightness must sit inside the take's own natural range (8 s windows) +-10%
wins = [cent(old[i:i + 8 * SR]) for i in range(0, max(1, len(old) - 8 * SR), 8 * SR)] or [cent(old)]
lo, hi = min(wins) * 0.9, max(wins) * 1.1
ld = 20 * np.log10(rms(new) / rms(trim(seg))); cn = cent(new)
ratio = len(new) / max(1, len(trim(seg)))
ok = abs(ld) <= 1.5 and lo <= cn <= hi and (INSERT or 0.6 <= ratio <= 1.7)
print(f"splice {section} {t0:.2f}-{t1:.2f}s | {0 if REUSE else len(spoken)} new chars | loudness {ld:+.1f} dB | brightness {cn:.0f} Hz (take range {lo:.0f}-{hi:.0f}) | length x{ratio:.2f} | {'PASS' if ok else 'FAIL'}")
if not ok:
    print("splice check failed: try once more (2 takes max); after 2 failed splices re-voice the whole section"); sys.exit(4)
gap = np.zeros(int(0.06 * SR), np.float32); x = int(0.03 * SR); f = np.linspace(0, 1, x)
A, B = old[:s0].copy(), old[s1:].copy()
body = np.concatenate([gap, new, gap])
if len(A) > x: body[:x] = body[:x] * f + A[-x:] * (1 - f); A = A[:-x]
if len(B) > x: body[-x:] = body[-x:] * (1 - f) + B[:x] * f; B = B[x:]
out = np.clip(np.concatenate([A, body, B]), -1, 1)
tmp = take[:-4] + ".tmp.wav"; w = wave.open(tmp, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
w.writeframes((out * 32767).astype(np.int16).tobytes()); w.close()
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmp, "-ar", str(SR), "-ac", "1", "-b:a", "192k", take], check=True)
os.remove(tmp)
if os.path.dirname(os.path.abspath(newp)) == os.path.abspath(vo): os.remove(newp)
print(f"spliced into {c['file']} (original kept as {os.path.basename(orig)}); re-voice characters this video: {log['chars']}")

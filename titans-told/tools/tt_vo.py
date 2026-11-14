"""Titans Told voiceover: script.md -> per-section ElevenLabs takes + manifest.json

Script markup (v2, owner request 6 Nov 2026: voice must rise and fall, never flat):
  [[SECTION | ...]]   section tag (own line)          [[pause]] = 1.0 s silence   [[beat]] = 0.5 s silence
  {fast} {steady} {slow}  at the START of a paragraph = pace for that paragraph (applied in tt_assemble)
  [tense] [hushed] [curious] [warm] [urgent] [ominous] [emphatic] [quietly] [building intensity] [short pause] ...
                      inline eleven_v3 audio tags = emotion/delivery; sent to TTS, never spoken; stripped for QA.
"""
import hashlib, json, os, re, subprocess, sys, time, urllib.request
VOICE = "uju3wxzG5OhpWcoi3SMy"; MODEL = "eleven_v3"; STABILITY = 0.5
TAG = re.compile(r"\[[^\[\]]{1,40}\]")
PACE = re.compile(r"^\s*\{(fast|steady|slow)\}\s*")
script, outdir = sys.argv[1], sys.argv[2]
os.makedirs(outdir, exist_ok=True)
# Voice account (owner decision 12 Nov 2026): TT_EL_KEY names the env var holding the key
# (ELEVENLABS_API_KEY_2 = second account, ELEVENLABS_API_KEY_3 = third account (owner, 14 Nov 2026),
# ELEVENLABS_API_KEY = main Pro). One video = one account:
# the first run records the account in vo/account.txt and later runs refuse a different one.
KEYVAR = os.environ.get("TT_EL_KEY", "ELEVENLABS_API_KEY")
if KEYVAR not in ("ELEVENLABS_API_KEY", "ELEVENLABS_API_KEY_2", "ELEVENLABS_API_KEY_3") or not os.environ.get(KEYVAR):
    raise SystemExit(f"voice key {KEYVAR} not available")
acc = os.path.join(outdir, "account.txt")
if os.path.exists(acc) and open(acc).read().strip() != KEYVAR:
    raise SystemExit(f"this video was voiced on {open(acc).read().strip()}; never mix accounts in one video "
                     f"(re-voice the whole video on one account by deleting {outdir}/t_*.mp3 and {acc})")
open(acc, "w").write(KEYVAR)
NEW_CHARS = 0
s = open(script).read()
parts = re.split(r"^\[\[(.*?)\]\]\s*$", s, flags=re.M)
chunks = []
name = "INTRO"
for i in range(1, len(parts), 2):
    tag, body = parts[i].strip(), parts[i + 1]
    if tag in ("pause", "beat"):
        chunks.append({"pause": 1.0 if tag == "pause" else 0.5})
    else:
        name = tag.split("|")[0].strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]
    if not paras:
        continue
    pl = []
    for p in paras:
        m = PACE.match(p)
        pace = m.group(1) if m else "steady"
        p = PACE.sub("", p)
        ref = re.sub(r"\s+", " ", TAG.sub(" ", p)).strip()
        pl.append({"pace": pace, "tts": p, "ref": ref})
    chunks.append({"section": name, "text": "\n\n".join(x["tts"] for x in pl),
                   "ref": " ".join(x["ref"] for x in pl), "paras": [{"pace": x["pace"], "ref": x["ref"]} for x in pl]})
def tts(text, path):
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}?output_format=mp3_44100_192",
        data=json.dumps({"text": text, "model_id": MODEL,
                         "voice_settings": {"stability": STABILITY, "similarity_boost": 0.8}}).encode(),
        headers={"xi-api-key": os.environ[KEYVAR], "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                open(path, "wb").write(r.read()); return
        except Exception as e:
            print("retry", attempt, e, flush=True); time.sleep(5)
    raise SystemExit("TTS failed")
def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", p]).strip())
for c in chunks:
    if "text" not in c: continue
    c["file"] = "t_" + hashlib.sha1(c["text"].encode()).hexdigest()[:10] + ".mp3"; p = os.path.join(outdir, c["file"])
    if not os.path.exists(p):
        assert len(c["text"]) <= 4800, c["section"]
        tts(c["text"], p); NEW_CHARS += len(c["text"])
    c["dur"] = dur(p); w = len(re.findall(r"[A-Za-z0-9'’.,$-]+", c["ref"]))
    c["wpm"] = round(w / (c["dur"] / 60)); print(c["file"], c["section"], len(c["text"]), f'{c["dur"]:.1f}s', c["wpm"], "wpm",
                                                 "paces:", "".join(x["pace"][0] for x in c["paras"]), flush=True)
json.dump(chunks, open(os.path.join(outdir, "manifest.json"), "w"), indent=1)
print(f"voice account: {KEYVAR} | new characters this run: {NEW_CHARS}")

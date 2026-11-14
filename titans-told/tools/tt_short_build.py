"""Titans Told Short with its OWN fast narration (owner, 10 Nov 2026: "in the Shorts just keep the absolute
twisted/shocked/mind-boggling part so viewers click into the long form, and keep the pace higher so more words are
covered, yet not sounding bad"; Shorts are 8-10 s).

  python3 tt_short_build.py out.mp4 --line "[tense] <28-34 words: the single most shocking twist>" \
      --images img4k/s12.png img4k/s34.png img4k/s51.png --headline "3 DAYS FROM|BANKRUPTCY" --brand TESLA \
      [--music music/score.wav --music-at 120] [--fix "It's=its" --fix "that's=that"] [--work shorts/work]

Voices the line with ElevenLabs eleven_v3 (Michael C. Vincent), speeds it up with a pitch-preserving atempo so it
lands at about 200-210 words a minute and fits 8-10 s (tempo capped at 1.22 so it never sounds rushed; if the line
is still longer than 9.7 s it refuses: shorten the line), gets word timings with faster-whisper, builds a 16:9
source clip from the images (slow push-in, the line's score bed 16 dB under the voice), then renders the vertical
Short with tt_short.py (headline, word-by-word captions, FULL STORY card).
"""
import argparse, hashlib, json, os, re, subprocess, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
VOICE = "uju3wxzG5OhpWcoi3SMy"


def dur_of(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out"); ap.add_argument("--line", required=True)
    ap.add_argument("--images", nargs="+", required=True)
    ap.add_argument("--headline", required=True); ap.add_argument("--brand", default="")
    ap.add_argument("--music"); ap.add_argument("--music-at", type=float, default=60.0)
    ap.add_argument("--fix", action="append", default=[]); ap.add_argument("--work", default=None)
    ap.add_argument("--wpm", type=float, default=205.0)
    a = ap.parse_args()
    work = a.work or os.path.splitext(a.out)[0] + "_work"
    os.makedirs(work, exist_ok=True)
    h = hashlib.sha1(a.line.encode()).hexdigest()[:10]
    raw = os.path.join(work, f"vo_{h}.mp3")
    if not os.path.exists(raw):
        body = json.dumps({"text": a.line, "model_id": "eleven_v3", "voice_settings": {"stability": 0.5, "similarity_boost": 0.8}}).encode()
        req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}?output_format=mp3_44100_192", data=body,
                                     headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"], "Content-Type": "application/json"})
        open(raw, "wb").write(urllib.request.urlopen(req, timeout=180).read())
    spoken = re.sub(r"\[[^\]]*\]", "", a.line)
    nwords = len(spoken.split())
    d0 = dur_of(raw)
    wpm0 = nwords / d0 * 60
    tempo = min(1.22, max(1.0, a.wpm / wpm0, d0 / 9.6))
    fast = os.path.join(work, f"vo_{h}_fast.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", raw, "-af", f"atempo={tempo:.4f},silenceremove=start_periods=1:start_threshold=-45dB", "-ar", "44100", fast], check=True)
    d = dur_of(fast)
    print(f"words {nwords} · raw {d0:.2f}s ({wpm0:.0f} wpm) · tempo {tempo:.3f} · final {d:.2f}s ({nwords / d * 60:.0f} wpm)")
    if d > 9.7:
        sys.exit("line too long for a 8-10 s Short even at the speed cap: cut a few words")
    # word timings
    import numpy as np
    from faster_whisper import WhisperModel
    pcm = subprocess.check_output(["ffmpeg", "-v", "error", "-i", fast, "-f", "f32le", "-ac", "1", "-ar", "16000", "-"])
    audio = np.frombuffer(pcm, np.float32)
    segs, _ = WhisperModel("base.en", device="cpu", compute_type="int8").transcribe(audio, word_timestamps=True)
    words = [{"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)} for s in segs for w in s.words]
    merged = []  # glue Whisper's split tokens back together ("28" ".6%" -> "28.6%", "one" "-day" -> "one-day", "Model 3's" -> "Model 3s")
    for w in words:
        if merged and re.match(r"^([-.,%]|[.,]\d)", w["w"]):
            merged[-1]["w"] += w["w"]; merged[-1]["e"] = w["e"]
        else:
            merged.append(dict(w))
    words = merged
    for w in words:
        w["w"] = re.sub(r"(\d)'s\b", r"\1s", w["w"])
    fixes = dict(f.split("=", 1) for f in a.fix)
    for w in words:
        if w["w"] in fixes:
            w["w"] = fixes[w["w"]]
    tl = os.path.join(work, "timeline.json")
    json.dump([{"section": "SHORT", "start": 0, "end": d, "text": " ".join(w["w"] for w in words), "words": words}], open(tl, "w"))
    print("captions:", " ".join(w["w"] for w in words))
    # 16:9 source clip
    D = d + 0.45
    per = D / len(a.images)
    inputs, parts = [], []
    for i, im in enumerate(a.images):
        inputs += ["-loop", "1", "-t", f"{per:.3f}", "-i", im]
        n = int(per * 30) + 1
        parts.append(f"[{i}:v]scale=3840:-2,zoompan=z='1+0.12*on/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s=2560x1440:fps=30,"
                     f"trim=duration={per:.3f},setpts=PTS-STARTPTS[v{i}]")
    nv = len(a.images)
    fc = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(nv)) + f"concat=n={nv}:v=1:a=0[v];[{nv}:a]apad=whole_dur={D:.3f}[vo]"
    extra = []
    if a.music:
        extra = ["-i", a.music]
        fc += f";[{nv + 1}:a]atrim=start={a.music_at}:duration={D:.3f},asetpts=PTS-STARTPTS,volume=0.16[bed];[vo][bed]amix=inputs=2:normalize=0[a]"
    else:
        fc += ";[vo]anull[a]"
    src = os.path.join(work, "src.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y"] + inputs + ["-i", fast] + extra + ["-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-t", f"{D:.3f}", src], check=True)
    subprocess.run([sys.executable, os.path.join(HERE, "tt_short.py"), src, tl, a.out, "--start", "0", "--end", f"{min(9.95, d + 0.3):.2f}",
                    "--headline", a.headline, "--brand", a.brand], check=True)


if __name__ == "__main__":
    main()

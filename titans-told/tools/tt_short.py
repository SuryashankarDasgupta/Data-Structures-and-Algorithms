"""Titans Told Shorts: cut an 8-10 s vertical Short (1080x1920) from a finished long video.

Owner, 10 Nov 2026: "build Shorts for all videos ... the Shorts duration should be 8-10 seconds".

Usage:
  python3 tt_short.py final.mp4 vo/timeline.json out.mp4 --from "Yet the logo" --to "thirty-five dollars" \
      --headline "NIKE'S LOGO|COST $35" [--brand NIKE] [--start 12.3 --end 21.0]

  --from / --to   phrases matched against the Whisper words in timeline.json (case/punctuation-insensitive);
                  the clip runs from the first word of --from to the last word of --to (+0.25 s tail).
  --start/--end   explicit seconds instead of phrases.
  --headline      big caps text in the top band; "|" splits lines (2 lines max recommended).
Default 8.0-10.0 s (old style). Owner plan 12 Nov 2026: cut 20-40 s Shorts with --min-len 20 --max-len 40 --tail 1.8 (end card after the last word); shorter clips are held on the last frame, longer ones are refused
(pick a tighter sentence). Layout: blurred full-bleed background, the 16:9 picture full width in the middle
(tracker band cropped off), word-by-word captions under it (current word gold), and a closing
"FULL STORY ON THE CHANNEL" call to action in the last 1.6 s. Audio = the original mix, normalised to -14 LUFS.
"""
import argparse, json, os, re, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "..", "fonts", "Inter.ttf")
W, H, FPS = 1080, 1920, 30
FG_H = 608  # 16:9 picture at full width
FG_Y = 640
CREAM, GOLD, RED, INK = (246, 238, 222), (242, 184, 28), (224, 51, 43), (12, 12, 16)


def font(size, weight="Black"):
    f = ImageFont.truetype(FONT, size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


def norm(s):
    return re.sub(r"[^a-z0-9$%]", "", s.lower())


def all_words(tl):
    out = []
    for sec in tl:
        out += sec.get("words", [])
    return out


def find_phrase(words, phrase, after=0.0, last=False):
    toks = [norm(t) for t in phrase.split() if norm(t)]
    seq = [norm(w["w"]) for w in words]
    for i in range(len(seq) - len(toks) + 1):
        if words[i]["s"] < after - 0.01:
            continue
        if all(seq[i + k].startswith(toks[k]) or toks[k].startswith(seq[i + k]) for k in range(len(toks))):
            return words[i + len(toks) - 1]["e"] if last else words[i]["s"]
    sys.exit(f"phrase not found in timeline: {phrase!r}")


def outlined(draw, xy, text, f, fill, anchor="mm", sw=None):
    sw = sw or max(4, f.size // 11)
    draw.text(xy, text, font=f, fill=fill + (255,), anchor=anchor, stroke_width=sw, stroke_fill=INK + (255,))


def fit(text, maxw, start, weight="Black"):
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    s = start
    while s > 30:
        f = font(s, weight)
        b = d.textbbox((0, 0), text, font=f, stroke_width=max(4, s // 11))
        if b[2] - b[0] <= maxw:
            return f
        s -= 4
    return font(30, weight)


def headline_layer(text, brand):
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    lines = [l.strip() for l in text.split("|") if l.strip()]
    y = 150
    for i, line in enumerate(lines):
        f = fit(line, W - 90, 118)
        outlined(d, (W // 2, y + f.size // 2), line, f, GOLD if i == len(lines) - 1 else CREAM)
        y += int(f.size * 1.08)
    tag = f"TITANS TOLD{(' · ' + brand) if brand else ''}"
    ft = font(34, "ExtraBold")
    tb = d.textbbox((0, 0), tag, font=ft)
    tw = tb[2] - tb[0]
    d.rounded_rectangle((W // 2 - tw // 2 - 22, 70, W // 2 + tw // 2 + 22, 70 + 52), 26, fill=(10, 14, 26, 220), outline=GOLD + (255,), width=3)
    d.text((W // 2, 96), tag, font=ft, fill=CREAM + (255,), anchor="mm")
    return lay


def caption_layer(chunk, cur):
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if not chunk:
        return lay
    d = ImageDraw.Draw(lay)
    words = [re.sub(r"(\d)\s+([,.]\d)", r"\1\2", re.sub(r"\s+([,.%])", r"\1", w["w"])).upper() for w in chunk]
    f = fit(" ".join(words), W - 100, 92)
    sp = d.textbbox((0, 0), " ", font=f)[2]
    widths = [d.textbbox((0, 0), w, font=f, stroke_width=max(4, f.size // 11))[2] for w in words]
    total = sum(widths) + sp * (len(words) - 1)
    x = (W - total) // 2
    y = FG_Y + FG_H + 150
    for i, w in enumerate(words):
        outlined(d, (x, y), w, f, GOLD if i == cur else CREAM, anchor="lm")
        x += widths[i] + sp
    return lay


def cta_layer():
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    f = font(58)
    t1, t2 = "FULL STORY", "ON THE CHANNEL ▶"
    d.rounded_rectangle((90, 1330, W - 90, 1560), 30, fill=(10, 14, 26, 235), outline=GOLD + (255,), width=5)
    outlined(d, (W // 2, 1395), t1, f, GOLD)
    outlined(d, (W // 2, 1490), t2, font(52), CREAM)
    return lay


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("timeline"); ap.add_argument("out")
    ap.add_argument("--from", dest="frm"); ap.add_argument("--to")
    ap.add_argument("--start", type=float); ap.add_argument("--end", type=float)
    ap.add_argument("--headline", required=True); ap.add_argument("--brand", default="")
    ap.add_argument("--min-len", type=float, default=8.0); ap.add_argument("--max-len", type=float, default=10.0)
    ap.add_argument("--tail", type=float, default=0.0, help="seconds added after the last word for the end card (owner plan 12 Nov: use 1.8)")
    a = ap.parse_args()
    tl = json.load(open(a.timeline))
    words = all_words(tl)
    t0 = a.start if a.start is not None else find_phrase(words, a.frm)
    t1 = a.end if a.end is not None else find_phrase(words, a.to, after=t0, last=True) + 0.25
    t0 = max(0.0, t0 - 0.12)
    dur = t1 - t0
    if dur > a.max_len:
        sys.exit(f"clip is {dur:.2f} s: Shorts must be {a.min_len:g}-{a.max_len:g} s; pick a tighter passage")
    if a.tail == 0 and dur < a.min_len - 2.5:
        sys.exit(f"clip is {dur:.2f} s: too short for a {a.min_len:g}-{a.max_len:g} s Short; pick a longer passage")
    total = max(a.min_len, dur + a.tail)
    print(f"clip {t0:.2f}-{t1:.2f} s = {dur:.2f} s (Short {total:.2f} s)")
    clip_words = [w for w in words if w["s"] >= t0 - 0.05 and w["e"] <= t1 + 0.3]
    # caption chunks of up to 3 words, never across a sentence end
    chunks, cur = [], []
    for w in clip_words:
        cur.append(w)
        if len(cur) == 3 or re.search(r"[.?!,:;]$", w["w"]):
            chunks.append(cur); cur = []
    if cur:
        chunks.append(cur)

    # video layers: blurred cover background + full-width foreground, tracker band (top 6.5 %) cropped off
    vf = (f"[0:v]trim=start={t0}:duration={dur},setpts=PTS-STARTPTS,fps={FPS},crop=iw:ih*0.935:0:ih*0.065,split[a][b];"
          f"[a]scale=-2:{H},crop={W}:{H},boxblur=24:2,eq=brightness=-0.18:saturation=0.85[bg];"
          f"[b]scale={W}:{FG_H}[fg];[bg][fg]overlay=0:{FG_Y},tpad=stop_mode=clone:stop_duration={total - dur:.3f}[v]")
    rd = subprocess.Popen(["ffmpeg", "-v", "error", "-i", a.src, "-filter_complex", vf, "-map", "[v]",
                           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    tmpv = a.out + ".v.mp4"
    wr = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                           "-pix_fmt", "yuv420p", tmpv], stdin=subprocess.PIPE)
    head = headline_layer(a.headline, a.brand)
    cta = cta_layer()
    cache = {}
    n = int(round(total * FPS))
    for i in range(n):
        raw = rd.stdout.read(W * H * 3)
        if len(raw) < W * H * 3:
            break
        t = t0 + i / FPS
        frame = Image.frombytes("RGB", (W, H), raw).convert("RGBA")
        frame.alpha_composite(head)
        if i / FPS >= total - 1.6:
            frame.alpha_composite(cta)
        else:
            key = None
            for ci, ch in enumerate(chunks):
                if ch[0]["s"] - 0.05 <= t <= ch[-1]["e"] + 0.25:
                    wi = max([k for k, w in enumerate(ch) if w["s"] - 0.05 <= t] or [0])
                    key = (ci, wi)
            if key:
                if key not in cache:
                    cache[key] = caption_layer(chunks[key[0]], key[1])
                frame.alpha_composite(cache[key])
        wr.stdin.write(frame.convert("RGB").tobytes())
    wr.stdin.close(); wr.wait()
    rd.stdout.read()  # drain any frames past the Short length so the reader exits cleanly
    rd.wait()
    # audio: original mix for the clip, short fades, padded with silence to the Short length, -14 LUFS
    af = (f"atrim=start={t0}:duration={dur},asetpts=PTS-STARTPTS,afade=t=in:d=0.08,"
          f"afade=t=out:st={max(0, dur - 0.3):.3f}:d=0.3,apad=whole_dur={total:.3f},loudnorm=I=-14:TP=-1.5:LRA=11")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmpv, "-i", a.src, "-map", "0:v", "-map", "1:a",
                    "-af", af, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                    "-t", f"{total:.3f}", "-movflags", "+faststart", a.out], check=True)
    os.remove(tmpv)
    print("saved", a.out)


if __name__ == "__main__":
    main()

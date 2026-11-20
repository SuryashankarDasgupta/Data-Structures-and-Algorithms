#!/usr/bin/env python3
"""Titans Told genuine-source shots (owner decision 20 Nov 2026: "You can add genuine source's screen recording,
genuine news paper cutting, or other genuine researches in all videos to increase authority"; production rules 9r).

Each shot is a REAL page or document, captured live, with the exact quoted line highlighted on it and a SOURCE label.
Nothing is redrawn or retyped: if the quoted line is not on the page, the shot fails and the video keeps its
illustration (so the capture also re-checks the fact).

usage (run in work/, after facts.md and the cues, before tt_sfx/tt_compose):
  python3 ../tools/tt_sources.py sources.txt [--img img] [--anim anim]
  sources.txt, one line per shot:
      sNN_slug | URL | exact quote as it appears on the page | still|scroll
    URL forms:
      https://...                 live page (news article, SEC filing, court/DOJ page, status page, company blog)
      https://....pdf[#page=N]    PDF (court filing, annual report, patent): the page holding the quote, highlighted
      wayback:YYYY:https://...    the Wayback Machine snapshot nearest to YYYY (old articles, defunct pages)
      loc:https://chroniclingamerica.loc.gov/...  Library of Congress newspaper page (public domain), PDF or page
    mode: "still" = screenshot (tt_compose moves the camera over it); "scroll" = a 4 s screen recording that glides
          to the quote and sweeps a highlighter across it (saved as anim/sNN_slug.mp4, which tt_compose plays).
  Writes img/sNN_slug.png (+ anim/sNN_slug.mp4 for scroll) and sources_log.json (url, final url, page title,
  host, accessed UTC, quote, ok/reason) for the description's Sources list and the video record.
  Then add each shot to spec.json as an image scene: {"type": "image", "src": "img/sNN_slug.png", "motion": "in",
  "fx": "none"} at the moment the narration states that fact (from the cues).
Exit codes: 0 all captured; 8 some failed (listed; use the illustration for those).
"""
import datetime as dt, html, json, os, re, subprocess, sys, tempfile
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
JS = os.path.join(HERE, "tt_srccap.js")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
CA = "/root/.ccr/ca-bundle.crt"


def arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def norm(s):
    s = s.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace(" ", " ").replace("ﬁ", "fi").replace("ﬂ", "fl")
    return re.sub(r"\s+", " ", s).strip().lower()


def label_chip(im, text):
    d = ImageDraw.Draw(im, "RGBA")
    size = max(18, im.width // 70)
    f = ImageFont.truetype(FONT, size)
    b = d.textbbox((0, 0), text, font=f)
    pad = size // 2
    x, y = int(im.width * 0.018), im.height - (b[3] - b[1]) - 3 * pad
    d.rounded_rectangle((x, y, x + b[2] - b[0] + 2 * pad + 8, y + b[3] - b[1] + 2 * pad), radius=pad, fill=(17, 17, 17, 225))
    d.rectangle((x, y, x + 8, y + b[3] - b[1] + 2 * pad), fill=(255, 225, 77, 255))
    d.text((x + 8 + pad - b[0], y + pad - b[1]), text, font=f, fill=(255, 255, 255, 255))
    return im


def pdf_shot(url, quote, out_png, date):
    """Download the PDF, find the page with the quote, render it, highlight the words, crop 16:9 around them."""
    page_hint = None
    m = re.search(r"#page=(\d+)", url)
    if m:
        page_hint = int(m.group(1)); url = url.split("#")[0]
    tmp = tempfile.mkdtemp(prefix="ttsrc_")
    pdf = os.path.join(tmp, "doc.pdf")
    r = subprocess.run(["curl", "-sSL", "--max-time", "90", "--cacert", CA, "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                        "-o", pdf, url], capture_output=True, text=True)
    if r.returncode or not os.path.exists(pdf) or open(pdf, "rb").read(5) != b"%PDF-":
        return False, "PDF download failed " + r.stderr[:120], ""
    info = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout
    pages = int(re.search(r"Pages:\s+(\d+)", info).group(1)) if "Pages:" in info else 1
    title = (re.search(r"Title:\s+(.*)", info) or [None, ""])[1].strip() if "Title:" in info else ""
    q = norm(quote).split(" ")
    order = ([page_hint] if page_hint else []) + [p for p in range(1, pages + 1) if p != page_hint]
    for p in order[:400]:
        txt = subprocess.run(["pdftotext", "-f", str(p), "-l", str(p), "-layout", pdf, "-"], capture_output=True, text=True).stdout
        if " ".join(q[:6]) not in norm(txt):
            continue
        bb = subprocess.run(["pdftotext", "-f", str(p), "-l", str(p), "-bbox", pdf, "-"], capture_output=True, text=True).stdout
        pw, ph = [float(x) for x in re.search(r'<page width="([\d.]+)" height="([\d.]+)"', bb).groups()]
        words = [(float(a), float(b), float(c), float(d_), norm(html.unescape(w)))
                 for a, b, c, d_, w in re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', bb)]
        toks = [w[4] for w in words]
        n = min(len(q), 40)
        hit = None
        for i in range(len(toks)):
            if toks[i:i + 6] == q[:6]:
                hit = (i, min(len(toks), i + n)); break
        if not hit:
            continue
        base = os.path.join(tmp, "pg")
        subprocess.run(["pdftoppm", "-f", str(p), "-l", str(p), "-r", "200", "-png", "-singlefile", pdf, base], check=True)
        im = Image.open(base + ".png").convert("RGB")
        sx, sy = im.width / pw, im.height / ph
        hl = Image.new("RGBA", im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(hl)
        sel = words[hit[0]:hit[1]]
        for x0, y0, x1, y1, _ in sel:
            d.rectangle((x0 * sx - 3, y0 * sy - 2, x1 * sx + 3, y1 * sy + 2), fill=(255, 225, 77, 120))
        im = Image.alpha_composite(im.convert("RGBA"), hl).convert("RGB")
        cy = (min(w[1] for w in sel) + max(w[3] for w in sel)) / 2 * sy
        cw = im.width; ch = int(cw * 9 / 16)
        top = int(max(0, min(im.height - ch, cy - ch / 2)))
        crop = im.crop((0, top, cw, min(im.height, top + ch)))
        canvas = Image.new("RGB", (cw, ch), (236, 233, 226)); canvas.paste(crop, (0, 0))
        host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", url).split("/")[0])
        label_chip(canvas, f"SOURCE  {host}  ·  page {p}  ·  accessed {date}")
        canvas.resize((3200, 1800), Image.LANCZOS).save(out_png)
        return True, "", title or f"{host} (PDF, page {p})"
    return False, "quote not found in the PDF", title


def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
        print(__doc__); return
    imgdir, animdir = arg("--img", "img"), arg("--anim", "anim")
    os.makedirs(imgdir, exist_ok=True); os.makedirs(animdir, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    date = f"{now.day} {now.strftime('%b %Y')}"
    log = json.load(open("sources_log.json")) if os.path.exists("sources_log.json") else []
    failed, done = [], 0
    for ln in open(sys.argv[1], encoding="utf-8"):
        if ln.count("|") < 2 or ln.lstrip().startswith("#"):
            continue
        parts = [x.strip() for x in ln.split("|")]
        sid, url, quote = parts[0], parts[1], parts[2]
        mode = parts[3].lower() if len(parts) > 3 and parts[3] else "still"
        png = os.path.join(imgdir, sid + ".png")
        if url.startswith("wayback:"):
            _, yr, rest = url.split(":", 2); url = f"https://web.archive.org/web/{yr}0101000000/{rest}"
        if url.startswith("loc:"):
            url = url[4:]
        entry = {"shot": sid, "url": url, "quote": quote, "mode": mode, "accessed_utc": now.isoformat(timespec="seconds")}
        if re.search(r"\.pdf($|#|\?)", url, re.I):
            ok, why, title = pdf_shot(url, quote, png, date)
            entry.update(ok=ok, reason=why, title=title, final_url=url, mode="still")
        else:
            vdir = tempfile.mkdtemp(prefix="ttvid_")
            job = {"url": url, "quote": quote, "mode": mode, "out_png": png, "out_dir": vdir, "label_date": date}
            r = subprocess.run(["node", JS, json.dumps(job)], capture_output=True, text=True, timeout=180)
            try:
                res = json.loads(r.stdout.strip().splitlines()[-1])
            except Exception:
                res = {"ok": False, "reason": "capture crashed: " + (r.stderr or r.stdout)[-160:]}
            entry.update(ok=res.get("ok", False), reason=res.get("reason", ""), title=res.get("title", ""),
                         final_url=res.get("final_url", url), host=res.get("host", ""))
            if entry["ok"] and mode == "scroll" and res.get("video"):
                mp4 = os.path.join(animdir, sid + ".mp4")
                start = max(0.0, res.get("anim_start_ms", 0) / 1000.0)
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", res["video"], "-t", "4.0",
                                "-vf", "scale=1920:1080,fps=30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                                "-an", mp4], check=False)
                if not os.path.exists(mp4):
                    entry["reason"] = "recording conversion failed; still kept"
            if entry["ok"] and os.path.exists(png):
                im = Image.open(png).convert("RGB")
                if im.size != (3200, 1800):
                    im.resize((3200, 1800), Image.LANCZOS).save(png)
        log = [e for e in log if e.get("shot") != sid] + [entry]
        if entry["ok"]:
            done += 1
        else:
            failed.append(f"{sid}: {entry['reason']}")
            if os.path.exists(png) and not entry["ok"]:
                os.remove(png)
    json.dump(log, open("sources_log.json", "w"), indent=1)
    print(f"sources: {done} captured, {len(failed)} failed -> {imgdir}/, {animdir}/, sources_log.json")
    if failed:
        print("not captured (keep the illustration):\n- " + "\n- ".join(failed)); sys.exit(8)


if __name__ == "__main__":
    main()

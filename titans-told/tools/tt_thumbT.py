"""Titans Told thumbnail, Style T (tension): split danger-vs-success scene + huge shock words.
Owner, 6 Nov 2026: "tension, shock, twist — images and texts that force viewers to click".

Usage:
  python3 tt_thumbT.py base.png out.jpg --left "3 DAYS" --left2 "LEFT" --right "$1T" [--right2 "LATER"] [--brand TESLA] [--leftpos bottom]
  python3 tt_thumbT.py base.png out.jpg --phrase "IT ALMOST" --phrase2 "DIED. TWICE." [--brand TESLA]
  python3 tt_thumbT.py base.png out.jpg --phrase "HOW DID" --phrase2 "IT SURVIVE?" [--brand TESLA]
base.png = 16:9 tension illustration (dark/danger left, golden/success right, no text).
Left words are alarm red, right words gold, all with a thick ink outline + drop shadow so they read at 120 px.
"""
import argparse, os
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "..", "fonts", "Inter.ttf")
RED, GOLD, CREAM, INK = (224, 51, 43), (242, 184, 28), (246, 238, 222), (12, 12, 16)
W, H = 1280, 720
BOXES = []  # every shock word drawn so far, so the topic banner never overlaps one


def font(size, weight="Black"):
    f = ImageFont.truetype(FONT, size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


def fit(d, text, maxw, start, weight="Black"):
    s = start
    while s > 40:
        f = font(s, weight)
        b = d.textbbox((0, 0), text, font=f, stroke_width=max(4, s // 14))
        if b[2] - b[0] <= maxw:
            return f
        s -= 4
    return font(40, weight)


def word(lay, xy, text, f, fill, anchor="la", stroke=None):
    d = ImageDraw.Draw(lay)
    sw = stroke or max(5, f.size // 12)
    sh = Image.new("RGBA", lay.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((xy[0] + 8, xy[1] + 10), text, font=f, fill=(0, 0, 0, 200), anchor=anchor, stroke_width=sw, stroke_fill=(0, 0, 0, 200))
    lay.alpha_composite(sh.filter(ImageFilter.GaussianBlur(6)))
    d.text(xy, text, font=f, fill=fill + (255,), anchor=anchor, stroke_width=sw, stroke_fill=INK + (255,))
    b = d.textbbox(xy, text, font=f, anchor=anchor, stroke_width=sw)
    BOXES.append((b[0], b[1], b[2] + 8, b[3] + 10))  # + drop shadow
    return b


WORDFONT = os.path.join(HERE, "..", "fonts", "Michroma.ttf")


def ensure_wordfont():
    """Michroma (OFL, Google Fonts) for the wordmark and timer digits, fetched on first use."""
    if not os.path.exists(WORDFONT):
        try:  # OFL font from Google Fonts, fetched on first use
            import urllib.request
            os.makedirs(os.path.dirname(WORDFONT), exist_ok=True)
            urllib.request.urlretrieve("https://fonts.gstatic.com/s/michroma/v21/PN_zRfy9qWD8fEagAMg6.ttf", WORDFONT)
        except Exception:
            pass


def brand_wordmark(lay, text, size=84, track=0.42, ytop=None):
    """Automaker-style wordmark: wide-tracked geometric caps, chrome gradient, dark halo, red glow. Not a logo."""
    f = ImageFont.truetype(WORDFONT if os.path.exists(WORDFONT) else FONT, size)
    gap = int(size * track)
    widths = [f.getbbox(ch)[2] - f.getbbox(ch)[0] for ch in text]
    tw = sum(widths) + gap * (len(text) - 1)
    asc = f.getbbox("H")
    th = asc[3] - asc[1]
    x0 = W - tw - 52
    y0 = ytop if ytop is not None else H - th - 54
    mask = Image.new("L", lay.size, 0); md = ImageDraw.Draw(mask)
    x = x0
    for ch, w in zip(text, widths):
        md.text((x - f.getbbox(ch)[0], y0 - asc[1]), ch, font=f, fill=255)
        x += w + gap
    mask = mask.filter(ImageFilter.MaxFilter(7))  # embolden the thin geometric face
    # smoked plate behind the word so it reads on any background (owner, 7 Nov 2026: brand "not clearly visible")
    plate = Image.new("L", lay.size, 0)
    ImageDraw.Draw(plate).rounded_rectangle((x0 - 26, y0 - 18, x0 + tw + 26, y0 + th + 18), 16, fill=200)
    plate = plate.filter(ImageFilter.GaussianBlur(10))
    lay.alpha_composite(Image.merge("RGBA", (Image.new("L", lay.size, 6),) * 3 + (plate,)))
    BOXES.append((x0 - 26, y0 - 18, x0 + tw + 26, y0 + th + 18))
    # red glow, then a solid black ink outline like the other thumbnail words
    glow = mask.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(16))
    red = Image.new("RGBA", lay.size, RED + (0,)); red.putalpha(glow.point(lambda v: min(255, int(v * 1.4))))
    lay.alpha_composite(red)
    ink = mask.filter(ImageFilter.MaxFilter(11))
    lay.alpha_composite(Image.merge("RGBA", (Image.new("L", lay.size, 8),) * 3 + (ink,)))
    # chrome: vertical gradient bright top, steel middle line, light bottom
    grad = Image.new("RGBA", lay.size, (0, 0, 0, 0)); gd = ImageDraw.Draw(grad)
    stops = [(0.0, (255, 255, 255)), (0.45, (214, 220, 228)), (0.52, (120, 128, 140)), (0.7, (200, 206, 214)), (1.0, (250, 250, 252))]
    for yy in range(th + 2):
        t = yy / max(1, th)
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                k = (t - t0) / (t1 - t0); c = tuple(int(c0[i] + (c1[i] - c0[i]) * k) for i in range(3)); break
        gd.line((x0 - 4, y0 + yy, x0 + tw + 4, y0 + yy), fill=c + (255,))
    grad.putalpha(mask)
    lay.alpha_composite(grad)


def danger_glow(lay):
    """Red alarm light bleeding in from the left edge."""
    m = Image.new("L", lay.size, 0); md = ImageDraw.Draw(m)
    md.rectangle((0, 0, 70, H), fill=150); md.rectangle((0, 0, W * 0.45, 40), fill=90)
    m = m.filter(ImageFilter.GaussianBlur(60))
    r = Image.new("RGBA", lay.size, RED + (0,)); r.putalpha(m); lay.alpha_composite(r)


def countdown(lay, digits, label, x=30, y=20):
    """Bomb-timer style panel: small caps label + glowing red digits. Returns right edge x."""
    fd = ImageFont.truetype(WORDFONT if os.path.exists(WORDFONT) else FONT, 64)
    fl = font(24, "ExtraBold")
    d = ImageDraw.Draw(lay)
    db = d.textbbox((0, 0), digits, font=fd); lb = d.textbbox((0, 0), label, font=fl)
    w = max(db[2] - db[0], lb[2] - lb[0]) + 40
    h = (lb[3] - lb[1]) + (db[3] - db[1]) + 44
    d.rounded_rectangle((x, y, x + w, y + h), 14, fill=(8, 8, 12, 230), outline=RED + (255,), width=4)
    d.text((x + 20, y + 12 - lb[1]), label, font=fl, fill=(255, 210, 200, 255))
    dy = y + 12 + (lb[3] - lb[1]) + 12 - db[1]
    glow = Image.new("RGBA", lay.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).text((x + 20, dy), digits, font=fd, fill=RED + (255,), stroke_width=3, stroke_fill=RED + (255,))
    lay.alpha_composite(glow.filter(ImageFilter.GaussianBlur(9)))
    d.text((x + 20, dy), digits, font=fd, fill=(255, 64, 52, 255), stroke_width=1, stroke_fill=(255, 64, 52, 255))
    return x + w


def battery(lay, x, y, h=58):
    """Near-empty battery outline with one red sliver, ink outline."""
    d = ImageDraw.Draw(lay)
    w = int(h * 1.9)
    d.rounded_rectangle((x, y, x + w, y + h), 10, fill=(8, 8, 12, 200), outline=CREAM + (255,), width=6)
    d.rectangle((x + w, y + h * 0.3, x + w + 10, y + h * 0.7), fill=CREAM + (255,))
    d.rounded_rectangle((x + 11, y + 11, x + 11 + w * 0.13, y + h - 11), 4, fill=RED + (255,))


def topic_banner(lay, text, x_left=470, bottom=104):  # clears YouTube's duration badge (bottom-right)
    """Topic strip bottom-right (owner, 7 Nov 2026: keep the video topic in the thumbnail text clearly).
    Dark plate with a gold rule; cream caps with ink outline. Stays right of the left-side words."""
    d = ImageDraw.Draw(lay)
    x1 = W - 36; y1 = H - bottom
    # owner, 8 Nov 2026: the banner must never overlap any other text ("INTEL'S WORST DAY" touched the % of "-29%").
    # Start right of every shock word whose rows meet the banner's rows, keep a 24 px gap, shrink the font to fit.
    left = x_left
    for _ in range(3):
        f = fit(d, text, max(200, x1 - left - 44), 64, "Black")
        b = d.textbbox((0, 0), text, font=f, stroke_width=max(4, f.size // 14))
        tw, th = b[2] - b[0], b[3] - b[1]
        y0 = y1 - th - 30
        clash = [bx for bx in BOXES if bx[1] < y1 + 6 and bx[3] > y0 - 6 and bx[2] + 24 > x1 - tw - 44]
        if not clash:
            break
        left = max(bx[2] for bx in clash) + 24
    x0 = x1 - tw - 44
    clash = [bx for bx in BOXES if bx[1] < y1 + 6 and bx[3] > y0 - 6 and bx[2] + 24 > x0]
    if clash:
        # still no room beside the words: lift the banner just above the words it would touch
        y1 = min(bx[1] for bx in clash) - 14; y0 = y1 - th - 30
        if any(bx[1] < y1 + 6 and bx[3] > y0 - 6 and bx[2] + 24 > x0 and bx[0] - 24 < x1 for bx in BOXES):
            print("WARNING: topic banner could not be placed clear of the other text; shorten the topic line")
    plate = Image.new("RGBA", lay.size, (0, 0, 0, 0)); pd = ImageDraw.Draw(plate)
    pd.rounded_rectangle((x0, y0, x1, y1), 12, fill=(10, 14, 26, 225), outline=GOLD + (255,), width=4)
    lay.alpha_composite(plate)
    word(lay, ((x0 + x1) // 2, (y0 + y1) // 2), text, f, CREAM, anchor="mm", stroke=max(4, f.size // 14))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base"); ap.add_argument("out")
    ap.add_argument("--left"); ap.add_argument("--left2", default="")
    ap.add_argument("--right"); ap.add_argument("--right2", default="")
    ap.add_argument("--phrase"); ap.add_argument("--phrase2", default="")
    ap.add_argument("--brand", default="")
    ap.add_argument("--timer", default="", help='red countdown panel top-left, e.g. "72:00:00"')
    ap.add_argument("--timerlabel", default="UNTIL BANKRUPTCY")
    ap.add_argument("--battery", action="store_true", help="red near-empty battery icon beside the timer")
    ap.add_argument("--topic", default="", help='topic banner bottom-right, e.g. "THE HISTORY OF NIKE"')
    ap.add_argument("--phrasepos", default="center", choices=["center", "right"], help="right keeps the phrase off a face in the left half")
    ap.add_argument("--leftpos", default="top", choices=["top", "bottom"], help="bottom keeps a face in the top-left visible")
    a = ap.parse_args()
    ensure_wordfont()
    im = Image.open(a.base).convert("RGB")
    s = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1), Image.LANCZOS)
    im = im.crop(((im.width - W) // 2, (im.height - H) // 2, (im.width - W) // 2 + W, (im.height - H) // 2 + H))
    im = ImageEnhance.Contrast(im).enhance(1.12)
    lay = im.convert("RGBA")
    # vignette for punch
    vig = Image.new("L", (W, H), 0); vd = ImageDraw.Draw(vig)
    for i in range(60):
        vd.rectangle((i * 4, i * 3, W - i * 4, H - i * 3), outline=int(150 * (1 - i / 60)))
    lay.alpha_composite(Image.merge("RGBA", (Image.new("L", (W, H), 0),) * 3 + (vig.filter(ImageFilter.GaussianBlur(30)),)))
    if a.timer or a.battery:
        danger_glow(lay)
    if a.timer:
        tx1 = countdown(lay, a.timer, a.timerlabel)
        if a.battery:
            battery(lay, tx1 + 18, 30)
    elif a.battery:
        battery(lay, 36, 30)
    d = ImageDraw.Draw(lay)
    if a.left:
        f1 = fit(d, a.left, W * 0.47, 210)
        f2 = fit(d, a.left2, W * 0.40, 120) if a.left2 else None
        if a.leftpos == "bottom":
            y2 = H - 40 - (f2.size if f2 else 0)
            y1 = (y2 - 6 - f1.size) if f2 else H - 40 - f1.size
        else:
            y1 = 34; y2 = 34 + f1.size + 6
        word(lay, (40, y1), a.left, f1, RED)
        if f2:
            word(lay, (48, y2), a.left2, f2, CREAM)
        f3 = fit(d, a.right, W * 0.40, 230)
        word(lay, (W - 40, 30), a.right, f3, GOLD, anchor="ra")
        if a.right2:
            f4 = fit(d, a.right2, W * 0.36, 100)
            word(lay, (W - 46, 30 + f3.size + 6), a.right2, f4, CREAM, anchor="ra")
    elif a.phrase:
        cx, mw = (W // 2, 0.9) if a.phrasepos == "center" else (int(W * 0.735), 0.49)
        f1 = fit(d, a.phrase, W * mw, 190)
        word(lay, (cx, 26), a.phrase, f1, CREAM, anchor="ma")
        if a.phrase2:
            f2 = fit(d, a.phrase2, W * (mw + 0.02 if a.phrasepos == "center" else mw), 190)
            word(lay, (cx, 26 + f1.size + 10), a.phrase2, f2, RED, anchor="ma")
    if a.brand:
        # under the right-hand shock word when there is one, else bottom-right
        brand_wordmark(lay, a.brand.upper(), ytop=(30 + f3.size + 26) if (a.left and not a.right2) else None)
    if a.topic:
        topic_banner(lay, a.topic.upper())
    lay.convert("RGB").save(a.out, quality=92)
    print("saved", a.out)


if __name__ == "__main__":
    main()

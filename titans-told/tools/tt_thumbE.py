#!/usr/bin/env python3
"""Titans Told thumbnail, Style E ("era" thumbnail), owner decision 17 Nov 2026: "Check all the competitors most viewed
videos ... the smaller channels winning videos ... See what formula is working. Adapt the same in ours."

Evidence (vidIQ, 17 Nov 2026): CEOzoned (30K subs) "The ENTIRE History of NVIDIA / Coca-Cola in N Minutes" 1.27M / 1.22M
views, Warren Buffett 358K; Built On You (16.5K subs) "The ENTIRE History of Amazon in 20 Minutes" 465.7K (18,461x
breakout); CEOzoned's Facebook thumbnail switched to this layout -> x3.1 views per hour. Every one uses this layout, and
the one CEOzoned video that broke it (shocked face + "IT'S OVER...") got 6.9K.

Layout: a bright daytime cartoon base (Gemini, no text): the founder/CEO from the knees up on the LEFT, arms crossed,
calm, with a thick orange-red outline; behind and to the right an isometric landscape telling the company's story
from first building to today; the upper right left as open sky. This tool adds, top right: the NAME in big black serif
capitals, the YEAR RANGE under it, and a small rounded-square icon (no real logos; a generic symbol or a short mark).

usage:
  python3 tt_thumbE.py base.png out.jpg --name "THERANOS" --years "2003 – 2018" [--icon "drop|chip|dollar|game|star|car|phone|plane|text:R"] [--iconcolor "#C0392B"]
Writes a 1280x720 JPEG (< 2 MB) for thumbnails/set.
"""
import argparse, os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
SERIFS = [os.path.join(HERE, "..", "fonts", "PlayfairDisplay.ttf"), "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"]
W, H = 1280, 720
INK = (17, 17, 17)


def serif(size):
    for p in SERIFS:
        if os.path.exists(p):
            f = ImageFont.truetype(p, size)
            try:
                f.set_variation_by_name("Black")
            except Exception:
                try:
                    f.set_variation_by_name("Bold")
                except Exception:
                    pass
            return f
    return ImageFont.load_default()


def fit(d, text, maxw, start, minsize=40):
    s = start
    while s > minsize:
        f = serif(s)
        b = d.textbbox((0, 0), text, font=f)
        if b[2] - b[0] <= maxw:
            return f, b
        s -= 4
    f = serif(minsize)
    return f, d.textbbox((0, 0), text, font=f)


def icon(img, kind, col, box):
    x0, y0, x1, y1 = box
    sz = x1 - x0
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    d.rounded_rectangle((x0 + 4, y0 + 6, x1 + 4, y1 + 6), radius=sz // 4, fill=(0, 0, 0, 70))   # soft shadow
    d.rounded_rectangle(box, radius=sz // 4, fill=col, outline=(255, 255, 255), width=4)
    cx, cy, r = (x0 + x1) / 2, (y0 + y1) / 2, sz * 0.28
    white = (255, 255, 255)
    if kind == "drop":
        d.ellipse((cx - r, cy - r * 0.4, cx + r, cy + r * 1.6), fill=white)
        d.polygon([(cx, cy - r * 1.5), (cx - r * 0.93, cy + r * 0.3), (cx + r * 0.93, cy + r * 0.3)], fill=white)
    elif kind == "chip":
        d.rectangle((cx - r, cy - r, cx + r, cy + r), outline=white, width=6)
        for i in range(-1, 2):
            o = i * r * 0.6
            for a, b in (((cx + o, cy - r), (cx + o, cy - r * 1.4)), ((cx + o, cy + r), (cx + o, cy + r * 1.4)),
                         ((cx - r, cy + o), (cx - r * 1.4, cy + o)), ((cx + r, cy + o), (cx + r * 1.4, cy + o))):
                d.line((a, b), fill=white, width=5)
    elif kind == "game":
        d.rounded_rectangle((cx - r * 1.4, cy - r * 0.7, cx + r * 1.4, cy + r * 0.7), radius=int(r * 0.6), fill=white)
        d.line((cx - r * 0.9, cy, cx - r * 0.3, cy), fill=col, width=6); d.line((cx - r * 0.6, cy - r * 0.3, cx - r * 0.6, cy + r * 0.3), fill=col, width=6)
        d.ellipse((cx + r * 0.4, cy - r * 0.25, cx + r * 0.7, cy + r * 0.05), fill=col); d.ellipse((cx + r * 0.75, cy - r * 0.05, cx + r * 1.05, cy + r * 0.25), fill=col)
    elif kind == "star":
        import math
        pts = [(cx + (r * 1.2 if i % 2 == 0 else r * 0.5) * math.sin(i * math.pi / 5),
                cy - (r * 1.2 if i % 2 == 0 else r * 0.5) * math.cos(i * math.pi / 5)) for i in range(10)]
        d.polygon(pts, fill=white)
    else:
        txt = {"dollar": "$", "car": "◆", "phone": "▮", "plane": "✈"}.get(kind, kind[5:] if kind.startswith("text:") else "★")
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(sz * 0.55))
        b = d.textbbox((0, 0), txt, font=f)
        d.text((cx - (b[2] - b[0]) / 2 - b[0], cy - (b[3] - b[1]) / 2 - b[1]), txt, font=f, fill=white)
    img.alpha_composite(lay)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base"); ap.add_argument("out")
    ap.add_argument("--name", required=True); ap.add_argument("--years", required=True)
    ap.add_argument("--icon", default="star"); ap.add_argument("--iconcolor", default="#C0392B")
    a = ap.parse_args()
    im = Image.open(a.base).convert("RGB")
    sw, sh = im.size
    if abs(sw / sh - 16 / 9) > 0.01:   # cover-crop to 16:9
        if sw / sh > 16 / 9:
            nw = int(sh * 16 / 9); im = im.crop(((sw - nw) // 2, 0, (sw - nw) // 2 + nw, sh))
        else:
            nh = int(sw * 9 / 16); im = im.crop((0, (sh - nh) // 2, sw, (sh - nh) // 2 + nh))
    im = im.resize((W, H), Image.LANCZOS).convert("RGBA")
    d = ImageDraw.Draw(im)
    left, right = int(W * 0.40), W - 150            # text block between 40% and the icon
    name = a.name.upper()
    fn, bn = fit(d, name, right - left, 150 if len(name) <= 8 else 120)
    fy, by = fit(d, a.years, int((right - left) * 0.85), 96)
    nh, yh = bn[3] - bn[1], by[3] - by[1]
    # soft white glow behind the text so it reads on any sky
    glow = Image.new("RGBA", im.size, (0, 0, 0, 0)); gd = ImageDraw.Draw(glow)
    ny = 34
    nx = left + (right - left - (bn[2] - bn[0])) // 2 - bn[0]
    yy = ny + nh + 26
    yx = left + (right - left - (by[2] - by[0])) // 2 - by[0]
    for (x, y, t, f) in ((nx, ny - bn[1], name, fn), (yx, yy - by[1], a.years, fy)):
        gd.text((x, y), t, font=f, fill=(255, 255, 255, 230), stroke_width=14, stroke_fill=(255, 255, 255, 230))
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(10)))
    d = ImageDraw.Draw(im)
    d.text((nx, ny - bn[1]), name, font=fn, fill=INK)
    d.text((yx, yy - by[1]), a.years, font=fy, fill=INK)
    col = tuple(int(a.iconcolor.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    s = 112
    icon(im, a.icon, col, (W - s - 26, 30, W - 26, 30 + s))
    im.convert("RGB").save(a.out, quality=92, optimize=True)
    print("saved", a.out)


if __name__ == "__main__":
    main()

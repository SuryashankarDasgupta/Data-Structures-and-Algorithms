"""Style A thumbnail compositor. Usage: tt_thumb.py base.png out.jpg --name TESLA --years "2003 – 2026" [--hook "3 DAYS"] [--hook2 "FROM BANKRUPTCY"]
Founder art sits in the left third of base.png; title block goes top-right. Output 1280x720 JPEG < 2 MB."""
import argparse, os, sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tt_compose as C
ap = argparse.ArgumentParser(); ap.add_argument("base"); ap.add_argument("out")
ap.add_argument("--name", required=True); ap.add_argument("--years", default=""); ap.add_argument("--hook", default=""); ap.add_argument("--hook2", default="")
a = ap.parse_args()
W, H = 1920, 1080
im = Image.open(a.base).convert("RGB").resize((W, H))
# soft cream glow behind the title area for legibility
glow = Image.new("L", (W, H), 0); g = ImageDraw.Draw(glow)
g.ellipse((980, -260, 2150, 640), fill=170); glow = glow.filter(ImageFilter.GaussianBlur(120))
im = Image.composite(Image.new("RGB", (W, H), C.CREAM), im, glow)
d = ImageDraw.Draw(im)
def fit(text, kind, weight, maxw, start):
    s = start
    while s > 40:
        f = C.font(kind, s, weight)
        if d.textlength(text, font=f) <= maxw: return f
        s -= 6
    return C.font(kind, 40, weight)
right = W - 70; maxw = 820
y = 60
if a.hook:  # hook words in gold with navy stroke, above the name
    fh = fit(a.hook, "sans", "Black", maxw, 230)
    tw = d.textlength(a.hook, font=fh)
    d.text((right - tw, y), a.hook, font=fh, fill=C.GOLD, stroke_width=10, stroke_fill=C.NAVY)
    y += fh.size + 10
    if a.hook2:
        f2 = fit(a.hook2, "sans", "ExtraBold", maxw, 90)
        tw = d.textlength(a.hook2, font=f2)
        d.text((right - tw, y), a.hook2, font=f2, fill=C.CREAM, stroke_width=7, stroke_fill=C.NAVY)
        y += f2.size + 30
fn = fit(a.name, "serif", "Black", maxw, 150 if a.hook else 260)
tw = d.textlength(a.name, font=fn)
d.text((right - tw, y), a.name, font=fn, fill=(15, 15, 15))
y += int(fn.size * 1.12)
if a.years:
    fy = C.font("sans", 64 if not a.hook else 50, "Bold")
    tw = d.textlength(a.years, font=fy)
    d.text((right - tw, y), a.years, font=fy, fill=C.NAVY)
# generic lightning-bolt badge (no real logo), bottom-right corner
cx, cy, r = W - 120, H - 120, 72
d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=C.NAVY, outline=C.GOLD, width=8)
bolt = [(cx + 10, cy - 52), (cx - 30, cy + 8), (cx - 2, cy + 8), (cx - 14, cy + 52), (cx + 30, cy - 10), (cx + 2, cy - 10)]
d.polygon(bolt, fill=C.GOLD)
im.resize((1280, 720), Image.LANCZOS).save(a.out, quality=90)
print("saved", a.out, os.path.getsize(a.out))

#!/usr/bin/env python3
"""Titans Told compositor: scene spec JSON -> 1920x1080/30fps MP4.

Usage: python3 tt_compose.py spec.json out.mp4 [--preview SECONDS] [--draft]

Spec:
{
  "narration": "voice.mp3",            # required (timeline length = narration length unless "duration")
  "music": "bed.mp3",                  # optional, looped, ducked
  "music_gain_db": -26,                # music level relative to full scale before loudnorm
  "scenes": [ {"start": 0.0, "end": 3.2, "type": "...", ...}, ... ]
}
Scene types (all accept optional "caption": "lower-third text", "kinetic": "BIG NUMBER", "kicker": "small label"):
  image    {"src": png/jpg, "motion": "in|out|left|right|up|down|still", "focus": [x,y] 0-1}
  card     {"title": str, "sub": str, "bg": "navy|cream|ink"}            chapter/date cards
  quote    {"text": str, "who": str}
  timeline {"items": [["2003","Founded"],...], "active": idx}
  bars     {"title": str, "items": [["2022",1.31],...], "unit": "M"}
  place    {"name": str, "sub": str}                                     location pin card
  atlas    {"src": png, "line": str}                                     mascot cameo
  counter  {"value": 465, "prefix": "$", "suffix": "M", "decimals": 0, "label": str, "sub": str}   number counts up
  split    {"title": str, "left": {"src"|"value", "label"}, "right": {...}}  side-by-side comparison
  linechart{"title": str, "points": [["2020",0.5],...], "prefix": "$", "unit": "T"}             animated line
  checklist{"title": str, "items": [str, ...]}                            items tick in one by one
  document {"text": str, "highlight": "phrase in text", "who": "source"} paper + highlighter sweep
  headline {"dateline": str, "title": str, "sub": str}                      headline card slams in
  frame3d  {"src": png, "yaw0": -14, "yaw1": 10, "focus": [x,y]}         illustration as a turning 3D print
Spec "tracker": {"items": ["THE IDEA", ...], "starts": [s1, ...], "end": t} draws a chapter tracker across the top.
Crossfade 0.35 s between scenes. Paper-grain texture over everything.
"""
import json, math, os, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1920, 1080, 30
OUT_W, OUT_H = 2560, 1440   # encoded size: 1440p uploads get YouTube's VP9 encode (sharper on every device)
XF = 0.35
HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "..", "fonts")
NAVY, CREAM, GOLD, BROWN, INK = (31, 42, 68), (242, 232, 213), (212, 160, 23), (123, 75, 42), (17, 17, 17)
BG = {"navy": NAVY, "cream": CREAM, "ink": INK}


FONT_URLS = {"PlayfairDisplay.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf",
             "Inter.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf"}


def ensure_fonts():
    os.makedirs(FONTS, exist_ok=True)
    for name, url in FONT_URLS.items():
        p = os.path.join(FONTS, name)
        if not os.path.exists(p) or os.path.getsize(p) < 10000:
            subprocess.run(["curl", "-sSL", "-o", p, url], check=True)


ensure_fonts()


def font(kind, size, weight="Bold"):
    path = os.path.join(FONTS, "PlayfairDisplay.ttf" if kind == "serif" else "Inter.ttf")
    f = ImageFont.truetype(path, size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


_cache = {}
_order = []


def load_img(src):
    """Load an illustration (ideally a 3840x2160 AI-upscaled master) at 2400x1350 so a 1.25x Ken Burns crop
    still has full 1080p detail. Small LRU cache keeps memory low across parallel workers."""
    if src in _cache:
        return _cache[src]
    im = Image.open(src).convert("RGB")
    tw = int(W * 1.25)
    th = int(tw * im.height / im.width)
    if im.width != tw:
        im = im.resize((tw, th), Image.LANCZOS)
    _cache[src] = im
    _order.append(src)
    if len(_order) > 6:
        _cache.pop(_order.pop(0), None)
    return im


def ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def kenburns(im, p, motion, focus):
    """Crop window that fills 16:9, animated by progress p in [0,1]."""
    iw, ih = im.size
    base_w = min(iw, ih * W / H)
    base_h = base_w * H / W
    z0, z1 = 1.0, 1.0
    dx0 = dx1 = dy0 = dy1 = 0.0
    if motion == "in":
        z0, z1 = 1.0, 1.14
    elif motion == "out":
        z0, z1 = 1.14, 1.0
    elif motion in ("left", "right"):
        z0 = z1 = 1.12
        dx0, dx1 = (0.5, -0.5) if motion == "left" else (-0.5, 0.5)
    elif motion in ("up", "down"):
        z0 = z1 = 1.12
        dy0, dy1 = (0.5, -0.5) if motion == "up" else (-0.5, 0.5)
    q = ease(p)
    z = z0 + (z1 - z0) * q
    cw, ch = base_w / z, base_h / z
    fx, fy = focus
    cx = fx * iw + (dx0 + (dx1 - dx0) * q) * (base_w - cw)
    cy = fy * ih + (dy0 + (dy1 - dy0) * q) * (base_h - ch)
    cx = min(max(cx, cw / 2), iw - cw / 2)
    cy = min(max(cy, ch / 2), ih - ch / 2)
    box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
    return im.transform((W, H), Image.EXTENT, box, Image.BICUBIC)


def text_w(d, s, f):
    b = d.textbbox((0, 0), s, font=f)
    return b[2] - b[0], b[3] - b[1]


def wrap(d, s, f, maxw):
    words, lines, cur = s.split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if text_w(d, t, f)[0] <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    return lines


def overlay_layer(scene, t_in, dur):
    """RGBA overlay with caption / kinetic / kicker, animated in."""
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    a = ease(t_in / 0.45)
    if scene.get("kinetic"):
        f = font("serif", 150, "Black")
        s = scene["kinetic"]
        tw, th = text_w(d, s, f)
        sc = 0.85 + 0.15 * a
        tmp = Image.new("RGBA", (tw + 80, th + 120), (0, 0, 0, 0))
        td = ImageDraw.Draw(tmp)
        td.text((40, 20), s, font=f, fill=GOLD + (255,), stroke_width=6, stroke_fill=INK + (255,))
        # soft dark halo so gold text stays readable on bright/gold art
        halo = Image.new("RGBA", tmp.size, INK + (0,))
        halo.putalpha(tmp.split()[3].filter(ImageFilter.GaussianBlur(26)).point(lambda v: min(255, int(v * 1.6))))
        halo.alpha_composite(tmp)
        tmp = halo
        tmp = tmp.resize((max(1, int(tmp.width * sc)), max(1, int(tmp.height * sc))), Image.LANCZOS)
        al = tmp.split()[3].point(lambda v: int(v * a))
        tmp.putalpha(al)
        lay.alpha_composite(tmp, ((W - tmp.width) // 2, (H - tmp.height) // 2 - 40))
    if scene.get("kicker"):
        f = font("sans", 40, "Bold")
        s = scene["kicker"].upper()
        tw, th = text_w(d, s, f)
        y = 110
        d.rounded_rectangle((90, y, 90 + tw + 44, y + th + 30), 10, fill=GOLD + (int(235 * a),))
        d.text((112, y + 9), s, font=f, fill=INK + (int(255 * a),))
    if scene.get("caption"):
        f = font("sans", 54, "SemiBold")
        lines = wrap(d, scene["caption"], f, W - 360)
        lh = 60
        bh = lh * len(lines) + 40
        y0 = H - bh - 70 + int((1 - a) * 30)
        d.rounded_rectangle((150, y0, W - 150, y0 + bh), 16, fill=NAVY + (int(215 * a),))
        for i, ln in enumerate(lines):
            tw, _ = text_w(d, ln, f)
            d.text(((W - tw) // 2, y0 + 18 + i * lh), ln, font=f, fill=CREAM + (int(255 * a),))
    return lay


def solid(color):
    return Image.new("RGB", (W, H), color)


def gradient_bg(color):
    base = np.zeros((H, W, 3), np.float32)
    c = np.array(color, np.float32)
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.sqrt(((xx - W / 2) / (W / 1.3)) ** 2 + ((yy - H / 2) / (H / 1.1)) ** 2)
    v = np.clip(1.08 - 0.45 * r, 0.55, 1.08)[..., None]
    base[:] = c * v
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))


_bgcache = {}


def bg(name):
    if name not in _bgcache:
        _bgcache[name] = gradient_bg(BG.get(name, NAVY))
    return _bgcache[name]


def draw_card(scene, t, dur):
    name = scene.get("bg", "navy")
    im = bg(name).copy()
    d = ImageDraw.Draw(im, "RGBA")
    fg = CREAM if name != "cream" else INK
    a = ease(t / 0.5)
    ft = font("serif", 140 if len(scene.get("title", "")) < 14 else 96, "Black")
    lines = wrap(d, scene.get("title", ""), ft, W - 300)
    y = H // 2 - 70 * len(lines) - (40 if scene.get("sub") else 0) + int((1 - a) * 40)
    for ln in lines:
        tw, th = text_w(d, ln, ft)
        d.text(((W - tw) // 2, y), ln, font=ft, fill=fg + (int(255 * a),))
        y += int(th * 1.25)
    d.line(((W // 2 - 120, y + 20), (W // 2 + 120, y + 20)), fill=GOLD + (int(255 * a),), width=6)
    if scene.get("sub"):
        fs = font("sans", 64, "Medium")
        for ln in wrap(d, scene["sub"], fs, W - 400):
            tw, th = text_w(d, ln, fs)
            d.text(((W - tw) // 2, y + 50), ln, font=fs, fill=fg + (int(230 * ease((t - 0.25) / 0.5)),))
            y += th + 18
    return im


def draw_quote(scene, t, dur):
    im = bg("cream").copy()
    d = ImageDraw.Draw(im, "RGBA")
    fq = font("serif", 76, "SemiBold")
    lines = wrap(d, "“" + scene["text"] + "”", fq, W - 360)
    n_show = len(lines)
    y = H // 2 - 50 * n_show - 40
    for i, ln in enumerate(lines):
        a = ease((t - i * 0.25) / 0.5)
        tw, th = text_w(d, ln, fq)
        d.text(((W - tw) // 2, y), ln, font=fq, fill=INK + (int(255 * a),))
        y += 100
    fw = font("sans", 50, "SemiBold")
    who = "— " + scene.get("who", "")
    tw, _ = text_w(d, who, fw)
    d.text(((W - tw) // 2, y + 30), who, font=fw, fill=BROWN + (int(255 * ease((t - 0.6) / 0.5)),))
    return im


def draw_timeline(scene, t, dur):
    im = bg("navy").copy()
    d = ImageDraw.Draw(im, "RGBA")
    items = scene["items"]
    act = scene.get("active", len(items) - 1)
    n = len(items)
    x0, x1, yl = 200, W - 200, H // 2 + 20
    prog = ease(t / max(0.8, dur * 0.5))
    d.line(((x0, yl), (x0 + (x1 - x0) * prog, yl)), fill=CREAM + (200,), width=6)
    fy, fl = font("serif", 76, "Black"), font("sans", 42, "SemiBold")
    for i, (yr, lab) in enumerate(items):
        x = x0 + (x1 - x0) * (i / max(1, n - 1))
        if (x - x0) / (x1 - x0 + 1e-6) > prog + 1e-3:
            continue
        on = i == act
        r = 26 if on else 16
        d.ellipse((x - r, yl - r, x + r, yl + r), fill=(GOLD if on else CREAM) + (255,))
        tw, _ = text_w(d, yr, fy)
        d.text((x - tw / 2, yl - 130), yr, font=fy, fill=(GOLD if on else CREAM) + (255,))
        for j, ln in enumerate(wrap(d, lab, fl, 300)):
            tw, _ = text_w(d, ln, fl)
            d.text((x - tw / 2, yl + 50 + j * 44), ln, font=fl, fill=CREAM + (255 if on else 180,))
    return im


def draw_bars(scene, t, dur):
    im = bg("cream").copy()
    d = ImageDraw.Draw(im, "RGBA")
    ft = font("serif", 70, "Black")
    tw, _ = text_w(d, scene.get("title", ""), ft)
    d.text(((W - tw) // 2, 100), scene.get("title", ""), font=ft, fill=INK)
    items = scene["items"]
    mx = max(v for _, v in items) or 1
    n = len(items)
    bw = min(220, (W - 400) // n - 40)
    gap = ((W - 400) - bw * n) / max(1, n - 1) if n > 1 else 0
    base, top = H - 170, 300
    fl, fv = font("sans", 46, "SemiBold"), font("sans", 50, "Bold")
    for i, (lab, v) in enumerate(items):
        g = ease((t - i * 0.18) / 0.9)
        h = (base - top) * (v / mx) * g
        x = 200 + i * (bw + gap)
        col = GOLD if i == n - 1 else NAVY
        d.rounded_rectangle((x, base - h, x + bw, base), 10, fill=col)
        lw, _ = text_w(d, str(lab), fl)
        d.text((x + (bw - lw) / 2, base + 20), str(lab), font=fl, fill=INK)
        if g > 0.6:
            vs = f"{v:g}{scene.get('unit', '')}"
            vw, _ = text_w(d, vs, fv)
            d.text((x + (bw - vw) / 2, base - h - 60), vs, font=fv, fill=INK)
    return im


def draw_place(scene, t, dur):
    im = bg("navy").copy()
    d = ImageDraw.Draw(im, "RGBA")
    a = ease(t / 0.5)
    cx, cy = W // 2, H // 2 - 120
    drop = int((1 - a) * -80)
    d.ellipse((cx - 60, cy - 60 + drop, cx + 60, cy + 60 + drop), fill=GOLD + (255,))
    d.polygon([(cx - 48, cy + 30 + drop), (cx + 48, cy + 30 + drop), (cx, cy + 140 + drop)], fill=GOLD + (255,))
    d.ellipse((cx - 22, cy - 22 + drop, cx + 22, cy + 22 + drop), fill=NAVY + (255,))
    fn, fs = font("serif", 110, "Black"), font("sans", 50, "Medium")
    tw, _ = text_w(d, scene["name"], fn)
    d.text(((W - tw) // 2, cy + 190), scene["name"], font=fn, fill=CREAM + (int(255 * a),))
    if scene.get("sub"):
        tw, _ = text_w(d, scene["sub"], fs)
        d.text(((W - tw) // 2, cy + 340), scene["sub"], font=fs, fill=GOLD + (int(255 * ease((t - 0.3) / 0.5)),))
    return im


def draw_atlas(scene, t, dur):
    im = bg("navy").copy()
    a_img = Image.open(scene["src"]).convert("RGBA")
    sc = (H * 0.92) / a_img.height
    a_img = a_img.resize((int(a_img.width * sc), int(a_img.height * sc)), Image.LANCZOS)
    bob = int(6 * math.sin(t * 2.2))
    im.paste(a_img, (W - a_img.width - 120, H - a_img.height + 20 + bob), a_img)
    if scene.get("line"):
        d = ImageDraw.Draw(im, "RGBA")
        f = font("serif", 76, "Bold")
        lines = wrap(d, scene["line"], f, W - a_img.width - 360)
        y = H // 2 - 50 * len(lines)
        for i, ln in enumerate(lines):
            al = ease((t - 0.2 - i * 0.2) / 0.5)
            d.text((160, y), ln, font=f, fill=CREAM + (int(255 * al),))
            y += 100
    return im


def _rays_bg(color, t):
    im = bg("navy" if color == NAVY else "ink").copy()
    d = ImageDraw.Draw(im, "RGBA")
    cx, cy = W // 2, H // 2 + 40
    for i in range(24):
        a = i * math.pi / 12 + t * 0.06
        x2, y2 = cx + math.cos(a) * 1600, cy + math.sin(a) * 1600
        x3, y3 = cx + math.cos(a + 0.06) * 1600, cy + math.sin(a + 0.06) * 1600
        d.polygon([(cx, cy), (x2, y2), (x3, y3)], fill=GOLD + (14,))
    return im


def draw_counter(scene, t, dur):
    """Big number counting up: {value, prefix, suffix, decimals, label, sub}"""
    im = _rays_bg(NAVY, t)
    d = ImageDraw.Draw(im, "RGBA")
    v = float(scene["value"]); dec = int(scene.get("decimals", 0))
    k = ease(t / min(1.6, max(0.6, dur * 0.45)))
    cur = v * k
    txt = f"{scene.get('prefix', '')}{cur:,.{dec}f}{scene.get('suffix', '')}"
    f = font("serif", 230 if len(txt) < 9 else 170, "Black")
    tw, th = text_w(d, txt, f)
    d.text(((W - tw) // 2, H // 2 - th - 10), txt, font=f, fill=GOLD, stroke_width=4, stroke_fill=INK)
    a = ease((t - 0.3) / 0.5)
    if scene.get("label"):
        fl = font("sans", 64, "SemiBold")
        for i, ln in enumerate(wrap(d, scene["label"], fl, W - 360)):
            lw, _ = text_w(d, ln, fl)
            d.text(((W - lw) // 2, H // 2 + 60 + i * 76), ln, font=fl, fill=CREAM + (int(255 * a),))
    if scene.get("sub"):
        fs = font("sans", 44, "Medium")
        sw, _ = text_w(d, scene["sub"], fs)
        d.text(((W - sw) // 2, H - 170), scene["sub"], font=fs, fill=GOLD + (int(220 * a),))
    return im


def _cover(im, w, h, fx=0.5, fy=0.5):
    s_ = max(w / im.width, h / im.height)
    r = im.resize((int(im.width * s_) + 1, int(im.height * s_) + 1), Image.LANCZOS)
    x = int((r.width - w) * fx); y = int((r.height - h) * fy)
    return r.crop((x, y, x + w, y + h))


def draw_split(scene, t, dur):
    """Two-sided comparison: {title, left:{src|value,label}, right:{src|value,label}}"""
    im = bg("ink").copy()
    d = ImageDraw.Draw(im, "RGBA")
    half = W // 2
    for side, key in ((0, "left"), (1, "right")):
        it = scene[key]
        k = ease((t - side * 0.25) / 0.6)
        off = int((1 - k) * (-half if side == 0 else half))
        x0 = side * half + off
        if it.get("src"):
            panel = _cover(load_img(it["src"]), half - 12, H - 290, it.get("fx", 0.5), it.get("fy", 0.5))
            im.paste(panel, (x0 + 6, 180))
        else:
            d.rectangle((x0 + 6, 180, x0 + half - 6, H - 110), fill=NAVY if side == 0 else BROWN)
            fv = font("serif", 170, "Black")
            vw, vh = text_w(d, it["value"], fv)
            d.text((x0 + (half - vw) // 2, H // 2 - vh // 2 - 60), it["value"], font=fv, fill=GOLD, stroke_width=3, stroke_fill=INK)
        fl = font("sans", 52, "Bold")
        lab = it.get("label", "")
        lw, lh = text_w(d, lab, fl)
        d.rounded_rectangle((x0 + (half - lw) // 2 - 24, H - 200, x0 + (half + lw) // 2 + 24, H - 200 + lh + 34), 12, fill=INK + (220,))
        d.text((x0 + (half - lw) // 2, H - 192), lab, font=fl, fill=CREAM)
    if scene.get("title"):
        ft = font("serif", 64, "Black")
        tw, _ = text_w(d, scene["title"], ft)
        d.text(((W - tw) // 2, 92), scene["title"], font=ft, fill=CREAM)
    a = ease((t - 0.5) / 0.4)
    r = int(70 * a)
    if r > 2:
        d.ellipse((W // 2 - r, H // 2 - r, W // 2 + r, H // 2 + r), fill=GOLD, outline=INK, width=6)
        fv = font("serif", 56, "Black"); vw, vh = text_w(d, "vs", fv)
        d.text((W // 2 - vw // 2, H // 2 - vh // 2 - 12), "vs", font=fv, fill=INK)
    return im


def draw_linechart(scene, t, dur):
    """Animated line chart: {title, points:[[label,value],...], unit, prefix}"""
    im = bg("cream").copy()
    d = ImageDraw.Draw(im, "RGBA")
    ft = font("serif", 70, "Black")
    tw, _ = text_w(d, scene.get("title", ""), ft)
    d.text(((W - tw) // 2, 100), scene.get("title", ""), font=ft, fill=INK)
    pts = scene["points"]; vals = [v for _, v in pts]
    lo, hi = min(0, min(vals)), max(vals) or 1
    x0, x1, y0, y1 = 220, W - 220, H - 210, 290
    for g in range(5):
        gy = y0 - (y0 - y1) * g / 4
        d.line(((x0, gy), (x1, gy)), fill=INK + (28,), width=2)
    xy = [(x0 + (x1 - x0) * i / max(1, len(pts) - 1), y0 - (y0 - y1) * (v - lo) / (hi - lo)) for i, (_, v) in enumerate(pts)]
    prog = ease(t / max(1.0, dur * 0.6)) * (len(xy) - 1)
    n = int(prog)
    path = xy[:n + 1]
    if n < len(xy) - 1:
        f_ = prog - n
        path = path + [(xy[n][0] + (xy[n + 1][0] - xy[n][0]) * f_, xy[n][1] + (xy[n + 1][1] - xy[n][1]) * f_)]
    if len(path) > 1:
        d.polygon(path + [(path[-1][0], y0), (x0, y0)], fill=GOLD + (60,))
        d.line(path, fill=NAVY, width=10, joint="curve")
    fl, fv = font("sans", 42, "SemiBold"), font("sans", 46, "Bold")
    for i, ((lab, v), (x, y)) in enumerate(zip(pts, xy)):
        lw, _ = text_w(d, str(lab), fl)
        d.text((x - lw / 2, y0 + 24), str(lab), font=fl, fill=INK)
        if i <= n:
            d.ellipse((x - 14, y - 14, x + 14, y + 14), fill=GOLD if i == len(pts) - 1 else NAVY, outline=INK, width=3)
            vs = f"{scene.get('prefix', '')}{v:g}{scene.get('unit', '')}"
            vw, _ = text_w(d, vs, fv)
            d.text((x - vw / 2, y - 76), vs, font=fv, fill=INK)
    return im


def draw_checklist(scene, t, dur):
    """Items revealed one by one with gold checks: {title, items:[...]}"""
    im = bg("navy").copy()
    d = ImageDraw.Draw(im, "RGBA")
    ft = font("serif", 76, "Black")
    tw, _ = text_w(d, scene.get("title", ""), ft)
    d.text(((W - tw) // 2, 110), scene.get("title", ""), font=ft, fill=CREAM)
    items = scene["items"]; n = len(items)
    fi = font("sans", 58, "SemiBold")
    y = 290
    if "done" in scene:
        # progress tracker (recurring thread graphic): all items visible; first `done` ticked (the newest ticks in),
        # `active` (optional) pulses as the step in play; the rest wait as hollow rings
        done, act = int(scene["done"]), scene.get("active")
        for i, it in enumerate(items):
            a_row = ease((t - i * 0.12) / 0.4)
            x = 300
            if i < done:
                ka = 1.0 if i < done - 1 or scene.get("animate_last") is False else ease((t - 0.5) / 0.35)
                d.ellipse((x - 34, y + 4, x + 34, y + 72), fill=GOLD + (int(255 * a_row),))
                if ka > 0:
                    d.line(((x - 16, y + 38), (x - 4, y + 52), (x + 18, y + 22)), fill=INK + (int(255 * min(a_row, ka)),), width=9)
                col = CREAM + (int(255 * a_row),)
            else:
                on = act is not None and i == act
                pulse = 0.5 + 0.5 * math.sin(t * 5) if on else 0
                d.ellipse((x - 34, y + 4, x + 34, y + 72), outline=(GOLD if on else CREAM) + (int((160 + 95 * pulse) * a_row),), width=5)
                col = (GOLD if on else CREAM) + (int((255 if on else 140) * a_row),)
            for j, ln in enumerate(wrap(d, it, fi, W - x - 260)):
                d.text((x + 70, y + 2 + j * 68), ln, font=fi, fill=col)
                if j:
                    y += 68
            y += 130
        return im
    step = max(0.5, min(1.4, (dur * 0.75) / n))
    for i, it in enumerate(items):
        a = ease((t - 0.3 - i * step) / 0.4)
        if a <= 0:
            break
        x = 300 - int((1 - a) * 60)
        d.ellipse((x - 34, y + 4, x + 34, y + 72), fill=GOLD + (int(255 * a),))
        d.line(((x - 16, y + 38), (x - 4, y + 52), (x + 18, y + 22)), fill=INK + (int(255 * a),), width=9)
        for j, ln in enumerate(wrap(d, it, fi, W - x - 260)):
            d.text((x + 70, y + 2 + j * 68), ln, font=fi, fill=CREAM + (int(255 * a),))
            if j:
                y += 68
        y += 130
    return im


def draw_document(scene, t, dur):
    """Paper document with a highlighter sweep: {text, highlight, who}"""
    base = gradient_bg(BROWN)
    page = Image.new("RGBA", (1240, 760), CREAM + (255,))
    pd = ImageDraw.Draw(page)
    fd = font("serif", 50, "SemiBold")
    lines = wrap(pd, scene["text"], fd, 1080)
    hl = scene.get("highlight", "")
    k = ease((t - 0.6) / 0.9)
    words_all = scene["text"].split()
    hw_ = hl.split()
    span = set()
    for i0 in range(len(words_all) - len(hw_) + 1):
        if hw_ and words_all[i0:i0 + len(hw_)] == hw_:
            span = set(range(i0, i0 + len(hw_))); break
    y = 90; wi = 0; nspan = max(1, len(span)); done = 0
    for ln in lines:
        x = 80
        for wd in ln.split():
            ww = text_w(pd, wd + " ", fd)[0]
            if wi in span and k > 0:
                frac = min(1.0, max(0.0, k * nspan - done))
                if frac > 0:
                    pd.rectangle((x - 6, y + 4, x - 6 + (ww + 6) * frac, y + 64), fill=(244, 205, 90, 255))
                done += 1
            x += ww; wi += 1
        pd.text((80, y), ln, font=fd, fill=INK)
        y += 78
    if scene.get("who"):
        fw = font("sans", 36, "SemiBold")
        pd.text((80, 760 - 90), "Source: " + scene["who"], font=fw, fill=BROWN)
    sh = Image.new("RGBA", (1300, 820), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle((30, 30, 1270, 790), fill=(0, 0, 0, 110))
    sh = sh.filter(ImageFilter.GaussianBlur(18))
    rot = -2.0 + 1.0 * ease(t / max(dur, 0.1))
    sc = 1.0 + 0.04 * ease(t / max(dur, 0.1))
    pg = page.resize((int(1240 * sc), int(760 * sc)), Image.LANCZOS).rotate(rot, expand=True, resample=Image.BICUBIC)
    shr = sh.rotate(rot, expand=True, resample=Image.BICUBIC)
    base = base.convert("RGBA")
    base.alpha_composite(shr, ((W - shr.width) // 2 + 14, (H - shr.height) // 2 + 20))
    base.alpha_composite(pg, ((W - pg.width) // 2, (H - pg.height) // 2))
    return base.convert("RGB")


def draw_headline(scene, t, dur):
    """Headline card that slams in: {dateline, title, sub}"""
    im = bg("cream").copy()
    d = ImageDraw.Draw(im, "RGBA")
    d.line(((160, 150), (W - 160, 150)), fill=INK, width=6)
    d.line(((160, 166), (W - 160, 166)), fill=INK, width=2)
    if scene.get("dateline"):
        fk = font("sans", 40, "Bold")
        kt = scene["dateline"].upper()
        kw, _ = text_w(d, kt, fk)
        d.text(((W - kw) // 2, 92), kt, font=fk, fill=BROWN)
    k = ease(t / 0.35)
    ft = font("serif", 120, "Black")
    lines = wrap(d, scene["title"], ft, W - 360)
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
    y = 260
    for ln in lines:
        lw, lh = text_w(ld, ln, ft)
        ld.text(((W - lw) // 2, y), ln, font=ft, fill=INK)
        y += int(lh * 1.22)
    sc = 1.18 - 0.18 * k
    lay = lay.resize((int(W * sc), int(H * sc)), Image.LANCZOS)
    lay = lay.crop(((lay.width - W) // 2, (lay.height - H) // 2, (lay.width - W) // 2 + W, (lay.height - H) // 2 + H))
    lay.putalpha(lay.split()[3].point(lambda v: int(v * k)))
    im = im.convert("RGBA"); im.alpha_composite(lay); im = im.convert("RGB")
    d = ImageDraw.Draw(im, "RGBA")
    d.line(((160, y + 40), (W - 160, y + 40)), fill=INK, width=2)
    if scene.get("sub"):
        fs = font("sans", 50, "Medium")
        a = ease((t - 0.4) / 0.4)
        for i, ln in enumerate(wrap(d, scene["sub"], fs, W - 400)):
            sw, _ = text_w(d, ln, fs)
            d.text(((W - sw) // 2, y + 80 + i * 64), ln, font=fs, fill=INK + (int(230 * a),))
    return im


def _persp_coeffs(src_pts, dst_pts):
    A, B = [], []
    for (x, y), (u, v) in zip(dst_pts, src_pts):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); B.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); B.append(v)
    return np.linalg.solve(np.array(A, float), np.array(B, float)).tolist()


def draw_frame3d(scene, t, dur):
    """Illustration as a print floating in 3D space, slowly turning: {src, yaw0, yaw1}"""
    base = bg("ink").copy().convert("RGBA")
    src = load_img(scene["src"])
    pw, ph = 1360, 765
    pr = _cover(src, pw, ph, *scene.get("focus", [0.5, 0.5]))
    card = Image.new("RGB", (pw + 40, ph + 40), CREAM); card.paste(pr, (20, 20))
    p = ease(t / max(dur, 0.1))
    yaw = math.radians(scene.get("yaw0", -14) + (scene.get("yaw1", 10) - scene.get("yaw0", -14)) * p)
    cw, chh = card.size
    zc = 2400.0
    pts = []
    for (x, y) in ((-cw / 2, -chh / 2), (cw / 2, -chh / 2), (cw / 2, chh / 2), (-cw / 2, chh / 2)):
        xr, zr = x * math.cos(yaw), x * math.sin(yaw)
        f_ = zc / (zc + zr)
        pts.append((W / 2 + xr * f_, H / 2 + y * f_ - 10))
    co = _persp_coeffs([(0, 0), (cw, 0), (cw, chh), (0, chh)], pts)
    warped = card.convert("RGBA").transform((W, H), Image.PERSPECTIVE, co, Image.BICUBIC)
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).polygon([(x + 22, y + 30) for x, y in pts], fill=(0, 0, 0, 150))
    sh = sh.filter(ImageFilter.GaussianBlur(22))
    base.alpha_composite(sh); base.alpha_composite(warped)
    return base.convert("RGB")


def scene_frame(scene, t):
    dur = scene["end"] - scene["start"]
    typ = scene.get("type", "image")
    if typ == "image":
        im = kenburns(load_img(scene["src"]), t / max(dur, 0.01), scene.get("motion", "in"), scene.get("focus", [0.5, 0.5]))
    elif typ == "card":
        im = draw_card(scene, t, dur)
    elif typ == "quote":
        im = draw_quote(scene, t, dur)
    elif typ == "timeline":
        im = draw_timeline(scene, t, dur)
    elif typ == "bars":
        im = draw_bars(scene, t, dur)
    elif typ == "place":
        im = draw_place(scene, t, dur)
    elif typ == "atlas":
        im = draw_atlas(scene, t, dur)
    elif typ == "counter":
        im = draw_counter(scene, t, dur)
    elif typ == "split":
        im = draw_split(scene, t, dur)
    elif typ == "linechart":
        im = draw_linechart(scene, t, dur)
    elif typ == "checklist":
        im = draw_checklist(scene, t, dur)
    elif typ == "document":
        im = draw_document(scene, t, dur)
    elif typ == "headline":
        im = draw_headline(scene, t, dur)
    elif typ == "frame3d":
        im = draw_frame3d(scene, t, dur)
    else:
        raise ValueError("unknown scene type " + typ)
    if any(scene.get(k) for k in ("caption", "kinetic", "kicker")):
        im = im.convert("RGBA")
        im.alpha_composite(overlay_layer(scene, t, dur))
        im = im.convert("RGB")
    return im


TRACKER = None   # {"items": [...], "starts": [...], "end": t} set from spec


def tracker_layer(t):
    """Chapter tracker across the top: numbered chapters, current one in a gold pill (owner request 6 Nov 2026)."""
    tr = TRACKER
    if not tr or t < tr["starts"][0] or t >= tr["end"]:
        return None
    idx = max(i for i, s0 in enumerate(tr["starts"]) if t >= s0)
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    a = min(1.0, (t - tr["starts"][0]) / 0.5, (tr["end"] - t) / 0.5)
    d.rectangle((0, 0, W, 78), fill=NAVY + (int(205 * a),))
    d.line(((0, 78), (W, 78)), fill=GOLD + (int(230 * a),), width=3)
    f = font("sans", 30, "ExtraBold")
    labels = [f"{i + 1}  {x.upper()}" for i, x in enumerate(tr["items"])]
    widths = [text_w(d, l, f)[0] for l in labels]
    gap = max(26, (W - 80 - sum(widths) - 40 * len(labels)) // max(1, len(labels) - 1))
    x = 40
    for i, (l, w) in enumerate(zip(labels, widths)):
        if i == idx:
            d.rounded_rectangle((x - 18, 14, x + w + 18, 64), 12, fill=GOLD + (int(255 * a),))
            d.text((x, 21), l, font=f, fill=INK + (int(255 * a),))
        else:
            col = CREAM + (int((215 if i < idx else 120) * a),)
            d.text((x, 21), l, font=f, fill=col)
        x += w + 40 + gap
    return lay


def grain():
    rng = np.random.default_rng(7)
    g = rng.normal(0, 3, (H, W, 1)).astype(np.float32)
    return g


def probe_dur(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    return float(out)


def render_range(scenes, f0, f1, path):
    G = grain()
    enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
                            "-vf", f"scale={OUT_W}:{OUT_H}:flags=lanczos", "-crf", "18", "-pix_fmt", "yuv420p", path], stdin=subprocess.PIPE)
    si = 0
    for fi in range(f0, f1):
        t = fi / FPS
        while si < len(scenes) - 1 and t >= scenes[si + 1]["start"]:
            si += 1
        cur = scenes[si]
        fr = np.asarray(scene_frame(cur, t - cur["start"]), np.float32)
        if si > 0 and t - cur["start"] < XF:
            prev = scenes[si - 1]
            pf = np.asarray(scene_frame(prev, t - prev["start"]), np.float32)
            k = ease((t - cur["start"]) / XF)
            fr = pf * (1 - k) + fr * k
        tl = tracker_layer(t)
        if tl is not None:
            im_ = Image.fromarray(np.clip(fr, 0, 255).astype(np.uint8)).convert("RGBA")
            im_.alpha_composite(tl)
            fr = np.asarray(im_.convert("RGB"), np.float32)
        fr = np.clip(fr + G, 0, 255).astype(np.uint8)
        enc.stdin.write(fr.tobytes())
        if (fi - f0) % (FPS * 60) == 0:
            print(f"[{os.path.basename(path)}] frame {fi - f0}/{f1 - f0}", flush=True)
    enc.stdin.close()
    if enc.wait():
        sys.exit("encoder failed")


def main():
    spec_path, out = sys.argv[1], sys.argv[2]
    preview = float(sys.argv[sys.argv.index("--preview") + 1]) if "--preview" in sys.argv else None
    spec = json.load(open(spec_path))
    root = os.path.dirname(os.path.abspath(spec_path))
    for s in spec["scenes"]:
        for obj in (s, s.get("left") or {}, s.get("right") or {}):
            if obj.get("src") and not os.path.isabs(obj["src"]):
                obj["src"] = os.path.join(root, obj["src"])
    narr = os.path.join(root, spec["narration"])
    total = spec.get("duration") or probe_dur(narr)
    if preview:
        total = min(total, preview)
    scenes = sorted(spec["scenes"], key=lambda s: s["start"])
    global TRACKER
    TRACKER = spec.get("tracker")
    nfr = int(total * FPS)
    silent = out + ".video.mp4"
    if "--part" in sys.argv:  # worker: render a frame range to a video-only file
        i, n = int(sys.argv[sys.argv.index("--part") + 1]), int(sys.argv[sys.argv.index("--part") + 2])
        render_range(scenes, nfr * i // n, nfr * (i + 1) // n, f"{out}.part{i}.mp4")
        return
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else max(1, min(3, (os.cpu_count() or 2) - 1))
    if workers == 1:
        render_range(scenes, 0, nfr, silent)
    else:
        base = [sys.executable, os.path.abspath(__file__), spec_path, out] + (["--preview", str(preview)] if preview else [])
        procs = [subprocess.Popen(base + ["--part", str(i), str(workers)]) for i in range(workers)]
        if any(p.wait() for p in procs):
            sys.exit("a render worker failed")
        lst = out + ".parts.txt"
        open(lst, "w").write("".join(f"file '{os.path.abspath(out)}.part{i}.mp4'\n" for i in range(workers)))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", silent], check=True)
        for i in range(workers):
            os.remove(f"{out}.part{i}.mp4")
        os.remove(lst)
    # audio: narration + ducked music, loudness -14 LUFS
    inputs = ["-i", silent, "-i", narr]
    filt = f"[1:a]atrim=0:{total},asetpts=N/SR/TB,aformat=sample_rates=48000:channel_layouts=stereo[v]"
    sfx = spec.get("sfx")
    if spec.get("music"):
        mus = os.path.join(root, spec["music"])
        inputs += ["-stream_loop", "-1", "-i", mus]
        gdb = spec.get("music_gain_db", -26); ratio = spec.get("duck_ratio", 6)
        filt = filt[:-3] + ",asplit=2[v][vs]"
        filt += (f";[2:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{total},volume={gdb}dB,afade=t=in:d=2,afade=t=out:st={max(0, total - 3)}:d=3[m];"
                 f"[m][vs]sidechaincompress=threshold=0.02:ratio={ratio}:attack=20:release=400[md]")
        if sfx:
            inputs += ["-i", os.path.join(root, sfx)]
            filt += (f";[3:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{total},volume={spec.get('sfx_gain_db', 0)}dB[fx]"
                     f";[v][md][fx]amix=inputs=3:normalize=0[mix];[mix]loudnorm=I=-14:TP=-1.5:LRA=11[a]")
        else:
            filt += ";[v][md]amix=inputs=2:normalize=0[mix];[mix]loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    else:
        filt += ";[v]loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error"] + inputs + ["-filter_complex", filt, "-map", "0:v",
                    "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                    "-movflags", "+faststart", "-t", str(total), out], check=True)
    os.remove(silent)
    print("done", out)


if __name__ == "__main__":
    main()

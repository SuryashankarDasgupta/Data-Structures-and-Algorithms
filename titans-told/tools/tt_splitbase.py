# Composite a new Style T base: left side from an existing base, right side from another image,
# joined by a jagged glowing "lightning" split.  usage: tt_splitbase.py left.png right.png out.png [--shift X]
import sys, random
from PIL import Image, ImageDraw, ImageFilter, ImageOps
L=Image.open(sys.argv[1]).convert("RGB"); R=Image.open(sys.argv[2]).convert("RGB")
W,H=L.size; R=ImageOps.fit(R,(W,H),Image.LANCZOS,centering=(float(sys.argv[5]) if len(sys.argv)>5 else 0.5,0.5))
random.seed(7); pts=[]; n=14
for i in range(n+1):
    y=H*i/n; x=W*(0.56-0.16*i/n)+(random.uniform(-28,28) if 0<i<n else 0); pts.append((x,y))
mask=Image.new("L",(W,H),0); d=ImageDraw.Draw(mask)
d.polygon(pts+[(W,H),(W,0)],fill=255)
out=Image.composite(R,L,mask)
glow=Image.new("L",(W,H),0); g=ImageDraw.Draw(glow); g.line(pts,fill=255,width=16)
glow=glow.filter(ImageFilter.GaussianBlur(14))
out=Image.composite(Image.new("RGB",(W,H),(255,210,90)),out,glow.point(lambda v:min(255,int(v*1.3))))
core=Image.new("L",(W,H),0); ImageDraw.Draw(core).line(pts,fill=255,width=5)
out=Image.composite(Image.new("RGB",(W,H),(255,248,220)),out,core)
out.save(sys.argv[3]); print("saved",sys.argv[3])

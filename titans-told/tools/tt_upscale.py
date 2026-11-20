"""AI upscale illustrations (Real-ESRGAN animevideov3, BSD-3, ONNX on CPU) to 3840x2160 masters.
Usage: tt_upscale.py in.png [in2.png ...] --out DIR      (keeps file names; skips files already done)
Model auto-downloads from Hugging Face (Tomoali/realesr-animevideov3-onnx) into ../models/."""
import os, sys, time, numpy as np
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(HERE, "..", "models"); os.makedirs(MODELS, exist_ok=True)
MP = os.path.join(MODELS, "animevideov3_nchw_512x512_fp32.onnx")
if not os.path.exists(MP):
    from huggingface_hub import hf_hub_download
    p = hf_hub_download("Tomoali/realesr-animevideov3-onnx", "animevideov3_nchw_512x512_fp32.onnx", local_dir=MODELS)
import onnxruntime as ort
so = ort.SessionOptions(); so.intra_op_num_threads = os.cpu_count() or 4
sess = ort.InferenceSession(MP, so, providers=["CPUExecutionProvider"])
IN = sess.get_inputs()[0].name
T, PAD, S = 512, 24, 4          # tile, overlap, scale
def upscale(im):
    a = np.asarray(im.convert("RGB"), np.float32) / 255.0
    h, w, _ = a.shape
    out = np.zeros((h * S, w * S, 3), np.float32)
    step = T - 2 * PAD
    for y0 in range(0, h, step):
        for x0 in range(0, w, step):
            ys, xs = max(0, min(y0 - PAD, h - T)), max(0, min(x0 - PAD, w - T))
            tile = a[ys:ys + T, xs:xs + T]
            th, tw = tile.shape[:2]
            if th < T or tw < T:
                tile = np.pad(tile, ((0, T - th), (0, T - tw), (0, 0)), mode="edge")
            r = sess.run(None, {IN: tile.transpose(2, 0, 1)[None]})[0][0].transpose(1, 2, 0)
            # paste the central region belonging to this step
            cy0, cx0 = y0, x0
            cy1, cx1 = min(y0 + step, h), min(x0 + step, w)
            out[cy0 * S:cy1 * S, cx0 * S:cx1 * S] = r[(cy0 - ys) * S:(cy1 - ys) * S, (cx0 - xs) * S:(cx1 - xs) * S]
    return Image.fromarray(np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8))
if __name__ == "__main__":
    args = sys.argv[1:]; od = args[args.index("--out") + 1]; files = [f for f in args if f not in ("--out", od)]
    os.makedirs(od, exist_ok=True)
    for f in files:
        o = os.path.join(od, os.path.basename(f))
        if os.path.exists(o): continue
        t = time.time(); im = Image.open(f)
        up = upscale(im).resize((3840, 2160), Image.LANCZOS)
        up.save(o, optimize=False); print(f"{os.path.basename(f)} {im.size} -> {up.size} {time.time()-t:.1f}s", flush=True)

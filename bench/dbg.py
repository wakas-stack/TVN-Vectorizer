"""Render one case large: truth | input | result, and dump shares/labels for inspection."""
import io, sys
import numpy as np
from PIL import Image
sys.path.insert(0, "."); sys.path.insert(0, "bench")
import engine
from cases import CASES
from run import render
case, px = sys.argv[1], int(sys.argv[2]); q = int(sys.argv[3] or 0) if len(sys.argv) > 3 else None
opts = eval(sys.argv[4]) if len(sys.argv) > 4 else {}
src = Image.fromarray(render(CASES[case], px).astype(np.uint8))
if q:
    b = io.BytesIO(); src.save(b, "JPEG", quality=q); src = Image.open(io.BytesIO(b.getvalue())).convert("RGB")
b = io.BytesIO(); src.save(b, "PNG")
r = engine.trace(b.getvalue(), {**opts})
open(f"bench/dbg/{case}.svg", "w").write(r["svg"])
R = 800
Image.fromarray(np.concatenate([render(CASES[case], R).astype(np.uint8), np.asarray(src.resize((R, R), Image.NEAREST)), render(r["svg"], R).astype(np.uint8)], 1)).save(f"bench/dbg/{case}.png")
print(r["colors"], r["stats"])

# Provenance copy of an analysis script from the 2026-10-03 independent review. Local paths are redacted
# (<REPO>, <SCRATCH>, <LOCAL>); the maintained, runnable versions are in reports/m7_final/scripts/.
"""Build blinded contact sheets for the 300 M3 review pairs + hidden controls.

Writes scratch/review/items.json (all pairs, incl. controls; NOT to be read
during review), key_A.json / key_B.json (code -> item), and sheets
review/A_XX.jpg, review/B_XX.jpg showing only anonymous codes.
"""
import csv
import io
import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

REPO = Path("<REPO>")
EXT = Path("C:/data/openinspect/extracted")
SCR = Path(sys.argv[1])
OUT = SCR / "review"
OUT.mkdir(exist_ok=True)
SYN = OUT / "synthetic"
SYN.mkdir(exist_ok=True)
rng = random.Random(20261002)

rows = list(csv.DictReader(open(REPO / "artifacts/m3/review-candidates.csv", encoding="utf-8")))
items = []
for r in rows:
    items.append({"item": r["pair_id"], "kind": "candidate",
                  "a": f"{r['source_a']}/{r['image_a']}", "b": f"{r['source_b']}/{r['image_b']}"})

# pool of all images present in the M3 candidate universe (nearest-neighbour table sources)
pool = {"dspcbsd-plus": [], "pcb-defect": [], "pcb-ind": []}
for src, pat in [("dspcbsd-plus", "Data_COCO/*/*.jpg"), ("pcb-defect", "PCB_Defect/images/*.jpg"),
                 ("pcb-ind", "YOLO/images/*/*.jpg")]:
    pool[src] = sorted(p.relative_to(EXT / src).as_posix() for p in (EXT / src).glob(pat))
print({k: len(v) for k, v in pool.items()})
used = {x for it in items for x in (it["a"], it["b"])}

# positive controls: synthetic transformed duplicates (as in M3 threshold validation, re-made here)
for i in range(18):
    src = ["dspcbsd-plus", "pcb-defect", "pcb-ind"][i % 3]
    rel = rng.choice(pool[src])
    im = Image.open(EXT / src / rel).convert("RGB")
    w, h = im.size
    f = rng.uniform(0.82, 0.95)
    x0, y0 = rng.randint(0, int(w * (1 - f))), rng.randint(0, int(h * (1 - f)))
    t = im.crop((x0, y0, x0 + int(w * f), y0 + int(h * f)))
    if rng.random() < 0.5:
        t = ImageOps.mirror(t)
    t = ImageEnhance.Brightness(t).enhance(rng.uniform(0.8, 1.2))
    t = ImageEnhance.Contrast(t).enhance(rng.uniform(0.85, 1.15))
    buf = io.BytesIO()
    t.save(buf, "JPEG", quality=rng.randint(35, 70))
    p = SYN / f"syn_{i:02d}.jpg"
    p.write_bytes(buf.getvalue())
    pair = [f"{src}/{rel}", f"__syn__/{p.name}"]
    rng.shuffle(pair)
    items.append({"item": f"POS-SYN-{i:02d}", "kind": "positive_synthetic", "a": pair[0], "b": pair[1]})

# negative controls: random cross-source pairs and random within-source pairs not in the queue
for i in range(12):
    s1, s2 = rng.sample(list(pool), 2)
    items.append({"item": f"NEG-X-{i:02d}", "kind": "negative_cross_source",
                  "a": f"{s1}/{rng.choice(pool[s1])}", "b": f"{s2}/{rng.choice(pool[s2])}"})
for i in range(12):
    s = ["dspcbsd-plus", "pcb-defect", "pcb-ind"][i % 3]
    a, b = rng.sample(pool[s], 2)
    items.append({"item": f"NEG-W-{i:02d}", "kind": "negative_random_within_source",
                  "a": f"{s}/{a}", "b": f"{s}/{b}"})

(OUT / "items.json").write_text(json.dumps(items, indent=1))


def load(ref):
    src, rel = ref.split("/", 1)
    p = SYN / rel if src == "__syn__" else EXT / src / rel
    return Image.open(p).convert("RGB")


font = ImageFont.load_default(size=22)
CELL = 380
PER = 6  # pairs per sheet: 3 rows x 2 pair-columns


def build(tag, order_seed):
    order = items[:]
    random.Random(order_seed).shuffle(order)
    codes = random.Random(order_seed + 1).sample(range(1000, 10000), len(order))
    key = {}
    for s in range(0, len(order), PER):
        chunk = order[s:s + PER]
        sheet = Image.new("RGB", (2 * (2 * CELL + 30) + 20, 3 * (CELL + 40) + 10), (255, 255, 255))
        d = ImageDraw.Draw(sheet)
        for j, it in enumerate(chunk):
            code = f"{tag}{codes[s + j]}"
            key[code] = it["item"]
            col, row = j % 2, j // 2
            ox, oy = 10 + col * (2 * CELL + 40), 10 + row * (CELL + 40)
            d.text((ox, oy), code, fill=(200, 0, 0), font=font)
            for k, ref in enumerate((it["a"], it["b"])):
                im = load(ref)
                im.thumbnail((CELL, CELL))
                if max(im.size) < CELL:  # upscale small crops so detail is visible
                    sc = CELL / max(im.size)
                    im = im.resize((int(im.width * sc), int(im.height * sc)), Image.NEAREST)
                sheet.paste(im, (ox + k * (CELL + 8), oy + 30))
            d.rectangle((ox - 4, oy - 4, ox + 2 * CELL + 14, oy + CELL + 34), outline=(0, 0, 0))
        sheet.save(OUT / f"{tag}_{s // PER:02d}.jpg", quality=90)
    (OUT / f"key_{tag}.json").write_text(json.dumps(key, indent=1))
    print(tag, len(key), "pairs", (len(order) + PER - 1) // PER, "sheets")


build("A", 101)
build("B", 202)

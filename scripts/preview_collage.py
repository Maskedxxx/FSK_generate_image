"""Превью коллажа для Слоя 4 — без отправки в OSMI."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

SCHEMA = "results/2026-04-01_5b1bdd01/L1_crops/schema_x2.png"
REFS_DIR = "scripts/debug_references"
OUTPUT = "scripts/debug_collage.png"
MAX_SIZE = 700


def resize_to_fit(img, max_size):
    w, h = img.size
    if max(w, h) <= max_size:
        return img
    scale = max_size / max(w, h)
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)


schema = resize_to_fit(Image.open(SCHEMA), MAX_SIZE)
refs = []
for fname in sorted(os.listdir(REFS_DIR)):
    if fname.endswith(".png"):
        refs.append(resize_to_fit(Image.open(os.path.join(REFS_DIR, fname)), MAX_SIZE))

images = [schema] + refs
total_w = sum(img.width for img in images) + (len(images) - 1) * 10
max_h = max(img.height for img in images)

collage = Image.new("RGB", (total_w, max_h), (255, 255, 255))
x = 0
for img in images:
    collage.paste(img, (x, (max_h - img.height) // 2))
    x += img.width + 10

collage.save(OUTPUT)
print(f"Коллаж: {collage.size} → {OUTPUT}")

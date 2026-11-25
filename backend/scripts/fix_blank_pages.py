"""
Fix Blank Placeholder Images
============================================================
Scans rendered_pages/ for blank/corrupted images and regenerates
informative dark-themed placeholders.

Run from backend/ directory:
    python scripts/fix_blank_pages.py
"""
import os
import sys
import json
from pathlib import Path

# Bootstrap backend root to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.retrieval.pdf_processor import _make_info_placeholder

import numpy as np
from PIL import Image

RENDERED_DIR = settings.RENDERED_PAGES_DIR


def is_blank(img_path: str, threshold: float = 250.0) -> bool:
    try:
        arr = np.array(Image.open(img_path).convert("RGB"))
        return float(arr.mean()) > threshold
    except Exception:
        return False


def fix_blank_images():
    if not os.path.isdir(RENDERED_DIR):
        print(f"[!] rendered_pages dir not found: {RENDERED_DIR}")
        return

    png_files = [f for f in os.listdir(RENDERED_DIR) if f.endswith(".png")]
    print(f"[->] Scanning {len(png_files)} PNG file(s) in {RENDERED_DIR}...")

    fixed = 0
    for fname in png_files:
        fpath = os.path.join(RENDERED_DIR, fname)
        if is_blank(fpath):
            stem = Path(fname).stem
            parts = stem.rsplit("_page_", 1)
            try:
                page_num = int(parts[1]) if len(parts) == 2 else 1
            except ValueError:
                page_num = 1
            pdf_name = parts[0] if parts else stem

            print(f"  [BLANK] {fname} -> regenerating as informative placeholder...")
            _make_info_placeholder(
                output_path=fpath,
                pdf_filename=pdf_name,
                page_num=page_num,
                total_pages=page_num,
            )
            fixed += 1
        else:
            print(f"  [OK]    {fname}")

    print(f"\nDone. Fixed {fixed} / {len(png_files)} blank image(s).")


if __name__ == "__main__":
    fix_blank_images()

"""
VLM-Enhanced Lightweight Ingestion — CPU-Only, Multimodal via Gemini Vision
=============================================================================
Compatible with: i5-5300U, 8GB RAM, CPU-only, Windows 10

This is an UPGRADED version of ingest_papers_lightweight.py.
It adds multimodal understanding of PDF pages using Gemini Vision —
meaning it can comprehend:
  ✅ Plain research text
  ✅ Clinical trial tables (HbA1c values, p-values, patient counts)
  ✅ Graphs and charts (line graphs, bar charts, forest plots)
  ✅ X-ray / MRI / histology images embedded in PDFs
  ✅ Scanned/handwritten pages (via Gemini's built-in OCR)
  ✅ Figures with captions
  ✅ Mathematical formulas and statistical outputs

How it works:
  For each PDF page:
    1. Render to PNG  (cpu-only, pdf2image)
    2. Send PNG to Gemini 2.0 Flash Vision API
       → Gemini "sees" the page and describes EVERYTHING visible
         (tables, charts, graphs, medical images, equations)
    3. Merge the visual description with PyMuPDF text extraction
    4. Embed the combined content via text-embedding-004 (768-dim)
    5. Store in FAISS index

Why this beats plain text extraction:
  PyMuPDF can only extract text that exists in the PDF's text stream.
  Scanned PDFs, charts, bar graphs, X-ray images have NO text stream.
  Gemini Vision reads the visual content and converts it to rich text.
  The resulting embeddings therefore encode chart values, image findings,
  and table data — not just the printable text.

Performance on i5-5300U (no GPU):
  Per-page: ~2-3 API calls (vision + embed) = ~1-2 seconds/page
  10 papers × 10 pages  = 100 pages  → ~2-3 minutes
  100 papers × 10 pages = 1000 pages → ~20-25 minutes
  500 papers              = 5000 pages → ~2 hours (acceptable)

  vs ColPali:  1000 pages × 60-120s each = 17-33 hours

API cost estimate (Gemini Flash pricing):
  Vision call per page:  ~0.5K tokens @ $0.075/1M = $0.000038/page
  Embed call per page:   ~1K tokens  @ $0.00002   = $0.00002/page
  1000 pages total cost: ~$0.06  (six cents)

Setup:
  pip install faiss-cpu pymupdf pdf2image google-generativeai
  (All already installed on your machine)

Run:
  cd backend
  python scripts/ingest_papers_vlm.py

Optional flags:
  --no-vision   : Skip Gemini Vision step (faster, text-only, no extra cost)
  --papers-dir  : Override PDF directory
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

# Force UTF-8 encoding for Windows standard output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from typing import Dict, List, Optional, Tuple

import numpy as np

# ── Bootstrap path ─────────────────────────────────────────────────────────
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.core.database import SessionLocal, engine, Base
from app.models.db_models import ResearchPaper, PaperPage
from app.retrieval.pdf_processor import render_pdf_to_images, get_pdf_page_count

# ── Config ─────────────────────────────────────────────────────────────────
_VISION_MODEL    = "gemini-2.0-flash"               # multimodal, sees images
_EMBED_MODEL     = "gemini-embedding-001"            # successor to text-embedding-004 (retired Jan 2026)
_EMBED_DIM       = 3072                              # 3072-dim vectors
_INDEX_DIR       = os.path.join(settings.INDEX_STORE_PATH, "text_index")
_FAISS_PATH      = os.path.join(_INDEX_DIR, "faiss.index")
_META_PATH       = os.path.join(_INDEX_DIR, "metadata.json")
_MAX_TEXT_CHARS  = 8000   # combined text + vision description limit
_RATE_LIMIT_SECS = 0.4    # ~2.5 calls/s, well under 300 RPM free tier


# ── Vision prompt — tuned for medical research pages ──────────────────────
_VISION_PROMPT = """\
You are a medical document analyst. Carefully examine this research paper page and provide a complete, \
structured description of ALL content visible including:

1. ALL text content (title, section headers, body paragraphs)
2. Tables: reproduce the exact data values, row labels, column headers, and units
3. Graphs/Charts: describe what is plotted, axis labels, data series names, key data points and trends
4. Medical images: describe what is shown (X-ray findings, MRI regions, histology patterns, etc.)
5. Statistical outputs: p-values, confidence intervals, odds ratios, hazard ratios
6. Figure captions and footnotes

Be precise and include all numerical values. This description will be used for clinical research retrieval.
If the page is mostly blank or a cover page, say so briefly."""


# ── Gemini API helpers ─────────────────────────────────────────────────────

def _configure_genai():
    if not settings.GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY is not set in backend/.env")
        sys.exit(1)


def describe_page_with_vision(image_path: str) -> str:
    """
    Sends a rendered PDF page image to Gemini 2.0 Flash Vision via google-genai SDK.
    Returns a rich text description of all visible content including
    charts, tables, graphs, medical images, and formulas.

    Falls back to empty string on API error.
    """
    if not os.path.exists(image_path):
        return ""

    try:
        from PIL import Image as PILImage  # type: ignore
        from google import genai  # type: ignore
        from google.genai import types

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        img = PILImage.open(image_path).convert("RGB")

        response = client.models.generate_content(
            model=_VISION_MODEL,
            contents=[_VISION_PROMPT, img],
            config=types.GenerateContentConfig(
                max_output_tokens=1024,
                temperature=0.1,
            ),
        )
        description = response.text.strip() if response.text else ""
        return description

    except Exception as exc:
        print(f"    ⚠️  Vision API error: {exc}")
        return ""


def compute_file_hash(file_path: str) -> str:
    """Computes SHA-256 hash of a file for content-level deduplication."""
    import hashlib
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def extract_page_text(pdf_path: str, page_number: int) -> str:
    """Extracts text from PDF page using PyMuPDF (0.01s/page, no model)."""
    import fitz  # type: ignore

    try:
        doc = fitz.open(pdf_path)
        page = doc[page_number - 1]
        text = page.get_text("text").strip()
        if len(text) < 30:
            blocks = page.get_text("blocks")
            text = " ".join(
                b[4].strip() for b in blocks
                if isinstance(b[4], str) and b[4].strip()
            )
        doc.close()
        return text[:_MAX_TEXT_CHARS] if text else ""
    except Exception:
        return ""


def embed_text(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> Optional[np.ndarray]:
    """Embeds text via gemini-embedding-001 using the new google-genai SDK (v1 API).
    Returns a normalised 3072-dim numpy vector.
    """
    if not text.strip():
        return None
    try:
        from google import genai as google_genai
        from google.genai import types as genai_types

        client = google_genai.Client(api_key=settings.GEMINI_API_KEY)
        result = client.models.embed_content(
            model=_EMBED_MODEL,
            contents=text,
            config=genai_types.EmbedContentConfig(task_type=task_type),
        )
        vec = np.array(result.embeddings[0].values, dtype=np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec
    except Exception as exc:
        print(f"    ⚠️  Embedding API error: {exc}")
        return None


# ── Main ingestion ─────────────────────────────────────────────────────────

def ingest_all_papers_vlm(use_vision: bool = True, papers_dir_override: str = None):
    """
    Full VLM-enhanced ingestion pipeline.

    use_vision: If True, each page is analyzed by Gemini Vision before embedding.
                If False, falls back to text-only (same as ingest_papers_lightweight.py).
    """
    import faiss  # type: ignore

    print("\n" + "=" * 70)
    if use_vision:
        print("   VLM-ENHANCED INGESTION — Gemini Vision + FAISS (CPU-Only)     ")
        print("   Supports: text, tables, charts, graphs, X-rays, scans         ")
    else:
        print("   LIGHTWEIGHT INGESTION — Text-Only FAISS (CPU-Only)            ")
    print("=" * 70)

    _configure_genai()

    # ── DB init ────────────────────────────────────────────────────────────
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    papers_dir = os.path.abspath(papers_dir_override or settings.PAPERS_DIR)
    os.makedirs(papers_dir, exist_ok=True)
    pdf_files = sorted(f for f in os.listdir(papers_dir) if f.endswith(".pdf"))

    if not pdf_files:
        print(f"\n⚠️  No PDF files found in: {papers_dir}")
        print("   Drop your research paper PDFs into that folder and re-run.")
        db.close()
        sys.exit(0)

    print(f"\n[Step 1] Found {len(pdf_files)} PDF(s) in '{papers_dir}'")

    # ── Step 1: DB registration + page rendering ───────────────────────────
    all_papers = []

    for pdf_name in pdf_files:
        pdf_path = os.path.join(papers_dir, pdf_name)
        pdf_hash = compute_file_hash(pdf_path)

        existing = (
            db.query(ResearchPaper)
            .filter((ResearchPaper.file_hash == pdf_hash) | (ResearchPaper.file_path == pdf_path))
            .first()
        )

        if existing:
            if not existing.file_hash:
                existing.file_hash = pdf_hash
                db.commit()
            print(f"  -> Already in DB (matched hash/path): {pdf_name}")
            all_papers.append((existing.id, existing.title, existing.authors, existing.journal, existing.publication_year, existing.page_count, pdf_path, existing.department, existing.access_roles))
            continue

        page_count = get_pdf_page_count(pdf_path)
        paper = ResearchPaper(
            title=pdf_name.replace(".pdf", "").replace("_", " ").title(),
            file_path=pdf_path,
            file_hash=pdf_hash,
            page_count=page_count,
            indexed=True,
        )
        db.add(paper)
        db.commit()
        db.refresh(paper)

        print(f"  -> Rendering pages: {pdf_name} ({page_count} pages)...")
        img_paths = render_pdf_to_images(pdf_path)
        for page_idx, img_path in enumerate(img_paths):
            db.add(PaperPage(
                paper_id=paper.id,
                page_number=page_idx + 1,
                image_path=img_path,
                has_tables=True,
                has_charts=True,
            ))
        db.commit()
        print(f"  [OK] Registered: {pdf_name} (id={paper.id}, {page_count} pages)")
        all_papers.append((paper.id, paper.title, paper.authors, paper.journal, paper.publication_year, paper.page_count, pdf_path, paper.department, paper.access_roles))

    db.close()

    # ── Step 2: Vision analysis + text extraction + embedding ──────────────
    mode_str = "Gemini Vision + text" if use_vision else "text-only"
    print(f"\n[Step 2] Processing {len(all_papers)} paper(s) [{mode_str}]...")

    os.makedirs(_INDEX_DIR, exist_ok=True)

    all_vectors: List[np.ndarray] = []
    all_meta: List[Dict] = []

    # Load existing index for incremental updates
    already_indexed: set = set()
    if os.path.exists(_FAISS_PATH) and os.path.exists(_META_PATH):
        existing_index = faiss.read_index(_FAISS_PATH)
        with open(_META_PATH, "r", encoding="utf-8") as f:
            all_meta = json.load(f)
        # Reconstruct existing vectors
        n = existing_index.ntotal
        if n > 0:
            existing_vecs = existing_index.reconstruct_n(0, n)
            all_vectors = [existing_vecs[i] for i in range(n)]
        already_indexed = {(m["doc_id"], m["page_number"]) for m in all_meta}
        print(f"  Resuming: {len(all_meta)} pages already indexed.\n")

    rendered_dir = settings.RENDERED_PAGES_DIR
    pages_processed = 0
    pages_skipped = 0

    for paper_id, title, authors, journal, pub_year, page_count, pdf_path, dept, roles in all_papers:
        page_cnt = min(page_count or get_pdf_page_count(pdf_path), 15)
        print(f"  [Paper] {title} (id={paper_id}, {page_cnt} pages max)")

        for page_num in range(1, page_cnt + 1):
            key = (paper_id, page_num)
            if key in already_indexed:
                pages_skipped += 1
                continue

            # ── Extract text (fast, no API call) ───────────────────────────
            extracted_text = extract_page_text(pdf_path, page_num)

            # ── Vision analysis (API call — describes charts/images) ────────
            vision_description = ""
            if use_vision:
                img_filename = f"paper_{paper_id}_page_{page_num}.png"
                img_path = os.path.join(rendered_dir, img_filename)

                if os.path.exists(img_path):
                    vision_description = describe_page_with_vision(img_path)
                    time.sleep(_RATE_LIMIT_SECS)   # rate limit between vision calls

            # ── Combine: text + vision description ─────────────────────────
            if vision_description:
                combined = (
                    f"[EXTRACTED TEXT]\n{extracted_text}\n\n"
                    f"[VISUAL CONTENT DESCRIPTION]\n{vision_description}"
                )[:_MAX_TEXT_CHARS]
            elif extracted_text:
                combined = extracted_text
            else:
                combined = f"[Page {page_num} — image-only page, no extractable text]"

            # ── Embed combined content ──────────────────────────────────────
            vec = embed_text(combined, task_type="retrieval_document")
            time.sleep(_RATE_LIMIT_SECS)

            if vec is None:
                print(f"    [WARN] Skipping page {page_num} (embedding failed)")
                continue

            # ── Store ───────────────────────────────────────────────────────
            all_vectors.append(vec)
            all_meta.append({
                "doc_id":           paper_id,
                "page_number":      page_num,
                "title":            title or "Unknown",
                "authors":          authors or "Unknown",
                "journal":          journal or "Unknown",
                "publication_year": pub_year,
                "text_content":     combined[:8000].replace("\n", " "),
                "text_snippet":     combined[:2000].replace("\n", " "),
                "has_vision":       bool(vision_description),
                "department":       dept or "General",
                "access_roles":     roles or "clinical,research"
            })
            already_indexed.add(key)
            pages_processed += 1

            vision_tag = "[Vision+Text]" if vision_description else "[Text]"
            print(
                f"    [OK] {vision_tag} Page {page_num}/{page_cnt} "
                f"({len(extracted_text)} text chars"
                + (f" + {len(vision_description)} vision chars" if vision_description else "")
                + ")"
            )

        print()

    # ── Step 3: Build + save FAISS index ──────────────────────────────────
    if not all_vectors:
        print("[WARN] No vectors to index. Nothing changed.")
        return

    print(f"[Step 3] Building FAISS index ({len(all_vectors)} embeddings)...")

    index = faiss.IndexFlatIP(_EMBED_DIM)
    matrix = np.stack(all_vectors, axis=0).astype(np.float32)
    index.add(matrix)

    faiss.write_index(index, _FAISS_PATH)
    with open(_META_PATH, "w", encoding="utf-8") as f:
        json.dump(all_meta, f, indent=2, ensure_ascii=False)

    vision_count = sum(1 for m in all_meta if m.get("has_vision"))

    # ── Summary ────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(" [SUCCESS] PAPER INGESTION COMPLETE!")
    print("=" * 70)
    print(f"  Papers processed       : {len(all_papers)}")
    print(f"  Pages embedded (new)   : {pages_processed}")
    print(f"  Pages skipped (cached) : {pages_skipped}")
    print(f"  Pages with vision desc : {vision_count} / {len(all_meta)}")
    print(f"  Total index size       : {index.ntotal} pages")
    print(f"  FAISS index            : {_FAISS_PATH}")
    print(f"  Metadata               : {_META_PATH}")
    print(f"\n  Start backend: uvicorn app.main:app --reload")
    print("=" * 70 + "\n")


# ── CLI entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="VLM-Enhanced Paper Ingestion (CPU-Only, Gemini Vision + FAISS)"
    )
    parser.add_argument(
        "--no-vision",
        action="store_true",
        help="Skip Gemini Vision step (faster, text-only, cheaper)",
    )
    parser.add_argument(
        "--papers-dir",
        type=str,
        default=None,
        help="Override path to PDF directory (default: from config)",
    )
    args = parser.parse_args()

    ingest_all_papers_vlm(
        use_vision=not args.no_vision,
        papers_dir_override=args.papers_dir,
    )

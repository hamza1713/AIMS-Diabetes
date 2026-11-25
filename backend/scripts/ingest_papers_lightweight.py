"""
Lightweight Paper Ingestion — No GPU, No PaliGemma 2
======================================================
Compatible with: i5-5300U, 8GB RAM, CPU-only, Windows 10

This script replaces the ColPali ingestion (ingest_papers.py) for machines
without a GPU. It uses:

  Step 1 — DB Registration:
    Same as ingest_papers.py — registers each PDF in the SQLite database.

  Step 2 — Page Rendering:
    Uses pdf2image + Poppler to render each PDF page to PNG.
    These images are served to the frontend for display in the evidence panel.
    This is CPU-only and fast (~1-2s per page).

  Step 3 — Text Extraction (PyMuPDF):
    Extracts text from each page without any neural model.
    PyMuPDF (fitz) uses PDF's internal text stream — instant, no OCR.
    Falls back to a note if a page is image-only (scanned).

  Step 4 — Gemini API Embedding:
    Sends each page's text to Google's text-embedding-004 API (768-dim).
    Rate-limited to 200 req/min (well within free tier: 300 req/min).
    Approximately 0.3s per page including network latency.
    Cost: ~$0.0000025 per page = essentially FREE for hundreds of papers.

  Step 5 — FAISS Index Save:
    Stores all embeddings in a FAISS IndexFlatIP (cosine similarity via
    normalised inner product). Saves index + metadata JSON to disk.

Performance on i5-5300U (user's machine):
  - 10 papers × 10 pages = 100 pages → ~50 seconds total
  - 100 papers × 10 pages = 1000 pages → ~8 minutes total
  - 500 papers × 10 pages = 5000 pages → ~35 minutes total

Requirements:
  pip install faiss-cpu pymupdf pdf2image google-generativeai

Poppler (for pdf2image on Windows):
  Download from https://github.com/oschwartz10612/poppler-windows/releases
  Extract and add bin/ folder to PATH, OR set POPPLER_PATH below.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ── Bootstrap path so we can import app.* ─────────────────────────────────
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.core.database import SessionLocal, engine, Base
from app.models.db_models import ResearchPaper, PaperPage
from app.retrieval.pdf_processor import render_pdf_to_images, get_pdf_page_count

# ── Config ─────────────────────────────────────────────────────────────────
_EMBED_MODEL     = "gemini-embedding-001"  # successor to text-embedding-004, retired Jan 2026
_EMBED_DIM       = 3072                    # 3072-dim (was 768 in text-embedding-004)
_INDEX_DIR       = os.path.join(settings.INDEX_STORE_PATH, "text_index")
_FAISS_PATH      = os.path.join(_INDEX_DIR, "faiss.index")
_META_PATH       = os.path.join(_INDEX_DIR, "metadata.json")
_MAX_TEXT_CHARS  = 8000   # truncate page text to avoid token limits
_RATE_LIMIT_RPS  = 4      # stay well under Gemini free tier (300 RPM = 5 RPS)


# ── Dependency checks ──────────────────────────────────────────────────────

def _check_dependencies() -> bool:
    ok = True
    try:
        import faiss  # type: ignore
        print(f"  [OK] faiss-cpu found (version {faiss.__version__})")
    except ImportError:
        print("  [ERROR] faiss-cpu not installed. Run: pip install faiss-cpu")
        ok = False

    try:
        import fitz  # type: ignore  (PyMuPDF)
        print(f"  [OK] PyMuPDF (fitz) found")
    except ImportError:
        print("  [ERROR] PyMuPDF not installed. Run: pip install pymupdf")
        ok = False

    try:
        import google.generativeai as genai  # type: ignore
        print(f"  [OK] google-generativeai found")
    except ImportError:
        print("  [ERROR] google-generativeai not installed. Run: pip install google-generativeai")
        ok = False

    if not settings.GEMINI_API_KEY:
        print("  [ERROR] GEMINI_API_KEY is not set in backend/.env")
        ok = False
    else:
        print(f"  [OK] GEMINI_API_KEY is configured")

    return ok


def extract_bibliographic_metadata(first_page_text: str) -> Dict[str, Any]:
    """
    Calls Gemini to parse the first page text of a paper and extract structured
    bibliographic metadata (Title, Authors, Journal, Year).
    """
    if not first_page_text or len(first_page_text.strip()) < 50:
        return {}
    try:
        import json  # noqa: PLC0415
        from google import genai as google_genai  # noqa: PLC0415
        from google.genai import types as genai_types  # noqa: PLC0415

        client = google_genai.Client(api_key=settings.GEMINI_API_KEY)
        prompt = (
            "You are a citation metadata extractor. Analyze the first-page text of this research paper.\n"
            "Respond ONLY with a JSON object containing keys: 'title', 'authors', 'journal', 'publication_year'.\n"
            "Format rules:\n"
            "  - 'title': exact title of the paper\n"
            "  - 'authors': short author representation (e.g. 'McDermott et al.' or 'Gomez-Peralta et al.')\n"
            "  - 'journal': name of published journal (e.g. 'Diabetes Care')\n"
            "  - 'publication_year': integer year (e.g. 2023)\n"
            "If any field cannot be found, set it to null.\n\n"
            f"TEXT:\n{first_page_text[:3000]}"
        )
        response = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        )
        data = json.loads(response.text.strip())
        return {
            "title": data.get("title"),
            "authors": data.get("authors"),
            "journal": data.get("journal"),
            "publication_year": data.get("publication_year"),
        }
    except Exception as exc:
        print(f"    [WARN] Bibliographic metadata extraction failed: {exc}")
        return {}


# ── Text extraction ────────────────────────────────────────────────────────

def extract_page_text(pdf_path: str, page_number: int) -> str:
    """
    Extracts text from a single PDF page using PyMuPDF.
    page_number is 1-indexed.

    Returns the extracted text, or a placeholder for image-only pages.
    """
    import fitz  # type: ignore

    try:
        doc = fitz.open(pdf_path)
        page = doc[page_number - 1]  # 0-indexed in fitz

        # Primary: get text with layout preservation
        text = page.get_text("text").strip()

        # If almost empty, try getting text from blocks (handles some edge cases)
        if len(text) < 30:
            blocks = page.get_text("blocks")
            text = " ".join(
                b[4].strip() for b in blocks
                if isinstance(b[4], str) and b[4].strip()
            )

        doc.close()

        # Clean up font subset mapping anomalies
        if text:
            text = text.replace('\u0001', '=').replace('\u0002', '-')

        if len(text) < 20:
            return f"[Page {page_number}: image-only or minimal text — visual content only]"

        # Truncate to stay within embedding token limit
        return text[:_MAX_TEXT_CHARS]

    except Exception as exc:
        return f"[Page {page_number}: text extraction failed — {exc}]"


# ── Gemini embedding ───────────────────────────────────────────────────────

def embed_text(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> Optional[np.ndarray]:
    """Embeds text via gemini-embedding-001 using the new google-genai SDK (v1 API).
    Returns a normalised 3072-dim numpy vector. Returns None on failure.
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
        print(f"    [WARN] Embedding API error: {exc}")
        return None


def compute_file_hash(file_path: str) -> str:
    """Computes SHA-256 hash of a file for content-level deduplication."""
    import hashlib
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


# ── Main ingestion ─────────────────────────────────────────────────────────

def ingest_all_papers_lightweight():
    """
    Main ingestion routine.
    Registers papers in DB, renders page images, extracts text,
    embeds text with Gemini API, and builds the FAISS index.
    """
    import faiss         # type: ignore

    print("\n" + "=" * 70)
    print("   LIGHTWEIGHT PAPER INGESTION - FAISS + Gemini API (CPU-Only)  ")
    print("=" * 70)

    # ── Dependency check ───────────────────────────────────────────────────
    print("\n[Checking dependencies...]")
    if not _check_dependencies():
        print("\n[ERROR] Fix the above issues then re-run this script.")
        sys.exit(1)

    # ── DB init ────────────────────────────────────────────────────────────
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # ── Discover PDFs ──────────────────────────────────────────────────────
    papers_dir = os.path.abspath(settings.PAPERS_DIR)
    os.makedirs(papers_dir, exist_ok=True)
    pdf_files = [f for f in os.listdir(papers_dir) if f.endswith(".pdf")]

    if not pdf_files:
        print(f"\n[WARN] No PDF files found in: {papers_dir}")
        print("   Drop your research paper PDFs into that folder and re-run.")
        db.close()
        sys.exit(0)

    print(f"\n[Step 1] Found {len(pdf_files)} PDF(s) in '{papers_dir}'")

    # ── Step 1: DB registration + page rendering ───────────────────────────
    all_papers = []   # (paper_db_record, pdf_path)

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
            # Retroactive metadata fill if empty or placeholder
            if not existing.authors or existing.authors == "Clinical Research Upload":
                print(f"  -> Retroactively extracting metadata for existing paper: {pdf_name}")
                first_page_text = extract_page_text(pdf_path, 1)
                meta = extract_bibliographic_metadata(first_page_text)
                if meta:
                    existing.title = meta.get("title") or existing.title
                    existing.authors = meta.get("authors") or existing.authors
                    existing.journal = meta.get("journal") or existing.journal
                    existing.publication_year = meta.get("publication_year") or existing.publication_year
                    db.commit()
                    db.refresh(existing)
                time.sleep(2.0)  # Rate limit safety sleep
            print(f"  -> Already in DB (matched hash/path): {pdf_name}")
            all_papers.append((existing, pdf_path))
            continue

        page_count = get_pdf_page_count(pdf_path)
        first_page_text = extract_page_text(pdf_path, 1)
        meta = extract_bibliographic_metadata(first_page_text)
        time.sleep(2.0)  # Rate limit safety sleep

        paper = ResearchPaper(
            title=meta.get("title") or pdf_name.replace(".pdf", "").replace("_", " ").title(),
            authors=meta.get("authors") or "Clinical Research Upload",
            journal=meta.get("journal") or "User Uploaded PDF",
            publication_year=meta.get("publication_year") or 2026,
            file_path=pdf_path,
            page_count=page_count,
            indexed=True,
        )
        db.add(paper)
        db.commit()
        db.refresh(paper)

        # Render pages to PNG for the frontend
        print(f"  -> Rendering pages: {pdf_name} (max 15 from {page_count} pages)...")
        img_paths = render_pdf_to_images(pdf_path)
        max_pages = min(page_count, 15)
        for page_idx in range(max_pages):
            img_path = img_paths[page_idx]
            db.add(PaperPage(
                paper_id=paper.id,
                page_number=page_idx + 1,
                image_path=img_path,
                has_tables=True,
                has_charts=True,
            ))
        db.commit()
        print(f"  [OK] Registered: {pdf_name} (id={paper.id}, {max_pages} pages)")
        all_papers.append((paper, pdf_path))

    # ── Step 2: Text extraction + Gemini embedding ─────────────────────────
    print(f"\n[Step 2] Extracting text and embedding {len(all_papers)} paper(s)...")
    print(f"         Model: {_EMBED_MODEL} | Rate: {_RATE_LIMIT_RPS} pages/s\n")

    os.makedirs(_INDEX_DIR, exist_ok=True)

    all_vectors: List[np.ndarray] = []
    all_meta:    List[Dict]       = []

    # Load existing index if it exists (incremental update)
    if os.path.exists(_FAISS_PATH) and os.path.exists(_META_PATH):
        existing_index = faiss.read_index(_FAISS_PATH)
        with open(_META_PATH, "r", encoding="utf-8") as f:
            all_meta = json.load(f)
        existing_vectors = faiss.rev_swig_ptr(
            existing_index.get_xb(), existing_index.ntotal * _EMBED_DIM
        ).reshape(existing_index.ntotal, _EMBED_DIM).copy()
        all_vectors = [existing_vectors[i] for i in range(len(existing_vectors))]
        already_indexed_keys = {
            (m["doc_id"], m["page_number"]) for m in all_meta
        }
        print(f"  Resuming from existing index with {len(all_meta)} pages.\n")
    else:
        already_indexed_keys: set = set()

    total_pages_processed = 0
    total_pages_skipped   = 0

    for paper, pdf_path in all_papers:
        page_count = min(paper.page_count or get_pdf_page_count(pdf_path), 15)
        paper_title = paper.title or Path(pdf_path).stem

        print(f"  [PDF] {paper_title} (id={paper.id}, {page_count} pages max)")

        for page_num in range(1, page_count + 1):
            key = (paper.id, page_num)
            if key in already_indexed_keys:
                total_pages_skipped += 1
                continue

            # Extract text
            text = extract_page_text(pdf_path, page_num)

            # Embed via Gemini API
            vec = embed_text(text, task_type="RETRIEVAL_DOCUMENT")

            if vec is None:
                print(f"    [WARN] Skipping page {page_num} (embedding failed)")
                continue

            # Store
            all_vectors.append(vec)
            all_meta.append({
                "doc_id":           paper.id,
                "page_number":      page_num,
                "title":            paper.title or "Unknown",
                "authors":          paper.authors or "Unknown",
                "journal":          paper.journal or "Unknown",
                "publication_year": paper.publication_year,
                # text_content: full page text for LLM evidence grounding (up to 8000 chars)
                "text_content":     text[:8000].replace("\n", " "),
                # text_snippet: shorter preview for UI display panels (up to 2000 chars)
                "text_snippet":     text[:2000].replace("\n", " "),
                "department":       paper.department or "General",
                "access_roles":     paper.access_roles or "clinical,research"
            })
            already_indexed_keys.add(key)
            total_pages_processed += 1

            print(f"    [OK] Page {page_num}/{page_count} embedded ({len(text)} chars)")

            # Rate limiting: stay under Gemini free tier
            time.sleep(1.0 / _RATE_LIMIT_RPS)

        print()

    # ── Step 3: Build + save FAISS index ──────────────────────────────────
    if not all_vectors:
        print("[WARN] No new vectors to add. Index unchanged.")
        return

    print(f"[Step 3] Building FAISS index ({len(all_vectors)} page embeddings)...")

    # IndexFlatIP: exact inner product search (= cosine similarity on normalised vecs)
    index = faiss.IndexFlatIP(_EMBED_DIM)
    matrix = np.stack(all_vectors, axis=0).astype(np.float32)
    index.add(matrix)

    faiss.write_index(index, _FAISS_PATH)
    with open(_META_PATH, "w", encoding="utf-8") as f:
        json.dump(all_meta, f, indent=2, ensure_ascii=False)

    # ── Summary ────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print(" [OK] INGESTION COMPLETE!")
    print("=" * 65)
    print(f"  Papers processed : {len(all_papers)}")
    print(f"  Pages embedded   : {total_pages_processed}")
    print(f"  Pages skipped    : {total_pages_skipped} (already in index)")
    print(f"  Total in index   : {index.ntotal}")
    print(f"  FAISS index      : {_FAISS_PATH}")
    print(f"  Metadata         : {_META_PATH}")
    print(f"\n  You can now start the backend: uvicorn app.main:app --reload")
    print("=" * 65 + "\n")
    db.close()


if __name__ == "__main__":
    ingest_all_papers_lightweight()

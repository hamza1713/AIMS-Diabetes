"""
Paper Ingestion Service
======================
Handles incremental PDF upload, page rendering, PyMuPDF text extraction,
Gemini vector embedding (3072-dim), and FAISS index updates.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from sqlalchemy.orm import Session

from app.core.cache import search_cache
from app.core.config import settings
from app.core.logger import get_logger
from app.models.db_models import ResearchPaper, PaperPage
from app.retrieval.pdf_processor import render_pdf_to_images, get_pdf_page_count
from app.retrieval.text_engine import _embed

log = get_logger(__name__)

_INDEX_DIR = os.path.join(settings.INDEX_STORE_PATH, "text_index")
_FAISS_PATH = os.path.join(_INDEX_DIR, "faiss.index")
_META_PATH = os.path.join(_INDEX_DIR, "metadata.json")
_EMBED_DIM = 3072
_index_lock = threading.Lock()


def compute_file_hash(file_path: str) -> str:
    """Computes SHA-256 hash of a file for content-level deduplication."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def extract_page_text(pdf_path: str, page_number: int) -> str:
    """Extracts text from PDF page using PyMuPDF (fitz)."""
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
        
        # Clean up font subset mapping anomalies
        if text:
            text = text.replace('\u0001', '=').replace('\u0002', '-')
            
        return text[:4000] if text else ""
    except Exception as exc:
        log.warning("PyMuPDF text extraction error on %s page %d: %s", pdf_path, page_number, exc)
        return ""


def extract_bibliographic_metadata(first_page_text: str) -> Dict[str, Any]:
    """
    Calls Gemini to parse the first page text of a paper and extract structured
    bibliographic metadata (Title, Authors, Journal, Year) to use in RAG citations.
    """
    if not first_page_text or len(first_page_text.strip()) < 50:
        return {}
    try:
        from google.genai import types as genai_types  # noqa: PLC0415
        from app.retrieval.text_engine import _get_gemini_client  # noqa: PLC0415
        
        client = _get_gemini_client()
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
        
        # Use gemini-3.5-flash-lite (Google's standard model in 2026)
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
        log.warning("Gemini bibliographic metadata extraction failed: %s", exc)
        return {}


def process_and_ingest_pdf(pdf_path: str, db: Session) -> Dict[str, Any]:
    """
    Ingests a single PDF into the SQLite DB, renders PNG pages,
    embeds text with Gemini API, and updates the FAISS index.
    """
    import faiss  # type: ignore

    pdf_filename = Path(pdf_path).name
    pdf_hash = compute_file_hash(pdf_path)

    # 1. Deduplication Check
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
            log.info("Retroactively extracting metadata for existing paper: %s", pdf_filename)
            first_page_text = extract_page_text(pdf_path, 1)
            meta = extract_bibliographic_metadata(first_page_text)
            if meta:
                existing.title = meta.get("title") or existing.title
                existing.authors = meta.get("authors") or existing.authors
                existing.journal = meta.get("journal") or existing.journal
                existing.publication_year = meta.get("publication_year") or existing.publication_year
                db.commit()
                db.refresh(existing)
        log.info("PDF %s already registered in DB (id=%d).", pdf_filename, existing.id)
        return {
            "status": "already_exists",
            "paper_id": existing.id,
            "title": existing.title,
            "page_count": existing.page_count,
            "message": f"Paper '{existing.title}' is already indexed.",
        }

    # 2. Register Paper in DB
    page_count = get_pdf_page_count(pdf_path)
    clean_title = pdf_filename.replace(".pdf", "").replace("_", " ").title()

    first_page_text = extract_page_text(pdf_path, 1)
    meta = extract_bibliographic_metadata(first_page_text)

    paper = ResearchPaper(
        title=meta.get("title") or clean_title,
        authors=meta.get("authors") or "Clinical Research Upload",
        journal=meta.get("journal") or "User Uploaded PDF",
        publication_year=meta.get("publication_year") or 2026,
        file_path=pdf_path,
        file_hash=pdf_hash,
        page_count=page_count,
        indexed=True,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)

    # 3. Render Pages to PNG
    img_paths = render_pdf_to_images(pdf_path)
    for idx, img_path in enumerate(img_paths):
        db.add(PaperPage(
            paper_id=paper.id,
            page_number=idx + 1,
            image_path=img_path,
            has_tables=True,
            has_charts=True,
        ))
    db.commit()
    log.info("Registered paper %s (id=%d, pages=%d).", clean_title, paper.id, page_count)

    # 4. Extract Text & Embed Pages
    new_vectors: List[np.ndarray] = []
    new_meta: List[Dict] = []
    new_pages = 0

    for page_num in range(1, page_count + 1):
        text_content = extract_page_text(pdf_path, page_num) or f"[Page {page_num} of {clean_title}]"
        vec = _embed(text_content, task_type="RETRIEVAL_DOCUMENT")
        if vec is not None:
            new_vectors.append(vec)
            new_meta.append({
                "doc_id": paper.id,
                "page_number": page_num,
                "title": paper.title,
                "authors": paper.authors or "Clinical Research Upload",
                "journal": paper.journal or "User Uploaded PDF",
                "publication_year": paper.publication_year or 2026,
                "file_path": pdf_path,
                # text_content: full page text for evidence grounding (up to 8000 chars)
                "text_content": text_content[:8000].replace("\n", " "),
                # text_snippet: shorter preview for UI panels (up to 2000 chars)
                "text_snippet": text_content[:2000].replace("\n", " "),
                "department": paper.department or "General",
                "access_roles": paper.access_roles or "clinical,research",
            })
            new_pages += 1

    if not new_vectors and page_count > 0:
        paper.indexed = False
        db.commit()
        log.warning("No vectors generated for paper '%s' (embedding service unavailable).", clean_title)
        return {
            "status": "partial_success",
            "paper_id": paper.id,
            "title": paper.title,
            "page_count": paper.page_count,
            "message": f"Paper '{paper.title}' registered in database, but text embeddings could not be generated.",
        }

    # 4.1 Thread-Safe Atomic Incremental FAISS Update
    with _index_lock:
        os.makedirs(_INDEX_DIR, exist_ok=True)
        index = None
        all_meta: List[Dict] = []

        if os.path.exists(_FAISS_PATH) and os.path.exists(_META_PATH):
            try:
                index = faiss.read_index(_FAISS_PATH)
                with open(_META_PATH, "r", encoding="utf-8") as f:
                    all_meta = json.load(f)

                # Ensure FAISS index count and metadata count stay aligned
                if index.ntotal != len(all_meta):
                    log.warning(
                        "FAISS vector count (%d) does not match metadata count (%d). Realigning to min count.",
                        index.ntotal, len(all_meta)
                    )
                    min_count = min(index.ntotal, len(all_meta))
                    all_meta = all_meta[:min_count]
            except Exception as exc:
                log.warning("Could not read existing FAISS index (%s) — initializing new index", exc)
                index = None
                all_meta = []

        if index is None:
            index = faiss.IndexFlatIP(_EMBED_DIM)

        if new_vectors:
            matrix = np.stack(new_vectors, axis=0).astype(np.float32)
            index.add(matrix)
            all_meta.extend(new_meta)

            # Atomic file replace to protect against crashes or corrupted reads
            temp_faiss = tempfile.NamedTemporaryFile(delete=False, dir=_INDEX_DIR, suffix=".tmp")
            temp_faiss_path = temp_faiss.name
            temp_faiss.close()

            temp_meta = tempfile.NamedTemporaryFile(delete=False, dir=_INDEX_DIR, suffix=".tmp", mode="w", encoding="utf-8")
            temp_meta_path = temp_meta.name
            temp_meta.close()

            try:
                faiss.write_index(index, temp_faiss_path)
                with open(temp_meta_path, "w", encoding="utf-8") as f:
                    json.dump(all_meta, f, indent=2, ensure_ascii=False)

                os.replace(temp_faiss_path, _FAISS_PATH)
                os.replace(temp_meta_path, _META_PATH)
                log.info("FAISS index incrementally updated (%d total pages, %d added).", index.ntotal, new_pages)
            except Exception as write_exc:
                log.error("Failed to write updated FAISS index/metadata: %s", write_exc)
                if os.path.exists(temp_faiss_path):
                    try:
                        os.remove(temp_faiss_path)
                    except OSError:
                        pass
                if os.path.exists(temp_meta_path):
                    try:
                        os.remove(temp_meta_path)
                    except OSError:
                        pass
                raise

    # 5. Flush Search Cache and Invalidate In-Memory Text Index
    search_cache.invalidate()
    try:
        from app.retrieval.text_engine import text_engine
        text_engine.invalidate()
    except Exception as exc:
        log.warning("Could not invalidate text_engine cache: %s", exc)

    return {
        "status": "success",
        "paper_id": paper.id,
        "title": paper.title,
        "page_count": paper.page_count,
        "message": f"Successfully uploaded and indexed '{paper.title}' ({page_count} pages).",
    }

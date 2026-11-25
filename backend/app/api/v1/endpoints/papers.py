"""
Research Papers & Ingestion Endpoints
====================================
Handles PDF document upload, catalog browsing, manual re-indexing,
and direct semantic search.
"""

import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import List, Optional

MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB limit

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Query
from sqlalchemy.orm import Session

from app.agents.orchestrator import _get_retrieval_engine
from app.core.cache import search_cache
from app.core.config import settings
from app.core.database import get_db
from app.core.logger import get_logger
from app.models.db_models import PaperPage, ResearchPaper
from app.models.domain import PaperResponse, SearchQuery
from app.retrieval.colpali_engine import colpali_engine
from app.retrieval.text_engine import text_engine
from app.services.ingestion_service import process_and_ingest_pdf

router = APIRouter()
log = get_logger(__name__)


@router.get("/papers", response_model=List[PaperResponse], summary="List Research Papers")
def get_papers(
    department: Optional[str] = Query(None, description="Filter papers by clinical department"),
    db: Session = Depends(get_db),
):
    """
    Retrieves all peer-reviewed research papers and indexed documents in the
    knowledge base along with page 1 preview image URLs and department classification.
    """
    query = db.query(ResearchPaper)
    if department and department.strip() and department.strip().lower() != "all":
        query = query.filter(ResearchPaper.department.ilike(department.strip()))

    papers = query.all()
    results = []
    for p in papers:
        page1 = (
            db.query(PaperPage)
            .filter(PaperPage.paper_id == p.id, PaperPage.page_number == 1)
            .first()
        )
        img_url = None
        if page1 and page1.image_path and os.path.exists(page1.image_path):
            img_url = f"/rendered_pages/{Path(page1.image_path).name}"
        else:
            rendered_dir = settings.RENDERED_PAGES_DIR
            if os.path.isdir(rendered_dir):
                for f in os.listdir(rendered_dir):
                    if f.endswith(".png") and (f"paper_{p.id}_" in f or Path(p.file_path).stem in f):
                        img_url = f"/rendered_pages/{f}"
                        break

        paper_dict = {
            "id": p.id,
            "title": p.title,
            "authors": p.authors,
            "journal": p.journal,
            "publication_year": p.publication_year,
            "doi": p.doi,
            "file_path": p.file_path,
            "page_count": p.page_count,
            "indexed": p.indexed,
            "created_at": p.created_at,
            "image_url": img_url,
            "department": p.department or "General",
            "access_roles": p.access_roles or "clinical,research",
        }
        results.append(paper_dict)
    return results


@router.post("/papers/upload", summary="Upload and Ingest Research Paper (PDF)")
async def upload_and_ingest_paper(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Accepts a PDF file, validates signature & size, sanitizes destination path against
    directory traversal, renders pages, embeds text via Gemini, and indexes in DB and FAISS.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename cannot be empty.")

    # 1. Guard against directory traversal attacks
    if ".." in file.filename or "/" in file.filename or "\\" in file.filename:
        raise HTTPException(status_code=400, detail="Path traversal characters not allowed in filename.")

    # Sanitize filename and enforce .pdf extension
    raw_name = Path(file.filename).name
    safe_name = re.sub(r"[^\w\-_\. ]", "_", raw_name).strip()
    if not safe_name.lower().endswith(".pdf") or safe_name.startswith("."):
        raise HTTPException(status_code=400, detail="Only standard PDF files (.pdf) are supported.")

    papers_dir = Path(settings.PAPERS_DIR).resolve()
    papers_dir.mkdir(parents=True, exist_ok=True)

    dest_path = (papers_dir / safe_name).resolve()
    # Guard against directory traversal escaping papers_dir
    try:
        dest_path.relative_to(papers_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid target filename.")

    # 2. Read and validate payload size & magic bytes
    try:
        contents = await file.read()
    except Exception as exc:
        log.error("Failed to read uploaded file: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to read uploaded file.")

    if len(contents) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds 50MB limit ({len(contents)} bytes).")

    if len(contents) < 10:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # Validate PDF signature in initial byte header
    if not (contents.startswith(b"%PDF-") or b"%PDF-" in contents[:1024]):
        raise HTTPException(status_code=400, detail="Invalid file: Missing '%PDF-' binary signature.")

    try:
        with open(dest_path, "wb") as f:
            f.write(contents)
    except Exception as exc:
        log.error("Failed to save uploaded file %s: %s", safe_name, exc)
        raise HTTPException(status_code=500, detail=f"Failed to save file: {exc}")

    result = process_and_ingest_pdf(pdf_path=str(dest_path), db=db)
    return result


@router.post("/ingest", summary="Trigger Background Offline Ingestion")
async def trigger_ingestion():
    """
    Triggers the paper ingestion pipeline script in a background thread.
    Automatically invalidates in-memory and search caches.
    """
    log.info("Manual ingestion triggered via API.")

    def _run_ingest():
        project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
        script = "scripts/ingest_papers_vlm.py"
        if not (project_root / script).exists():
            script = "scripts/ingest_papers_lightweight.py"
        if not (project_root / script).exists():
            script = "scripts/ingest_papers.py"

        result = subprocess.run(
            [sys.executable, script],
            capture_output=True,
            text=True,
            cwd=str(project_root),
        )
        search_cache.invalidate()
        try:
            text_engine.invalidate()
        except Exception as exc:
            log.warning("Could not invalidate text_engine cache: %s", exc)

        if result.returncode != 0:
            log.error("Ingestion failed: %s", result.stderr[:500])
        else:
            log.info("Ingestion completed successfully.")

    thread = threading.Thread(target=_run_ingest, daemon=True)
    thread.start()

    return {
        "status": "started",
        "message": "Ingestion running in background. Check server logs for progress.",
        "cache_will_flush": True,
    }


@router.post("/search", summary="Direct Visual Document Search")
@router.post("/papers/search", summary="Direct Visual Document Search (alias)", include_in_schema=False)
def search_research_papers(payload: SearchQuery, db: Session = Depends(get_db)):
    """
    Executes visual/hybrid document search.
    Returns matching pages with paper metadata, scores, and thumbnail URLs.
    """
    engine = _get_retrieval_engine()
    enriched = engine.search_enriched(
        queries=[payload.query], top_k=payload.top_k, db=db
    )
    return {
        "query": payload.query,
        "total_results": len(enriched),
        "results": enriched,
    }

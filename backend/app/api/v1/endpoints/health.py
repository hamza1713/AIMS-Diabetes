"""
System Health & Diagnostics Endpoints
=====================================
Provides detailed subsystem telemetry for monitoring dashboards and health probes.
"""

import os
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.logger import get_logger
from app.core.cache import search_cache
from app.models.db_models import ResearchPaper, ChatMessage
from app.retrieval.text_engine import text_engine
from app.agents.ollama_client import is_ollama_available

router = APIRouter()
log = get_logger(__name__)


@router.get("/health", summary="System Health Status")
def health_check(db: Session = Depends(get_db)):
    """
    Detailed health check — reports status of every subsystem component:
    database connectivity, vector indices, page caches, active LLM engines.
    """
    # 1. DB connectivity
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
        paper_count = db.query(ResearchPaper).count()
        chat_count = db.query(ChatMessage).count()
    except Exception as exc:
        db_ok = False
        paper_count = chat_count = -1
        log.error("Health check DB error: %s", exc)

    # 2. ColPali index
    index_dir = os.path.join(
        settings.INDEX_STORE_PATH, ".byaldi", "diabetes_papers_index"
    )
    index_exists = os.path.isdir(index_dir)

    # 3. Rendered pages
    rendered_dir = settings.RENDERED_PAGES_DIR
    rendered_count = len(
        [f for f in os.listdir(rendered_dir) if f.endswith(".png")]
    ) if os.path.isdir(rendered_dir) else 0

    # 4. Gemini API key
    gemini_ok = bool(settings.GEMINI_API_KEY)

    # 5. Ollama Status
    ollama_ok = is_ollama_available()

    llm_ok = ollama_ok if settings.LLM_PROVIDER == "ollama" else gemini_ok
    overall = "healthy" if (db_ok and llm_ok) else "degraded"

    return {
        "status": overall,
        "version": "2.0.0",
        "components": {
            "database": {
                "ok": db_ok,
                "papers_indexed": paper_count,
                "chat_messages": chat_count,
            },
            "colpali_index": {
                "ok": index_exists,
                "index_path": index_dir,
                "note": "Run scripts/ingest_papers.py to build (requires GPU)" if not index_exists else "Ready",
            },
            "text_index": {
                "ok": text_engine.is_available,
                "note": (
                    "Run: python scripts/ingest_papers_lightweight.py"
                    if not text_engine.is_available
                    else "Ready — CPU-friendly FAISS index"
                ),
            },
            "active_engine": (
                "TextEngine (FAISS + Gemini Embeddings — CPU-friendly)"
                if text_engine.is_available
                else "ColPaliEngine (PaliGemma 2 — requires GPU)"
                if index_exists
                else "None — run ingestion script first"
            ),
            "rendered_pages": {
                "ok": rendered_count > 0,
                "count": rendered_count,
            },
            "llm_provider": {
                "configured": settings.LLM_PROVIDER,
                "ollama": {
                    "ok": ollama_ok,
                    "model": settings.OLLAMA_MODEL,
                    "base_url": settings.OLLAMA_BASE_URL,
                },
                "gemini": {
                    "ok": gemini_ok,
                },
            },
            "search_cache": search_cache.stats(),
        },
    }

"""
ColPali Vision-Language Retrieval Engine
=========================================
Wraps the Byaldi / PaliGemma 2 late-interaction multi-vector index.

Key design decisions:
- `search()` — raw ColPali results (fast, no DB); used internally.
- `search_enriched()` — joins ColPali results with DB metadata + image paths;
  returned to the orchestrator and serialised into the API response.
- Diversity-aware deduplication: when merging results from multiple sub-queries,
  we prefer spreading results across different documents rather than N pages from
  the same document, giving the LLM broader evidence coverage.
- All public methods are safe to call before the model is initialised — they
  degrade gracefully to empty lists.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings


class ColPaliEngine:
    """
    ColPali Vision-Language Model Late-Interaction Multi-Vector Retrieval Engine.
    Powered by PaliGemma 2 / ColPali (vidore/colpali-v1.2) for zero-OCR document retrieval.
    """

    def __init__(self, index_name: str = "diabetes_papers_index") -> None:
        self.index_name = index_name
        self.index_path = settings.INDEX_STORE_PATH
        self.model_name = settings.COLPALI_MODEL_NAME
        self.model = None
        self._is_initialized = False

    # ── Initialization ──────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Lazy-initialise the Byaldi / ColPali model backend."""
        if self._is_initialized:
            return

        try:
            from byaldi import RAGMultiModalModel  # type: ignore

            print(f"[ColPali] Loading model {self.model_name}...")
            index_dir = os.path.join(self.index_path, ".byaldi", self.index_name)
            if os.path.exists(index_dir):
                print(f"[ColPali] Loading existing index from {index_dir}...")
                self.model = RAGMultiModalModel.from_index(
                    self.index_name, index_root=self.index_path
                )
            else:
                print(f"[ColPali] No index found — loading pretrained base model...")
                self.model = RAGMultiModalModel.from_pretrained(self.model_name)

            self._is_initialized = True
            print("[ColPali] Engine initialised successfully.")

        except Exception as exc:
            print(
                f"[ColPali] ⚠️  Failed to initialise Byaldi model ({exc}). "
                "Running in dev-fallback mode — search will return empty results."
            )
            self.model = None
            self._is_initialized = False

    # ── Indexing ────────────────────────────────────────────────────────────

    def index_documents(self, pdf_dir: str) -> None:
        """
        Indexes all PDF files in *pdf_dir* using ColPali patch embeddings.
        Converts each page to a set of visual patch vectors via PaliGemma 2.
        """
        self.initialize()
        pdf_paths = [f for f in os.listdir(pdf_dir) if f.endswith(".pdf")]

        if not pdf_paths:
            print(f"[ColPali] No PDF files found in {pdf_dir}.")
            return

        print(f"[ColPali] Indexing {len(pdf_paths)} research PDFs...")
        if self.model:
            try:
                self.model.index(
                    input_path=pdf_dir,
                    index_name=self.index_name,
                    index_root=self.index_path,
                    store_collection_with_index=True,
                    overwrite=True,
                )
                print("[ColPali] ✅ Ingestion completed successfully.")
            except Exception as exc:
                print(f"[ColPali] Indexing error: {exc}")
        else:
            print("[ColPali] [Dev Mode] Simulated indexing completed (no model loaded).")

    # ── Raw Search ──────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 8) -> List[Dict[str, Any]]:
        """
        Performs late-interaction (MaxSim) multi-vector search across indexed pages.

        Returns a list of dicts:
            {"doc_id": int, "page_number": int, "score": float, "metadata": dict}

        Returns an empty list if the model is not loaded (graceful degradation).
        """
        self.initialize()

        if not self.model:
            print(f"[ColPali Dev] No model — skipping search for: '{query}'")
            return []

        try:
            raw = self.model.search(query=query, k=top_k)
            return [
                {
                    "doc_id": getattr(r, "doc_id", 0),
                    "page_number": getattr(r, "page_num", 1),
                    "score": getattr(r, "score", 0.0),
                    "metadata": getattr(r, "metadata", {}),
                }
                for r in raw
            ]
        except Exception as exc:
            print(f"[ColPali] Search error: {exc}")
            return []

    # ── Enriched Search (with DB metadata + image paths) ───────────────────

    def search_enriched(
        self,
        queries: List[str],
        top_k: int = 5,
        db=None,
    ) -> List[Dict[str, Any]]:
        """
        Runs ColPali search for each query in *queries*, then:
          1. Deduplicates results keeping the highest score per (doc_id, page) pair.
          2. Applies diversity-aware selection: no more than 2 pages per document
             in the final top-k, ensuring the LLM sees multiple papers.
          3. Joins with DB metadata (title, authors, journal, image path).

        Args:
            queries:  One or more query strings (original + any expansions).
            top_k:    Maximum number of unique pages to return.
            db:       SQLAlchemy Session — if None, metadata fields will be None.

        Returns:
            List of enriched result dicts, sorted descending by score.
        """
        # ── Step 1: Collect all raw results across queries ─────────────────
        merged: Dict[Tuple[int, int], Dict[str, Any]] = {}
        for q in queries:
            for res in self.search(query=q, top_k=top_k + 3):  # fetch extra for dedup
                key = (res["doc_id"], res["page_number"])
                if key not in merged or res["score"] > merged[key]["score"]:
                    merged[key] = res

        if not merged:
            return []

        # ── Step 2: Diversity-aware selection ──────────────────────────────
        # Sort all candidates by score (best first), then greedily pick top-k
        # while limiting to max_pages_per_doc per unique document.
        # Compute dynamic diversity cap based on top_k. Allows more pages for
        # targeted single-paper queries while maintaining multi-paper diversity.
        max_pages_per_doc = max(3, top_k // 2)
        doc_page_count: Dict[int, int] = {}
        selected: List[Dict[str, Any]] = []

        for res in sorted(merged.values(), key=lambda x: x["score"], reverse=True):
            doc_id = res["doc_id"]
            count = doc_page_count.get(doc_id, 0)
            if count < max_pages_per_doc:
                selected.append(res)
                doc_page_count[doc_id] = count + 1
            if len(selected) >= top_k:
                break

        if not selected:
            return []

        # ── Step 3: Enrich with DB metadata ───────────────────────────────
        if db is None:
            # Return partial results without metadata
            return [
                {**r, "title": None, "authors": None, "journal": None,
                 "publication_year": None, "image_path": None, "image_url": None}
                for r in selected
            ]

        # Import here to avoid circular imports at module load time
        from app.models.db_models import ResearchPaper, PaperPage  # noqa: PLC0415
        from sqlalchemy import or_  # noqa: PLC0415

        # Query Byaldi doc_id -> file path mapping
        doc_id_to_file_path = {}
        if self.model:
            try:
                doc_id_to_file_path = self.model.get_doc_ids_to_file_names()
            except Exception as e:
                print(f"[ColPali] Failed to retrieve doc_id map from Byaldi model: {e}")

        # Batch query ResearchPaper to eliminate N+1 queries
        candidate_ids = [
            int(res["doc_id"])
            for res in selected
            if res.get("doc_id") is not None and (
                isinstance(res["doc_id"], int) or (isinstance(res["doc_id"], str) and str(res["doc_id"]).isdigit())
            )
        ]
        candidate_files = [doc_id_to_file_path[bid] for bid in candidate_ids if bid in doc_id_to_file_path]

        conditions = []
        if candidate_ids:
            conditions.append(ResearchPaper.id.in_(candidate_ids))
        if candidate_files:
            conditions.append(ResearchPaper.file_path.in_(candidate_files))
            for fp in candidate_files:
                if fp:
                    conditions.append(ResearchPaper.file_path.like(f"%{Path(fp).name}"))

        papers = []
        try:
            if conditions:
                papers = db.query(ResearchPaper).filter(or_(*conditions)).all()
        except Exception as db_exc:
            print(f"[ColPali] ResearchPaper batch lookup failed: {db_exc}")

        paper_by_id: Dict[int, ResearchPaper] = {p.id: p for p in papers}
        paper_by_path: Dict[str, ResearchPaper] = {p.file_path: p for p in papers if p.file_path}
        paper_by_name: Dict[str, ResearchPaper] = {Path(p.file_path).name: p for p in papers if p.file_path}

        resolved_paper_map: Dict[int, Optional[ResearchPaper]] = {}
        resolved_doc_map: Dict[int, Optional[int]] = {}
        for res in selected:
            byaldi_doc_id = res["doc_id"]
            paper = None
            if byaldi_doc_id is not None:
                file_path = doc_id_to_file_path.get(byaldi_doc_id)
                if file_path:
                    paper = paper_by_path.get(file_path) or paper_by_name.get(Path(file_path).name)
                if not paper and (isinstance(byaldi_doc_id, int) or (isinstance(byaldi_doc_id, str) and str(byaldi_doc_id).isdigit())):
                    paper = paper_by_id.get(int(byaldi_doc_id))
            doc_id = paper.id if paper else byaldi_doc_id
            resolved_paper_map[byaldi_doc_id] = paper
            resolved_doc_map[byaldi_doc_id] = doc_id

        all_doc_ids = list({
            int(doc_id)
            for doc_id in resolved_doc_map.values()
            if doc_id is not None and (
                isinstance(doc_id, int) or (isinstance(doc_id, str) and str(doc_id).isdigit())
            )
        })
        pages = []
        try:
            if all_doc_ids:
                pages = db.query(PaperPage).filter(PaperPage.paper_id.in_(all_doc_ids)).all()
        except Exception as db_exc:
            print(f"[ColPali] PaperPage batch lookup failed: {db_exc}")

        pages_by_doc_page: Dict[Tuple[int, int], PaperPage] = {(p.paper_id, p.page_number): p for p in pages}

        # Cache directory listing once to avoid repeated disk I/O in the loop
        rendered_dir = settings.RENDERED_PAGES_DIR
        try:
            rendered_files = os.listdir(rendered_dir) if os.path.isdir(rendered_dir) else []
        except Exception:
            rendered_files = []

        enriched: List[Dict[str, Any]] = []
        for res in selected:
            byaldi_doc_id = res["doc_id"]
            page_num = res["page_number"]
            doc_id = resolved_doc_map.get(byaldi_doc_id, byaldi_doc_id)
            paper = resolved_paper_map.get(byaldi_doc_id)

            lookup_doc_id = int(doc_id) if (doc_id is not None and (isinstance(doc_id, int) or (isinstance(doc_id, str) and str(doc_id).isdigit()))) else doc_id
            page: Optional[PaperPage] = pages_by_doc_page.get((lookup_doc_id, page_num)) if lookup_doc_id is not None else None

            # Build image full path & URL for frontend thumbnail and modal
            img_full_path: Optional[str] = None
            image_url: Optional[str] = None
            if page and page.image_path and os.path.exists(page.image_path):
                img_full_path = page.image_path
                image_url = f"/rendered_pages/{Path(page.image_path).name}"
            elif rendered_files and doc_id is not None:
                paper_stem = Path(paper.file_path).stem if (paper and paper.file_path) else None
                for filename in rendered_files:
                    if filename.endswith(f"_page_{page_num}.png"):
                        if (
                            filename.startswith(f"paper_{doc_id}_")
                            or (paper_stem and paper_stem in filename)
                            or filename == f"paper_{doc_id}_page_{page_num}.png"
                        ):
                            img_full_path = os.path.join(rendered_dir, filename)
                            image_url = f"/rendered_pages/{filename}"
                            break

            enriched.append({
                "doc_id": doc_id,
                "page_number": page_num,
                "score": res["score"],
                "title": paper.title if paper else f"Research Paper (doc={doc_id})",
                "authors": paper.authors if paper else "Unknown Authors",
                "journal": paper.journal if paper else "Unknown Journal",
                "publication_year": paper.publication_year if paper else None,
                # file_path lets the orchestrator live-read page text via PyMuPDF fallback
                "file_path": paper.file_path if paper else None,
                "image_path": img_full_path,                      # absolute FS path
                "image_url": image_url,                            # URL for frontend
            })

        return enriched


# ── Module-level singleton ──────────────────────────────────────────────────
colpali_engine = ColPaliEngine()

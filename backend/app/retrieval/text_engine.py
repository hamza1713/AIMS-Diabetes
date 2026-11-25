"""
Lightweight Text Engine — FAISS + Gemini Embeddings
=====================================================
CPU-only alternative to ColPali for machines without a GPU.

Why this works better on your hardware (i5-5300U, 8GB RAM, no GPU):
  - No local model to download or load (ColPali downloads 5.85GB PaliGemma 2)
  - Embeddings generated via Gemini API (cloud, ~0.3s per call)
  - FAISS index uses only ~10MB RAM for 1000 pages
  - Retrieval is milliseconds (CPU vector similarity on compressed index)
  - Quality: Gemini text-embedding-004 is state-of-the-art (768-dim dense embeddings)

Performance comparison on i5-5300U:
  ColPali CPU ingestion : 60-120s per page × 1000 pages = 17-33 HOURS
  This engine ingestion : ~0.3s per page × 1000 pages  = ~5 MINUTES

Implements exactly the same search_enriched() interface as ColPaliEngine
so the orchestrator, API endpoints, and frontend require ZERO changes.

Trade-off: loses visual/chart understanding (tables embedded as extracted text,
which is still very high quality for academic PDF research papers).
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.config import settings
from app.core.logger import get_logger

log = get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────
# gemini-embedding-001: Google's current embedding model (released 2025)
# Successor to text-embedding-004 (retired Jan 14 2026)
# Uses the new google-genai SDK (v1 API) not google-generativeai (v1beta)
# Dimension: 3072 (higher than text-embedding-004's 768)
_EMBEDDING_MODEL = "gemini-embedding-001"
_EMBEDDING_DIM = 3072
_INDEX_DIR = os.path.join(settings.INDEX_STORE_PATH, "text_index")
_FAISS_PATH = os.path.join(_INDEX_DIR, "faiss.index")
_META_PATH = os.path.join(_INDEX_DIR, "metadata.json")
# _MAX_PAGES_PER_DOC constant removed; diversity cap is now computed dynamically.

# ── Gemini client singleton ────────────────────────────────────────────────
# Instantiated once at module load to avoid per-call construction overhead.
# This also reuses the underlying HTTP session across embedding calls.
_gemini_client = None


def _get_gemini_client():
    """Returns the shared Gemini client, creating it lazily on first use."""
    global _gemini_client
    if _gemini_client is None:
        from google import genai as google_genai  # noqa: PLC0415
        _gemini_client = google_genai.Client(api_key=settings.GEMINI_API_KEY)
    return _gemini_client


# ── Gemini embedding helper ────────────────────────────────────────────────

def _embed(text: str, task_type: str = "RETRIEVAL_QUERY") -> Optional[np.ndarray]:
    """
    Calls Gemini gemini-embedding-001 via the new google-genai SDK (v1 API).
    Returns a normalised 3072-dim numpy vector.
    Includes exponential retry backoff on transient/quota errors.
    """
    import time
    max_retries = 3
    base_delay = 1.0
    
    for attempt in range(max_retries):
        try:
            from google.genai import types as genai_types  # noqa: PLC0415

            # Use the module-level singleton client (avoids per-call construction overhead)
            client = _get_gemini_client()
            result = client.models.embed_content(
                model=_EMBEDDING_MODEL,
                contents=text,
                # Ensure task_type is uppercase — lowercase silently produces generic embeddings
                config=genai_types.EmbedContentConfig(task_type=task_type.upper()),
            )
            vec = np.array(result.embeddings[0].values, dtype=np.float32)
            # L2-normalise so cosine similarity = inner product
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            return vec
        except Exception as exc:
            exc_msg = str(exc).lower()
            is_transient = any(tag in exc_msg for tag in ["429", "quota", "resource exhausted", "503", "service unavailable", "overloaded", "disconnected"])
            if is_transient and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                log.warning("Transient embedding error on attempt %d: %s. Retrying in %.1fs...", attempt + 1, exc, delay)
                time.sleep(delay)
            else:
                log.error("Embedding API error: %s", exc)
                return None
    return None


def _embed_batch(texts: List[str], task_type: str = "RETRIEVAL_QUERY") -> List[Optional[np.ndarray]]:
    """
    Embeds a list of texts in a single batch API call via gemini-embedding-001.
    Returns a list of normalised 3072-dim numpy vectors.
    """
    if not texts:
        return []
        
    import time
    max_retries = 3
    base_delay = 1.0
    
    for attempt in range(max_retries):
        try:
            from google.genai import types as genai_types  # noqa: PLC0415
            client = _get_gemini_client()
            result = client.models.embed_content(
                model=_EMBEDDING_MODEL,
                contents=texts,
                config=genai_types.EmbedContentConfig(task_type=task_type.upper()),
            )
            
            vectors = []
            for emb in result.embeddings:
                vec = np.array(emb.values, dtype=np.float32)
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm
                vectors.append(vec)
            return vectors
        except Exception as exc:
            exc_msg = str(exc).lower()
            is_transient = any(tag in exc_msg for tag in ["429", "quota", "resource exhausted", "503", "service unavailable", "overloaded", "disconnected"])
            if is_transient and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                log.warning("Transient batch embedding error on attempt %d: %s. Retrying in %.1fs...", attempt + 1, exc, delay)
                time.sleep(delay)
            else:
                log.error("Batch embedding API error: %s", exc)
                # Fallback to individual embeddings on failure
                log.info("Batch embedding failed. Falling back to individual queries.")
                vectors = []
                for t in texts:
                    vectors.append(_embed(t, task_type))
                return vectors
    return [None] * len(texts)


class BM25:
    """
    Lightweight, zero-dependency BM25 implementation for lexical keyword search.
    Complements dense embeddings to provide robust hybrid retrieval (RRF).
    """
    def __init__(self, corpus: List[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus_size = len(corpus)
        self.avgdl = 0.0
        self.doc_lengths = []
        self.doc_term_freqs = []
        self.nd = {}  # number of documents containing term t

        total_len = 0
        for doc in corpus:
            tokens = self._tokenize(doc)
            self.doc_lengths.append(len(tokens))
            total_len += len(tokens)
            
            frequencies = {}
            for token in tokens:
                frequencies[token] = frequencies.get(token, 0) + 1
            self.doc_term_freqs.append(frequencies)
            
            for token in frequencies.keys():
                self.nd[token] = self.nd.get(token, 0) + 1
                
        self.avgdl = total_len / self.corpus_size if self.corpus_size > 0 else 0.0

        # Build inverted index: token -> list of (doc_idx, term_frequency)
        self.inverted_index: Dict[str, List[Tuple[int, int]]] = {}
        for doc_idx, frequencies in enumerate(self.doc_term_freqs):
            for token, freq in frequencies.items():
                if token not in self.inverted_index:
                    self.inverted_index[token] = []
                self.inverted_index[token].append((doc_idx, freq))

    def _tokenize(self, text: str) -> List[str]:
        if not text or not isinstance(text, str):
            return []
        # Lowercase and split into words
        words = re.findall(r'\w+', text.lower())
        
        # Stopwords to filter out
        stopwords = {
            "the", "a", "an", "and", "or", "but", "if", "then", "else", "when", 
            "at", "by", "from", "for", "with", "about", "against", "between", 
            "into", "through", "during", "before", "after", "above", "below", 
            "to", "of", "in", "on", "that", "this", "these", "those", "is", "are", 
            "was", "were", "be", "been", "being", "have", "has", "had", "having", 
            "do", "does", "did", "doing", "can", "could", "should", "would", "will"
        }
        tokens = [w for w in words if w not in stopwords and len(w) > 1]
        
        # Simple rule-based suffix stemming for medical domain
        stemmed = []
        for t in tokens:
            if t.endswith("ies") and not t.endswith("aies"):
                t = t[:-3] + "y"
            elif t.endswith("es") and t[:-2] in ["diabet", "glucos", "dos"]:
                t = t[:-1]
            elif t.endswith("s") and not t.endswith("ss") and not t.endswith("is"):
                t = t[:-1]
            elif t.endswith("ing"):
                t = t[:-3]
            elif t.endswith("ed"):
                t = t[:-2]
            elif t.endswith("al") and len(t) > 4:
                t = t[:-2]
            stemmed.append(t)
        return stemmed

    def get_score(self, query: str, index: int) -> float:
        """Returns the BM25 relevance score of document at `index` for `query`."""
        if self.corpus_size == 0 or self.avgdl == 0 or index < 0 or index >= self.corpus_size:
            return 0.0

        score = 0.0
        doc_len = self.doc_lengths[index]
        frequencies = self.doc_term_freqs[index]
        query_tokens = self._tokenize(query)

        for token in query_tokens:
            if token not in self.nd:
                continue
            
            # IDF with standard BM25 smoothing
            n_t = self.nd[token]
            idf = math.log((self.corpus_size - n_t + 0.5) / (n_t + 0.5) + 1.0)
            
            # Document term frequency
            tf = frequencies.get(token, 0)
            
            # Score formula
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / self.avgdl))
            
            score += idf * (numerator / denominator)
            
        return score

    def search(
        self,
        query: str,
        top_k: int = 8,
        allowed_indices: Optional[set] = None,
    ) -> List[Tuple[int, float]]:
        """Returns top_k document indices and their BM25 scores using inverted index candidate scoring."""
        if self.corpus_size == 0 or self.avgdl == 0:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        candidate_scores: Dict[int, float] = {}
        for token in query_tokens:
            if token not in self.inverted_index:
                continue
            n_t = self.nd.get(token, 0)
            if n_t == 0:
                continue
            idf = math.log((self.corpus_size - n_t + 0.5) / (n_t + 0.5) + 1.0)
            for doc_idx, tf in self.inverted_index[token]:
                if allowed_indices is not None and doc_idx not in allowed_indices:
                    continue
                doc_len = self.doc_lengths[doc_idx]
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / self.avgdl))
                candidate_scores[doc_idx] = candidate_scores.get(doc_idx, 0.0) + idf * (numerator / denominator)

        scores = [(idx, score) for idx, score in candidate_scores.items() if score > 0.0]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


class TextEngine:
    """
    FAISS + Gemini text embedding retrieval engine.

    Drop-in replacement for ColPaliEngine on CPU-only machines.
    Implements the same search_enriched() interface so no other code changes.
    """

    def __init__(self) -> None:
        self._index = None       # faiss.IndexFlatIP
        self._metadata: List[Dict] = []
        self._loaded = False
        self._bm25: Optional[BM25] = None
        self._last_mtime_faiss: float = 0.0
        self._last_mtime_meta: float = 0.0

    def invalidate(self) -> None:
        """Forces reloading of the FAISS index, metadata, and BM25 on next search."""
        self._loaded = False
        self._index = None
        self._metadata = []
        self._bm25 = None
        self._last_mtime_faiss = 0.0
        self._last_mtime_meta = 0.0
        log.info("TextEngine in-memory index invalidated; will reload on next query.")

    # ── Index loading ──────────────────────────────────────────────────────

    def _load(self) -> bool:
        """Load FAISS index + metadata from disk. Returns True if successful."""
        if not os.path.exists(_FAISS_PATH) or not os.path.exists(_META_PATH):
            log.warning(
                "Text index not found at %s. "
                "Run scripts/ingest_papers_lightweight.py first.",
                _INDEX_DIR,
            )
            return False

        try:
            current_faiss_mtime = os.path.getmtime(_FAISS_PATH)
            current_meta_mtime = os.path.getmtime(_META_PATH)
        except OSError:
            current_faiss_mtime = 0.0
            current_meta_mtime = 0.0

        if self._loaded and current_faiss_mtime == self._last_mtime_faiss and current_meta_mtime == self._last_mtime_meta:
            return True

        try:
            import faiss  # type: ignore
            self._index = faiss.read_index(_FAISS_PATH)
            with open(_META_PATH, "r", encoding="utf-8") as f:
                self._metadata = json.load(f)
            self._loaded = True
            self._last_mtime_faiss = current_faiss_mtime
            self._last_mtime_meta = current_meta_mtime
            
            # Initialize BM25 search corpus from page content AND paper title for robust lexical matching
            corpus = [
                f"{meta.get('title', '')} {meta.get('text_content', meta.get('text_snippet', ''))}"
                for meta in self._metadata
            ]
            self._bm25 = BM25(corpus)
            
            log.info(
                "Text index loaded: %d page embeddings from %s",
                self._index.ntotal,
                _INDEX_DIR,
            )
            return True
        except Exception as exc:
            log.error("Failed to load text index: %s", exc)
            return False

    @property
    def is_available(self) -> bool:
        """True if the FAISS index exists on disk."""
        return os.path.exists(_FAISS_PATH) and os.path.exists(_META_PATH)

    # ── Search ─────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 8,
        allowed_departments: Optional[List[str]] = None,
        allowed_roles: Optional[List[str]] = None,
        query_vec: Optional[np.ndarray] = None
    ) -> List[Dict[str, Any]]:
        """
        Embed the query (if not pre-computed) and run FAISS inner-product search.
        Returns list of {doc_id, page_number, score, text_snippet, text_content}.
        """
        if not self._load():
            return []

        if query_vec is None:
            query_vec = _embed(query, task_type="RETRIEVAL_QUERY")
            if query_vec is None:
                return []

        # Build set of allowed indices based on metadata attributes
        allowed_ids = []
        allowed_set = None
        
        if allowed_departments is not None or allowed_roles is not None:
            for idx, meta in enumerate(self._metadata):
                dept_ok = True
                role_ok = True
                
                if allowed_departments is not None:
                    dept_ok = meta.get("department", "General") in allowed_departments
                    
                if allowed_roles is not None:
                    meta_roles = meta.get("access_roles", "clinical,research").split(",")
                    role_ok = any(r in allowed_roles for r in meta_roles)
                    
                if dept_ok and role_ok:
                    allowed_ids.append(idx)
            allowed_set = set(allowed_ids)
            if not allowed_set:
                return []

        # FAISS expects (n_queries, d) shape
        query_mat = query_vec.reshape(1, -1)
        
        scores, indices = None, None
        use_fallback = True
        
        # Try native FAISS selector-based search first
        if allowed_set is not None:
            try:
                import faiss  # type: ignore
                import numpy as np
                id_arr = np.array(list(allowed_set), dtype=np.int64)
                selector = faiss.IDSelectorArray(id_arr)
                params = faiss.SearchParameters()
                params.sel = selector
                scores, indices = self._index.search(query_mat, top_k, params=params)
                use_fallback = False
            except Exception as e:
                log.debug("Native FAISS SearchParameters failed (%s) - using fallback", e)
                use_fallback = True
                
        if use_fallback or scores is None:
            # Search a larger count then filter programmatic
            search_k = min(max(top_k * 4, 50), len(self._metadata))
            if search_k <= 0:
                return []
            scores, indices = self._index.search(query_mat, search_k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._metadata):
                continue
            if allowed_set is not None and idx not in allowed_set:
                continue
            meta = self._metadata[idx]
            results.append({
                **meta,
                "score": float(score),
            })
            if len(results) >= top_k:
                break
        return results

    def search_enriched(
        self,
        queries: List[str],
        top_k: int = 5,
        db=None,
        allowed_departments: Optional[List[str]] = None,
        allowed_roles: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        # ── 1. Gather rankings from all channels (Dense and BM25 for each query) ──
        # We run dense vector similarity search and BM25 lexical keyword search
        # on all expanded queries. This gives us 2 * len(queries) total channels.
        if not self._load():
            return []

        inner_top_k = top_k + 5  # fetch extra candidates for RRF overlap
        
        # Build allowed index set for metadata filtering in BM25
        allowed_set = None
        if allowed_departments is not None or allowed_roles is not None:
            allowed_ids = []
            for idx, meta in enumerate(self._metadata):
                dept_ok = True
                role_ok = True
                
                if allowed_departments is not None:
                    dept_ok = meta.get("department", "General") in allowed_departments
                    
                if allowed_roles is not None:
                    meta_roles = meta.get("access_roles", "clinical,research").split(",")
                    role_ok = any(r in allowed_roles for r in meta_roles)
                    
                if dept_ok and role_ok:
                    allowed_ids.append(idx)
            allowed_set = set(allowed_ids)
            if not allowed_set:
                return []

        # Keep track of ranks across channels for each (doc_id, page_number)
        # (doc_id, page_number) -> list of ranks
        page_ranks: Dict[Tuple[int, int], List[int]] = {}
        
        # Build metadata quick-lookup map
        meta_map: Dict[Tuple[int, int], Dict] = {}
        for meta in self._metadata:
            key = (meta.get("doc_id", -1), meta.get("page_number", 0))
            meta_map[key] = meta

        # Batch embed all query variants in a single API call
        query_vectors = _embed_batch(queries, task_type="RETRIEVAL_QUERY")

        for idx, query in enumerate(queries):
            q_vec = query_vectors[idx] if idx < len(query_vectors) else None
            
            # Channel A: Dense Vector Search (supports metadata filtering)
            dense_raw = self.search(
                query,
                top_k=inner_top_k,
                allowed_departments=allowed_departments,
                allowed_roles=allowed_roles,
                query_vec=q_vec
            )
            for rank, r in enumerate(dense_raw):
                key = (r.get("doc_id", -1), r.get("page_number", 0))
                if key not in page_ranks:
                    page_ranks[key] = []
                page_ranks[key].append(rank)

            # Channel B: BM25 Lexical Keyword Search (filters candidates using allowed_set)
            if self._bm25:
                bm25_raw = self._bm25.search(query, top_k=inner_top_k, allowed_indices=allowed_set)
                for rank, (idx, _) in enumerate(bm25_raw):
                    if idx < 0 or idx >= len(self._metadata):
                        continue
                    meta = self._metadata[idx]
                    key = (meta.get("doc_id", -1), meta.get("page_number", 0))
                    if key not in page_ranks:
                        page_ranks[key] = []
                    page_ranks[key].append(rank)
                    
        if not page_ranks:
            return []

        # ── 2. Reciprocal Rank Fusion (RRF) ──────────────────────────────────
        # Fuses dense & lexical rankings. consensus matches rise to the top.
        # Constant k = 60 is standard in RAG retrieval.
        RRF_K = 60.0
        rrf_scores: Dict[Tuple[int, int], float] = {}
        for key, ranks in page_ranks.items():
            rrf_scores[key] = sum(1.0 / (RRF_K + r) for r in ranks)

        # ── 3. Sort by RRF score descending ──────────────────────────────────
        sorted_keys = sorted(rrf_scores.keys(), key=lambda k: rrf_scores[k], reverse=True)

        # ── 4. Diversity-aware selection ────────────────────────────────────
        # Compute dynamic diversity cap based on top_k. If a specific paper is
        # targeted or few documents match, allow more pages from that paper.
        unique_docs_in_results = len(set(k[0] for k in sorted_keys))
        if unique_docs_in_results <= 2:
            max_pages_per_doc = top_k
        else:
            max_pages_per_doc = max(4, int(top_k * 0.7))

        doc_counts: Dict[int, int] = {}
        diverse: List[Dict] = []
        for key in sorted_keys:
            meta = meta_map.get(key)
            if not meta:
                continue
            doc_id = key[0]
            count = doc_counts.get(doc_id, 0)
            if count < max_pages_per_doc:
                diverse.append({
                    **meta,
                    "score": rrf_scores[key],
                })
                doc_counts[doc_id] = count + 1
            if len(diverse) >= top_k:
                break

        # ── 5. Enrich with image paths & DB metadata ────────────────────────
        rendered_dir = settings.RENDERED_PAGES_DIR
        enriched: List[Dict] = []

        from app.models.db_models import PaperPage, ResearchPaper  # noqa: PLC0415

        # Batch lookup PaperPage and ResearchPaper records to eliminate N+1 queries
        doc_ids = list({
            int(r.get("doc_id"))
            for r in diverse
            if r.get("doc_id") is not None and (
                isinstance(r.get("doc_id"), int) or (isinstance(r.get("doc_id"), str) and str(r.get("doc_id")).isdigit())
            )
        })
        papers_by_id: Dict[int, ResearchPaper] = {}
        pages_by_doc_page: Dict[Tuple[int, int], PaperPage] = {}

        if db is not None and doc_ids:
            try:
                papers = db.query(ResearchPaper).filter(ResearchPaper.id.in_(doc_ids)).all()
                papers_by_id = {p.id: p for p in papers}

                pages = db.query(PaperPage).filter(PaperPage.paper_id.in_(doc_ids)).all()
                pages_by_doc_page = {(p.paper_id, p.page_number): p for p in pages}
            except Exception as db_exc:
                log.warning("Batch database metadata lookup failed in TextEngine: %s", db_exc)

        # Cache directory listing once to avoid repeated disk I/O in the loop
        try:
            rendered_files = os.listdir(rendered_dir) if os.path.isdir(rendered_dir) else []
        except Exception:
            rendered_files = []

        for r in diverse:
            raw_doc_id = r.get("doc_id")
            doc_id = int(raw_doc_id) if (
                raw_doc_id is not None and (
                    isinstance(raw_doc_id, int) or (isinstance(raw_doc_id, str) and str(raw_doc_id).isdigit())
                )
            ) else raw_doc_id
            page_num = r.get("page_number", 1)

            img_full_path = None
            img_url = None
            pdf_file_path = None  # absolute path to the source PDF for live text re-read

            # 1. In-memory lookup for page and paper
            page_rec = pages_by_doc_page.get((doc_id, page_num)) if doc_id is not None else None
            if page_rec and page_rec.image_path and os.path.exists(page_rec.image_path):
                img_full_path = page_rec.image_path
                img_url = f"/rendered_pages/{Path(page_rec.image_path).name}"

            paper_rec = papers_by_id.get(doc_id) if doc_id is not None else None
            if paper_rec and paper_rec.file_path:
                pdf_file_path = paper_rec.file_path
            elif r.get("file_path"):
                pdf_file_path = r.get("file_path")

            # 2. Fallback: match by file patterns in pre-listed rendered_pages directory
            if not img_url and rendered_files and doc_id is not None:
                paper_stem = Path(paper_rec.file_path).stem if (paper_rec and paper_rec.file_path) else None
                for filename in rendered_files:
                    if filename.endswith(f"_page_{page_num}.png"):
                        if (
                            filename.startswith(f"paper_{doc_id}_")
                            or (paper_stem and paper_stem in filename)
                            or filename == f"paper_{doc_id}_page_{page_num}.png"
                        ):
                            img_full_path = os.path.join(rendered_dir, filename)
                            img_url = f"/rendered_pages/{filename}"
                            break

            enriched.append({
                "doc_id": doc_id,
                "page_number": page_num,
                "score": r["score"],
                "title": paper_rec.title if (paper_rec and paper_rec.title) else r.get("title", "Unknown"),
                "authors": paper_rec.authors if (paper_rec and paper_rec.authors) else r.get("authors", "Unknown"),
                "journal": paper_rec.journal if (paper_rec and paper_rec.journal) else r.get("journal", "Unknown"),
                "publication_year": paper_rec.publication_year if (paper_rec and paper_rec.publication_year) else r.get("publication_year"),
                # text_content: full page text stored at ingestion (up to 4000 chars)
                "text_content": r.get("text_content") or "",
                # text_snippet: short preview (up to 2000 chars) for older index compat
                "text_snippet": r.get("text_snippet") or "",
                # file_path: source PDF path — lets orchestrator live-read via PyMuPDF
                "file_path": pdf_file_path,
                "image_url": img_url,
                "image_path": img_full_path,
            })

        log.info(
            "TextEngine.search_enriched: %d queries -> %d diverse results",
            len(queries),
            len(enriched),
        )
        return enriched


# ── Module-level singleton ──────────────────────────────────────────────────
text_engine = TextEngine()

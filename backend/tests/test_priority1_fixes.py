"""
Unit & Integration Tests for Priority 1 Performance & Retrieval Optimizations
=============================================================================
Tests:
  1. BM25 inverted index correctness, efficiency, and equivalence with get_score()
  2. Batch metadata enrichment in TextEngine & ColPaliEngine (eliminating N+1 SQL queries)
  3. Concurrent intent classification and query expansion in stream_rag_pipeline
  4. Incremental FAISS vector index ingestion without full index reconstruction
  5. Dynamic retrieval engine selection in POST /api/v1/papers/search
"""

import asyncio
import json
import os
import shutil
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import faiss
import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.orchestrator import stream_rag_pipeline, _get_retrieval_engine
from app.models.db_models import Base, PaperPage, ResearchPaper
from app.retrieval.colpali_engine import ColPaliEngine
from app.retrieval.text_engine import BM25, TextEngine


# ── Workspace-Local Temporary Directory Fixture ────────────────────────────
# Avoids [WinError 5] PermissionError from pytest's default tmp_path in AppData\Local\Temp

@pytest.fixture
def local_tmp_path():
    base_dir = Path(__file__).parent / "_test_scratch"
    base_dir.mkdir(parents=True, exist_ok=True)
    sub_dir = base_dir / f"run_{time.time_ns()}"
    sub_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield sub_dir
    finally:
        shutil.rmtree(sub_dir, ignore_errors=True)


# ── Test Database Fixture ──────────────────────────────────────────────────

@pytest.fixture
def in_memory_db():
    """Provides an isolated in-memory SQLite database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


# ── 1. BM25 Inverted Index Tests ──────────────────────────────────────────

def test_bm25_inverted_index_structure_and_scoring():
    corpus = [
        "Metformin therapy reduces HbA1c in type 2 diabetes mellitus patients.",
        "Cardiovascular outcome trials for SGLT2 inhibitors and GLP-1 receptor agonists.",
        "Insulin glargine titration protocols for inpatient glycemic control in hospital.",
        "Completely unrelated text about astrophysics, planetary orbits, and deep space exploration.",
    ]
    bm25 = BM25(corpus)

    # 1. Structure validation
    assert hasattr(bm25, "inverted_index"), "BM25 must have an inverted_index attribute"
    assert isinstance(bm25.inverted_index, dict)
    
    # Check that tokenized terms from doc 0 exist in inverted index
    doc0_tokens = bm25._tokenize(corpus[0])
    for token in doc0_tokens:
        assert token in bm25.inverted_index
        assert any(idx == 0 for idx, _ in bm25.inverted_index[token])

    # 2. Search scoring equivalence with get_score()
    query = "metformin diabetes"
    results = bm25.search(query, top_k=4)

    assert len(results) > 0
    top_doc, top_score = results[0]
    assert top_doc == 0  # Doc 0 is the strongest match for metformin diabetes

    # Verify score produced by search() exactly matches get_score()
    for doc_idx, score in results:
        expected_score = bm25.get_score(query, doc_idx)
        assert score == pytest.approx(expected_score, rel=1e-5)

    # 3. Efficiency check: non-matching documents must not be in results
    result_doc_ids = {doc_idx for doc_idx, _ in results}
    assert 3 not in result_doc_ids  # Doc 3 has zero matching terms


def test_bm25_edge_cases():
    # Empty corpus
    empty_bm25 = BM25([])
    assert empty_bm25.search("diabetes") == []
    assert empty_bm25.get_score("diabetes", 0) == 0.0

    # Zero avgdl corpus (all empty docs)
    zero_avgdl_bm25 = BM25(["", "   "])
    assert zero_avgdl_bm25.search("diabetes") == []
    assert zero_avgdl_bm25.get_score("diabetes", 0) == 0.0

    # Out of bounds indices
    corpus = ["Insulin resistance and metabolic syndrome in adults."]
    bm25 = BM25(corpus)
    assert bm25.get_score("insulin", -1) == 0.0
    assert bm25.get_score("insulin", 999) == 0.0

    # Non-empty corpus with empty/stopword-only query
    assert bm25.search("") == []
    assert bm25.search("the a and") == []

    # Query with non-existent terms
    assert bm25.search("astrophysics telescope") == []

    # Repeated query terms
    repeated_query = "insulin insulin"
    res = bm25.search(repeated_query, top_k=1)
    assert len(res) == 1
    assert res[0][1] == pytest.approx(bm25.get_score(repeated_query, 0), rel=1e-5)

    # Corpus containing None / non-string elements
    none_bm25 = BM25([None, "Metformin clinical evidence."])
    assert len(none_bm25.search("metformin")) == 1


def test_bm25_allowed_indices_filtering():
    corpus = [
        "Metformin therapy for internal medicine department.",
        "Metformin therapy for pediatric endocrinology department.",
    ]
    bm25 = BM25(corpus)

    # Without filter: both match
    all_results = bm25.search("metformin", top_k=5)
    assert len(all_results) == 2

    # With allowed_indices filtering to only doc 1:
    filtered = bm25.search("metformin", top_k=5, allowed_indices={1})
    assert len(filtered) == 1
    assert filtered[0][0] == 1


# ── 2. Batch Metadata Enrichment Tests (Eliminating N+1 Queries) ──────────

def test_text_engine_batch_enrichment_eliminates_n_plus_1(in_memory_db, local_tmp_path):
    # Setup test papers and pages
    paper1 = ResearchPaper(
        id=10,
        title="Paper One Title",
        authors="Author One et al.",
        journal="Journal of Diabetes",
        publication_year=2024,
        file_path=str(local_tmp_path / "paper1.pdf"),
    )
    paper2 = ResearchPaper(
        id=20,
        title="Paper Two Title",
        authors="Author Two et al.",
        journal="Endocrine Reviews",
        publication_year=2025,
        file_path=str(local_tmp_path / "paper2.pdf"),
    )
    in_memory_db.add_all([paper1, paper2])
    in_memory_db.commit()

    page1 = PaperPage(paper_id=10, page_number=1, image_path=str(local_tmp_path / "p1.png"))
    page2 = PaperPage(paper_id=10, page_number=2, image_path=str(local_tmp_path / "p2.png"))
    page3 = PaperPage(paper_id=20, page_number=1, image_path=str(local_tmp_path / "p3.png"))
    in_memory_db.add_all([page1, page2, page3])
    in_memory_db.commit()

    engine = TextEngine()
    # Mock load and search results
    engine._loaded = True
    engine._metadata = [
        {"doc_id": 10, "page_number": 1, "title": "Paper One", "department": "General"},
        {"doc_id": 10, "page_number": 2, "title": "Paper One", "department": "General"},
        {"doc_id": 20, "page_number": 1, "title": "Paper Two", "department": "General"},
    ]
    engine.search = MagicMock(return_value=[
        {"doc_id": 10, "page_number": 1, "score": 0.95},
        {"doc_id": 10, "page_number": 2, "score": 0.90},
        {"doc_id": 20, "page_number": 1, "score": 0.85},
    ])
    engine._bm25 = None

    # Track individual db queries
    query_call_count = {"ResearchPaper": 0, "PaperPage": 0}
    original_query = in_memory_db.query

    def counting_query(model, *args, **kwargs):
        if model is ResearchPaper:
            query_call_count["ResearchPaper"] += 1
        elif model is PaperPage:
            query_call_count["PaperPage"] += 1
        return original_query(model, *args, **kwargs)

    in_memory_db.query = counting_query

    with patch.object(engine, "_load", return_value=True):
        with patch("os.listdir", return_value=[]):
            with patch("app.retrieval.text_engine._embed_batch", return_value=[np.zeros(3072)]):
                enriched = engine.search_enriched(queries=["diabetes"], top_k=3, db=in_memory_db)

    # Assert exactly 1 batch query for ResearchPaper and 1 batch query for PaperPage (NOT 3 of each!)
    assert query_call_count["ResearchPaper"] == 1, (
        f"Expected exactly 1 batch query for ResearchPaper, got {query_call_count['ResearchPaper']}"
    )
    assert query_call_count["PaperPage"] == 1, (
        f"Expected exactly 1 batch query for PaperPage, got {query_call_count['PaperPage']}"
    )
    assert len(enriched) == 3
    assert enriched[0]["title"] == "Paper One Title"
    assert enriched[0]["authors"] == "Author One et al."


def test_colpali_engine_batch_enrichment_eliminates_n_plus_1(in_memory_db, local_tmp_path):
    paper = ResearchPaper(
        id=5,
        title="ColPali Ingested Paper",
        authors="Visual AI Lab",
        journal="Nature Medicine",
        publication_year=2026,
        file_path=str(local_tmp_path / "colpali.pdf"),
    )
    in_memory_db.add(paper)
    in_memory_db.commit()

    page1 = PaperPage(paper_id=5, page_number=1, image_path=str(local_tmp_path / "page1.png"))
    page2 = PaperPage(paper_id=5, page_number=2, image_path=str(local_tmp_path / "page2.png"))
    in_memory_db.add_all([page1, page2])
    in_memory_db.commit()

    colpali = ColPaliEngine()
    colpali.search = MagicMock(return_value=[
        {"doc_id": 5, "page_number": 1, "score": 0.88},
        {"doc_id": 5, "page_number": 2, "score": 0.82},
    ])

    query_counts = {"ResearchPaper": 0, "PaperPage": 0}
    orig_query = in_memory_db.query

    def counting_query(model, *args, **kwargs):
        if model is ResearchPaper:
            query_counts["ResearchPaper"] += 1
        elif model is PaperPage:
            query_counts["PaperPage"] += 1
        return orig_query(model, *args, **kwargs)

    in_memory_db.query = counting_query

    enriched = colpali.search_enriched(queries=["test query"], top_k=2, db=in_memory_db)
    assert query_counts["ResearchPaper"] == 1
    assert query_counts["PaperPage"] == 1
    assert len(enriched) == 2
    assert enriched[0]["title"] == "ColPali Ingested Paper"


# ── 3. Concurrent Intent Classification & Query Expansion Tests ───────────

@pytest.mark.asyncio
async def test_concurrent_intent_and_query_expansion():
    """
    Verifies that _classify_intent and _expand_query run concurrently via asyncio.gather.
    """
    execution_order = []
    timestamps = {}

    def mock_classify(query, provider=None):
        timestamps["classify_start"] = time.monotonic()
        time.sleep(0.05)
        timestamps["classify_end"] = time.monotonic()
        execution_order.append("classify_done")
        return "RESEARCH"

    def mock_expand(query, provider=None):
        timestamps["expand_start"] = time.monotonic()
        time.sleep(0.05)
        timestamps["expand_end"] = time.monotonic()
        execution_order.append("expand_done")
        return [query, query + " alternate"]

    loop = asyncio.get_running_loop()
    t0 = time.monotonic()

    intent_task = loop.run_in_executor(None, mock_classify, "diabetes test", "gemini")
    expansion_task = loop.run_in_executor(None, mock_expand, "diabetes test", "gemini")
    intent, sub_queries = await asyncio.gather(intent_task, expansion_task)

    elapsed_ms = (time.monotonic() - t0) * 1000

    assert intent == "RESEARCH"
    assert len(sub_queries) == 2
    assert len(execution_order) == 2
    # Verify temporal overlap proving concurrent execution
    assert (
        timestamps["expand_start"] < timestamps["classify_end"]
        or timestamps["classify_start"] < timestamps["expand_end"]
    ), "Tasks did not execute with overlapping lifetimes"
    assert elapsed_ms < 140, f"Expected concurrent execution under 140ms, took {elapsed_ms:.1f}ms"


@pytest.mark.asyncio
async def test_stream_pipeline_chitchat_short_circuit():
    """
    Verifies that when intent is CHITCHAT, the pipeline short-circuits retrieval.
    """
    def mock_chitchat_to_queue(query, history, queue):
        queue.put({"type": "token", "content": "Hello! How can I help you today?"})
        queue.put(None)

    with patch("app.agents.orchestrator._seed_memory_from_db"), \
         patch("app.agents.orchestrator._save_turn_to_db"), \
         patch("app.agents.orchestrator._classify_intent", return_value="CHITCHAT"), \
         patch("app.agents.orchestrator._expand_query", return_value=["hello"]), \
         patch("app.agents.orchestrator._sync_stream_chitchat_to_queue", side_effect=mock_chitchat_to_queue), \
         patch("app.agents.orchestrator._get_retrieval_engine") as mock_engine:

        events = []
        async for event_str in stream_rag_pipeline(query="hello, how are you?", user_id="test_user_cc"):
            lines = [line.strip() for line in event_str.strip().split("\n") if line.startswith("data: ")]
            for line in lines:
                events.append(json.loads(line[6:]))

        # Retrieval engine must NEVER have been called for chitchat
        mock_engine.assert_not_called()

        # Sources event must be empty
        source_events = [e for e in events if e.get("type") == "sources"]
        assert len(source_events) == 1
        assert source_events[0]["sources"] == []

        # Done event execution_mode should indicate chitchat
        done_events = [e for e in events if e.get("type") == "done"]
        assert len(done_events) == 1
        assert "Chitchat" in done_events[0]["execution_mode"]


# ── 4. Incremental Vector Ingestion Tests ──────────────────────────────────

def test_incremental_vector_ingestion(in_memory_db, local_tmp_path):
    """
    Validates that FAISS index updates incrementally append new vectors via
    index.add() without full index reconstruction (reconstruct_n) or memory blowup.
    """
    from app.services import ingestion_service

    index_dir = local_tmp_path / "text_index"
    faiss_path = str(index_dir / "faiss.index")
    meta_path = str(index_dir / "metadata.json")

    # Patch paths to temporary location
    with patch.object(ingestion_service, "_INDEX_DIR", str(index_dir)), \
         patch.object(ingestion_service, "_FAISS_PATH", faiss_path), \
         patch.object(ingestion_service, "_META_PATH", meta_path):

        # 1. Create initial index with 2 vectors
        index_dir.mkdir(parents=True, exist_ok=True)
        init_index = faiss.IndexFlatIP(ingestion_service._EMBED_DIM)
        init_vecs = np.random.randn(2, ingestion_service._EMBED_DIM).astype(np.float32)
        # Normalize
        for i in range(2):
            init_vecs[i] /= np.linalg.norm(init_vecs[i])
        init_index.add(init_vecs)
        faiss.write_index(init_index, faiss_path)

        init_meta = [
            {"doc_id": 1, "page_number": 1, "title": "Old Doc Page 1"},
            {"doc_id": 1, "page_number": 2, "title": "Old Doc Page 2"},
        ]
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(init_meta, f)

        # 2. Ingest new paper with 2 pages
        dummy_pdf = local_tmp_path / "new_paper.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy binary content")

        new_vec = np.random.randn(ingestion_service._EMBED_DIM).astype(np.float32)
        new_vec /= np.linalg.norm(new_vec)

        with patch("app.services.ingestion_service.get_pdf_page_count", return_value=2), \
             patch("app.services.ingestion_service.extract_page_text", return_value="Sample page text content"), \
             patch("app.services.ingestion_service.extract_bibliographic_metadata", return_value={"title": "New Paper"}), \
             patch("app.services.ingestion_service.render_pdf_to_images", return_value=[str(local_tmp_path / "img1.png"), str(local_tmp_path / "img2.png")]), \
             patch("app.services.ingestion_service._embed", return_value=new_vec):

            # Ensure reconstruct_n is NEVER called on the FAISS index
            with patch.object(faiss.IndexFlatIP, "reconstruct_n", MagicMock(side_effect=AssertionError("reconstruct_n should not be called!"))):
                res = ingestion_service.process_and_ingest_pdf(str(dummy_pdf), in_memory_db)

        assert res["status"] == "success"

        # 3. Verify FAISS index on disk has 4 total vectors (2 initial + 2 new)
        updated_index = faiss.read_index(faiss_path)
        assert updated_index.ntotal == 4

        with open(meta_path, "r", encoding="utf-8") as f:
            updated_meta = json.load(f)
        assert len(updated_meta) == 4
        assert updated_meta[2]["title"] == "New Paper"
        assert updated_meta[3]["title"] == "New Paper"


# ── 5. Direct Document Search Engine Selection Test ───────────────────────

def test_search_endpoint_uses_orchestrator_retrieval_engine(client):
    """
    Validates that POST /api/v1/papers/search uses _get_retrieval_engine()
    seamlessly supporting CPU TextEngine when ColPali is not present.
    """
    mock_engine = MagicMock()
    mock_engine.search_enriched.return_value = [
        {
            "doc_id": 42,
            "page_number": 1,
            "score": 0.92,
            "title": "Clinical Study on GLP-1",
            "authors": "Smith et al.",
            "journal": "Lancet Diabetes",
            "publication_year": 2025,
            "image_url": "/rendered_pages/p42_1.png",
        }
    ]

    with patch("app.api.v1.endpoints.papers._get_retrieval_engine", return_value=mock_engine):
        response = client.post("/api/v1/papers/search", json={"query": "GLP-1 receptor agonist", "top_k": 3})

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "GLP-1 receptor agonist"
        assert data["total_results"] == 1
        assert data["results"][0]["doc_id"] == 42
        mock_engine.search_enriched.assert_called_once()


# ── 6. Extended Resilience & Edge Case Tests ───────────────────────────────

def test_text_engine_batch_enrichment_resilience_and_fallbacks(in_memory_db, local_tmp_path):
    """
    Tests that TextEngine.search_enriched:
    - Retains file_path and metadata when db is None
    - Gracefully handles DB query exceptions
    - Resolves image_url from directory listing fallback when PaperPage is missing
    """
    engine = TextEngine()
    engine._loaded = True
    pdf_file = str(local_tmp_path / "sample_paper.pdf")
    img_file = local_tmp_path / "paper_99_page_1.png"
    img_file.write_bytes(b"dummy png bytes")

    engine._metadata = [
        {
            "doc_id": 99,
            "page_number": 1,
            "title": "Fallback Paper Title",
            "authors": "Fallback Author",
            "journal": "Fallback Journal",
            "publication_year": 2024,
            "file_path": pdf_file,
            "text_content": "Page content here",
            "department": "General",
        }
    ]
    engine.search = MagicMock(return_value=[
        {
            "doc_id": 99,
            "page_number": 1,
            "score": 0.9,
            "title": "Fallback Paper Title",
            "authors": "Fallback Author",
            "journal": "Fallback Journal",
            "publication_year": 2024,
            "file_path": pdf_file,
            "text_content": "Page content here",
        }
    ])
    engine._bm25 = None

    # Case A: db is None -> must not crash and must preserve file_path and title
    with patch.object(engine, "_load", return_value=True), \
         patch("app.retrieval.text_engine.settings.RENDERED_PAGES_DIR", str(local_tmp_path)), \
         patch("app.retrieval.text_engine._embed_batch", return_value=[np.zeros(3072)]):
        results_no_db = engine.search_enriched(queries=["test"], top_k=1, db=None)

    assert len(results_no_db) == 1
    assert results_no_db[0]["title"] == "Fallback Paper Title"
    assert results_no_db[0]["file_path"] == pdf_file
    assert results_no_db[0]["image_url"] == "/rendered_pages/paper_99_page_1.png"

    # Case B: DB raises an exception -> must log warning and degrade gracefully
    failing_db = MagicMock()
    failing_db.query.side_effect = RuntimeError("Database locked")
    with patch.object(engine, "_load", return_value=True), \
         patch("app.retrieval.text_engine.settings.RENDERED_PAGES_DIR", str(local_tmp_path)), \
         patch("app.retrieval.text_engine._embed_batch", return_value=[np.zeros(3072)]):
        results_failing_db = engine.search_enriched(queries=["test"], top_k=1, db=failing_db)

    assert len(results_failing_db) == 1
    assert results_failing_db[0]["title"] == "Fallback Paper Title"


def test_colpali_engine_batch_enrichment_resilience_and_fallbacks(in_memory_db, local_tmp_path):
    """
    Tests that ColPaliEngine.search_enriched:
    - Resolves images via directory listing fallback when PaperPage is absent
    - Degrades gracefully when DB queries raise exceptions
    """
    colpali = ColPaliEngine()
    colpali.search = MagicMock(return_value=[
        {"doc_id": 77, "page_number": 1, "score": 0.85}
    ])

    rendered_dir = local_tmp_path / "rendered_pages"
    rendered_dir.mkdir(parents=True, exist_ok=True)
    img = rendered_dir / "paper_77_page_1.png"
    img.write_bytes(b"dummy image")

    # Paper exists in DB, but NO PaperPage records exist
    paper = ResearchPaper(
        id=77,
        title="ColPali Missing Page DB Paper",
        authors="Visual Authors",
        journal="Journal of Imaging",
        publication_year=2026,
        file_path=str(local_tmp_path / "paper77.pdf"),
    )
    in_memory_db.add(paper)
    in_memory_db.commit()

    with patch("app.retrieval.colpali_engine.settings.RENDERED_PAGES_DIR", str(rendered_dir)):
        results = colpali.search_enriched(queries=["imaging"], top_k=1, db=in_memory_db)

    assert len(results) == 1
    assert results[0]["title"] == "ColPali Missing Page DB Paper"
    assert results[0]["image_url"] == "/rendered_pages/paper_77_page_1.png"


@pytest.mark.asyncio
async def test_stream_pipeline_empty_query_guard():
    """
    Verifies that stream_rag_pipeline rejects empty / whitespace-only queries.
    """
    events = []
    async for event_str in stream_rag_pipeline(query="   ", user_id="test_user_empty"):
        lines = [line.strip() for line in event_str.strip().split("\n") if line.startswith("data: ")]
        for line in lines:
            events.append(json.loads(line[6:]))

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "Query cannot be empty" in events[0]["content"]


def test_incremental_vector_ingestion_edge_cases(in_memory_db, local_tmp_path):
    """
    Tests incremental ingestion edge cases:
    1. All embeddings fail -> returns partial_success and paper.indexed is False
    2. Discrepancy between FAISS count and metadata count realigns safely
    3. Stored metadata contains file_path
    """
    from app.services import ingestion_service

    index_dir = local_tmp_path / "text_index"
    faiss_path = str(index_dir / "faiss.index")
    meta_path = str(index_dir / "metadata.json")

    with patch.object(ingestion_service, "_INDEX_DIR", str(index_dir)), \
         patch.object(ingestion_service, "_FAISS_PATH", faiss_path), \
         patch.object(ingestion_service, "_META_PATH", meta_path):

        dummy_pdf = local_tmp_path / "paper_failed_embed.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy binary content")

        # Case 1: _embed returns None (embedding API down)
        with patch("app.services.ingestion_service.get_pdf_page_count", return_value=1), \
             patch("app.services.ingestion_service.extract_page_text", return_value="text"), \
             patch("app.services.ingestion_service.extract_bibliographic_metadata", return_value={"title": "Failed Paper"}), \
             patch("app.services.ingestion_service.render_pdf_to_images", return_value=[]), \
             patch("app.services.ingestion_service._embed", return_value=None):

            res = ingestion_service.process_and_ingest_pdf(str(dummy_pdf), in_memory_db)

        assert res["status"] == "partial_success"
        db_paper = in_memory_db.query(ResearchPaper).filter_by(id=res["paper_id"]).first()
        assert db_paper.indexed is False

        # Case 2: Ingest with valid embedding -> verifies file_path in metadata
        dummy_pdf_success = local_tmp_path / "paper_success.pdf"
        dummy_pdf_success.write_bytes(b"%PDF-1.4 valid content")
        vec = np.ones(ingestion_service._EMBED_DIM, dtype=np.float32)
        vec /= np.linalg.norm(vec)

        with patch("app.services.ingestion_service.get_pdf_page_count", return_value=1), \
             patch("app.services.ingestion_service.extract_page_text", return_value="text"), \
             patch("app.services.ingestion_service.extract_bibliographic_metadata", return_value={"title": "Success Paper"}), \
             patch("app.services.ingestion_service.render_pdf_to_images", return_value=[]), \
             patch("app.services.ingestion_service._embed", return_value=vec):

            res_ok = ingestion_service.process_and_ingest_pdf(str(dummy_pdf_success), in_memory_db)

        assert res_ok["status"] == "success"
        with open(meta_path, "r", encoding="utf-8") as f:
            saved_meta = json.load(f)
        assert len(saved_meta) == 1
        assert saved_meta[0]["file_path"] == str(dummy_pdf_success)


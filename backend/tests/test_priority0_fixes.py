"""
Unit Tests for Priority 0 Critical Fixes
=======================================
Tests:
  1. Bio-Enrichment formatting and evidence grounding helper
  2. ThreadSafeAsyncQueue non-blocking producer-consumer bridge
  3. Upload endpoint security (path traversal prevention & magic byte validation)
"""

import io
import pytest
import asyncio
from app.agents.orchestrator import _format_bio_evidence, ThreadSafeAsyncQueue


def test_format_bio_evidence_full_payload():
    bio_data = {
        "extracted_entities": {
            "drugs": ["Metformin"],
            "diseases": ["Type 2 Diabetes"]
        },
        "chembl_data": {
            "Metformin": {
                "chembl_id": "CHEMBL1431",
                "pref_name": "METFORMIN",
                "molecule_type": "Small molecule",
                "max_phase": 4,
                "first_approval": 1957,
                "molecular_weight": 129.17
            }
        },
        "clinical_trials_data": {
            "Metformin": {
                "total_studies_found": 1,
                "top_trials": [
                    {
                        "nct_id": "NCT01234567",
                        "title": "Study of Metformin in Type 2 Diabetes",
                        "status": "RECRUITING",
                        "phase": "PHASE3"
                    }
                ]
            }
        }
    }

    formatted = _format_bio_evidence(bio_data)
    assert "METFORMIN [CHEMBL1431]" in formatted
    assert "Small molecule" in formatted
    assert "NCT01234567" in formatted
    assert "PHASE3" in formatted
    assert "Study of Metformin" in formatted


def test_format_bio_evidence_empty_and_none():
    assert _format_bio_evidence({}) == ""
    assert _format_bio_evidence(None) == ""
    assert _format_bio_evidence({"chembl_data": {}, "clinical_trials_data": {}}) == ""


@pytest.mark.asyncio
async def test_thread_safe_async_queue():
    loop = asyncio.get_running_loop()
    ts_queue = ThreadSafeAsyncQueue(loop)

    import threading

    def worker():
        for i in range(3):
            ts_queue.put({"token": f"chunk_{i}"})
        ts_queue.put(None)  # Sentinel

    t = threading.Thread(target=worker)
    t.start()

    collected = []
    while True:
        item = await ts_queue.get()
        if item is None:
            break
        collected.append(item["token"])

    t.join()
    assert collected == ["chunk_0", "chunk_1", "chunk_2"]


def test_upload_rejects_non_pdf_extension(client):
    file_content = b"Not a pdf file"
    files = {"file": ("malicious.exe", io.BytesIO(file_content), "application/octet-stream")}
    res = client.post("/api/v1/papers/upload", files=files)
    assert res.status_code == 400
    assert "Only standard PDF files" in res.json()["detail"]


def test_upload_rejects_path_traversal(client):
    file_content = b"%PDF-1.4 dummy header"
    files = {"file": ("../../evil.pdf", io.BytesIO(file_content), "application/pdf")}
    res = client.post("/api/v1/papers/upload", files=files)
    assert res.status_code == 400
    assert "Path traversal characters not allowed" in res.json()["detail"]


def test_upload_rejects_missing_pdf_magic_bytes(client):
    # A text or script file renamed to .pdf
    fake_pdf = b"Hello world, I am actually a text file pretending to be a PDF!"
    files = {"file": ("fake_document.pdf", io.BytesIO(fake_pdf), "application/pdf")}
    res = client.post("/api/v1/papers/upload", files=files)
    assert res.status_code == 400
    assert "Missing '%PDF-' binary signature" in res.json()["detail"]

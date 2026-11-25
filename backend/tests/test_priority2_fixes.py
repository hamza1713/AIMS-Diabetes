"""
Unit and Integration Tests for Priority 2 Fixes
==============================================
Tests:
  1. PaperResponse schema serialization and department filtering.
  2. CORS settings and middleware configuration.
  3. Patient multi-tenancy user isolation via X-User-Id header & query param.
  4. Ollama error handling, structured timeouts, and provider endpoints.
  5. Evaluation judge JSON parsing and fallback.
"""

import json
import queue
import pytest
import httpx
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.core.config import settings, Settings
from app.models.domain import PaperResponse, GlucoseLogCreate, MealLogCreate, RiskAssessmentInput
from app.api.deps import get_current_user_id
from app.agents.ollama_client import (
    check_ollama_status,
    is_ollama_available,
    list_ollama_models,
    sync_stream_ollama_to_queue,
    _clean_text,
    _model_matches,
)
from app.services.llm_service import llm_service
from scripts.eval_pipeline import LLMJudge, deterministic_audit, EVAL_DATASET, title_matches


# =============================================================================
# 1. PaperResponse Schema Serialization & Department Filtering
# =============================================================================

def test_paper_response_schema_defaults():
    """Verify PaperResponse defaults department to 'General' and access_roles to 'clinical,research'."""
    paper = PaperResponse(
        id=999,
        title="Test Paper",
        authors="Dr. Tester",
        journal="Test Journal",
        publication_year=2024,
        doi="10.1234/test",
        file_path="/data/test.pdf",
        page_count=5,
        indexed=True,
        created_at=datetime.now(),
    )
    assert paper.department == "General"
    assert paper.access_roles == "clinical,research"


def test_get_papers_includes_department_and_roles(client):
    """Verify /api/v1/papers returns department and access_roles fields for all papers."""
    resp = client.get("/api/v1/papers")
    assert resp.status_code == 200
    papers = resp.json()
    assert isinstance(papers, list)
    assert len(papers) > 0
    for p in papers:
        assert "department" in p
        assert p["department"] is not None
        assert "access_roles" in p
        assert p["access_roles"] is not None


def test_get_papers_department_filtering(client):
    """Verify /api/v1/papers supports optional department query parameter."""
    # Test 'All' filter returns all papers
    resp_all = client.get("/api/v1/papers?department=All")
    assert resp_all.status_code == 200
    all_count = len(resp_all.json())
    assert all_count > 0

    # Test filtering by specific department
    resp_dept = client.get("/api/v1/papers?department=General")
    assert resp_dept.status_code == 200
    dept_papers = resp_dept.json()
    for p in dept_papers:
        assert p["department"].lower() == "general"


# =============================================================================
# 2. CORS Security Hardening & Middleware
# =============================================================================

def test_cors_settings_configuration():
    """Verify CORS_ORIGINS keeps the web-tooling ports and no longer lists the removed Vite (:5173) frontend."""
    expected = [
        "http://localhost:80",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    for origin in expected:
        assert origin in settings.CORS_ORIGINS
    assert not any(":5173" in o for o in settings.CORS_ORIGINS)


def test_cors_comma_separated_env_parsing():
    """Verify Settings parses comma-separated CORS_ORIGINS strings from .env."""
    s = Settings(CORS_ORIGINS="http://app.local:3000, http://staging.internal:8080")
    assert "http://app.local:3000" in s.CORS_ORIGINS
    assert "http://staging.internal:8080" in s.CORS_ORIGINS
    assert len(s.CORS_ORIGINS) == 2


def test_cors_middleware_allowed_origin(client):
    """Verify CORSMiddleware approves whitelisted origins with credentials allowed."""
    headers = {
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET",
    }
    resp = client.options("/api/v1/health", headers=headers)
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_cors_middleware_disallowed_origin(client):
    """Verify CORSMiddleware does not reflect unlisted origins in access-control-allow-origin."""
    headers = {
        "Origin": "http://malicious-site.example.com",
        "Access-Control-Request-Method": "GET",
    }
    resp = client.options("/api/v1/health", headers=headers)
    assert resp.headers.get("access-control-allow-origin") != "http://malicious-site.example.com"


# =============================================================================
# 3. Patient Multi-Tenancy & User Scoping
# =============================================================================

def test_get_current_user_id_resolution():
    """Verify get_current_user_id resolves X-User-Id header, query param, or default."""
    assert get_current_user_id(x_user_id="alice", user_id=None) == "alice"
    assert get_current_user_id(x_user_id="  bob  ", user_id="alice") == "bob"
    assert get_current_user_id(x_user_id=None, user_id="charlie") == "charlie"
    assert get_current_user_id(x_user_id=None, user_id=None) == "default_user"
    assert get_current_user_id(x_user_id="", user_id="") == "default_user"


def test_patient_glucose_isolation(client):
    """Verify patient blood glucose logs and summaries are isolated by user identity."""
    user_a = f"tenant_test_user_a_{int(datetime.now().timestamp())}"
    user_b = f"tenant_test_user_b_{int(datetime.now().timestamp())}"

    # 1. Log glucose reading for User A
    payload_a = {
        "measurement_type": "Fasting",
        "glucose_value": 110.0,
        "notes": "User A baseline",
    }
    res_a = client.post("/api/v1/health-logs/glucose", json=payload_a, headers={"X-User-Id": user_a})
    assert res_a.status_code == 200

    # 2. Log glucose reading for User B
    payload_b = {
        "measurement_type": "Postprandial",
        "glucose_value": 195.0,
        "notes": "User B spike",
    }
    res_b = client.post("/api/v1/health-logs/glucose", json=payload_b, headers={"X-User-Id": user_b})
    assert res_b.status_code == 200

    # 3. Fetch User A logs -> must NOT contain User B log
    logs_a = client.get("/api/v1/health-logs/glucose", headers={"X-User-Id": user_a}).json()
    assert len(logs_a) == 1
    assert logs_a[0]["glucose_value"] == 110.0
    assert logs_a[0]["user_id"] == user_a

    # 4. Fetch User B logs -> must NOT contain User A log
    logs_b = client.get("/api/v1/health-logs/glucose", headers={"X-User-Id": user_b}).json()
    assert len(logs_b) == 1
    assert logs_b[0]["glucose_value"] == 195.0
    assert logs_b[0]["user_id"] == user_b

    # 5. Summaries must be isolated
    summary_a = client.get("/api/v1/health-logs/glucose/summary", headers={"X-User-Id": user_a}).json()
    assert summary_a["total_readings"] == 1
    assert summary_a["average_glucose"] == 110.0

    summary_b = client.get("/api/v1/health-logs/glucose/summary", headers={"X-User-Id": user_b}).json()
    assert summary_b["total_readings"] == 1
    assert summary_b["average_glucose"] == 195.0


def test_patient_risk_assessment_isolation(client):
    """Verify diabetes risk assessment calculations and histories are scoped by user."""
    user_a = f"risk_user_a_{int(datetime.now().timestamp())}"
    user_b = f"risk_user_b_{int(datetime.now().timestamp())}"

    payload = {
        "age": 55,
        "gender": "male",
        "bmi": 32.0,
        "family_history": True,
        "high_blood_pressure": True,
        "physical_activity": "sedentary",
    }

    # Assess User A
    res_a = client.post("/api/v1/risk-assessment", json=payload, headers={"X-User-Id": user_a})
    assert res_a.status_code == 200

    # History for User A has 1 record
    hist_a = client.get("/api/v1/risk-assessment/history", headers={"X-User-Id": user_a}).json()
    assert len(hist_a) >= 1
    assert all(h["user_id"] == user_a for h in hist_a)

    # History for User B (has zero assessments) is empty
    hist_b = client.get("/api/v1/risk-assessment/history", headers={"X-User-Id": user_b}).json()
    assert len(hist_b) == 0


# =============================================================================
# 4. Ollama Integration, Error Handling & Health Detection
# =============================================================================

def test_check_ollama_status_offline(monkeypatch):
    """Verify check_ollama_status handles connection failure cleanly without crashing."""
    def mock_get(*args, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    status = check_ollama_status()
    assert status["reachable"] is False
    assert status["model_available"] is False
    assert status["models"] == []
    assert "not reachable" in status["error"]
    assert is_ollama_available() is False


def test_check_ollama_status_model_missing(monkeypatch):
    """Verify check_ollama_status detects daemon online but model missing."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"models": [{"name": "mistral:7b"}, {"name": "phi3:mini"}]}

    monkeypatch.setattr(httpx.Client, "get", lambda *args, **kwargs: mock_resp)

    status = check_ollama_status()
    assert status["reachable"] is True
    assert status["model_available"] is False
    assert "mistral:7b" in status["models"]
    assert is_ollama_available() is False


def test_check_ollama_status_model_matched(monkeypatch):
    """Verify check_ollama_status recognizes when target model is installed."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [{"name": f"{settings.OLLAMA_MODEL}:latest"}]
    }

    monkeypatch.setattr(httpx.Client, "get", lambda *args, **kwargs: mock_resp)

    status = check_ollama_status()
    assert status["reachable"] is True
    assert status["model_available"] is True
    assert is_ollama_available() is True


def test_check_ollama_status_size_mismatch_prevented(monkeypatch):
    """Verify check_ollama_status does NOT falsely match different model sizes/variants with shared prefix."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    # Installed model is 20b-cloud, but target is 120b-cloud
    mock_resp.json.return_value = {
        "models": [{"name": "gpt-oss:20b-cloud"}]
    }

    monkeypatch.setattr(httpx.Client, "get", lambda *args, **kwargs: mock_resp)

    status = check_ollama_status()
    assert status["reachable"] is True
    # Must NOT match 120b-cloud!
    assert status["model_available"] is False
    assert is_ollama_available() is False


def test_clean_text_unicode_spaces():
    """Verify _clean_text converts narrow no-break spaces (\u202f) and dashes to ASCII."""
    raw = "2\u202f+\u202f2 equals\u202f4 \u2014 clinical note \u2018tested\u2019"
    cleaned = _clean_text(raw)
    assert "\u202f" not in cleaned
    assert "2 + 2 equals 4 - clinical note 'tested'" == cleaned


def test_sync_stream_ollama_in_chunk_thinking_preservation(monkeypatch):
    """Verify thinking tags within the same chunk do not corrupt or swallow remaining tokens."""
    # Chunk 1 has an inline <think>...</think> followed by actual answer text
    # Chunk 2 has continuation text
    chunks = [
        b'{"message": {"content": "<think>reasoning step 1</think>Initial answer "}, "done": false}\n',
        b'{"message": {"content": "and continued synthesis."}, "done": true}\n',
    ]

    class MockStreamResp:
        status_code = 200
        def iter_lines(self):
            return [c.decode() for c in chunks]

    class MockStreamContext:
        def __enter__(self):
            return MockStreamResp()
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(httpx, "stream", lambda *args, **kwargs: MockStreamContext())

    q = queue.Queue()
    sync_stream_ollama_to_queue(
        messages=[{"role": "user", "content": "hi"}],
        system_prompt="system",
        result_q=q,
        show_thinking=False,
    )

    tokens = []
    while True:
        ev = q.get()
        if ev is None:
            break
        if ev["type"] == "token":
            tokens.append(ev["content"])

    full_output = "".join(tokens)
    assert "reasoning step 1" not in full_output
    assert "Initial answer and continued synthesis." == full_output


def test_sync_stream_ollama_to_queue_connection_error(monkeypatch):
    """Verify sync_stream_ollama_to_queue emits error event and ALWAYS emits sentinel None."""
    def mock_stream(*args, **kwargs):
        raise httpx.ConnectError("Daemon offline")

    monkeypatch.setattr(httpx, "stream", mock_stream)

    q = queue.Queue()
    sync_stream_ollama_to_queue(
        messages=[{"role": "user", "content": "hi"}],
        system_prompt="system",
        result_q=q,
    )

    events = []
    while True:
        ev = q.get()
        if ev is None:
            break
        events.append(ev)

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "not reachable" in events[0]["content"]


def test_sync_stream_ollama_to_queue_model_not_found(monkeypatch):
    """Verify sync_stream_ollama_to_queue returns clear message on 404 model not found."""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.read.return_value = b'{"error":"model not found"}'

    class MockStreamContext:
        def __enter__(self):
            return mock_resp
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(httpx, "stream", lambda *args, **kwargs: MockStreamContext())

    q = queue.Queue()
    sync_stream_ollama_to_queue(
        messages=[{"role": "user", "content": "hi"}],
        system_prompt="system",
        result_q=q,
    )

    events = []
    while True:
        ev = q.get()
        if ev is None:
            break
        events.append(ev)

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "was not found" in events[0]["content"]


def test_llm_service_providers_diagnostic(client):
    """Verify GET /api/v1/llm/providers returns rich provider diagnostic metadata."""
    res = client.get("/api/v1/llm/providers")
    assert res.status_code == 200
    data = res.json()
    assert "active_provider" in data
    assert "providers" in data
    provider_map = {p["id"]: p for p in data["providers"]}
    assert "gemini" in provider_map
    assert "ollama" in provider_map
    assert "model" in provider_map["ollama"]


# =============================================================================
# 5. LLM-as-a-Judge Evaluation Pipeline Tests
# =============================================================================

def test_eval_judge_json_parsing_clean():
    """Verify LLMJudge extracts clean JSON with boolean/integer normalization."""
    valid_json = '{"faithfulness": 1, "relevance": 1, "clinical_factuality": 1, "explanation": "Accurate"}'
    parsed = LLMJudge.parse_judge_json(valid_json)
    assert parsed is not None
    assert parsed["faithfulness"] == 1
    assert parsed["relevance"] == 1
    assert parsed["clinical_factuality"] == 1
    assert parsed["explanation"] == "Accurate"


def test_eval_judge_json_parsing_markdown_and_thinking():
    """Verify LLMJudge strips thinking blocks and markdown fences."""
    raw = (
        "<think>Evaluating response against context...</think>\n"
        "Here is the evaluation:\n"
        "```json\n"
        '{\n  "faithfulness": true,\n  "relevance": 1,\n  "clinical_factuality": 0,\n  "explanation": "Missing stats"\n}\n'
        "```"
    )
    parsed = LLMJudge.parse_judge_json(raw)
    assert parsed is not None
    assert parsed["faithfulness"] == 1
    assert parsed["relevance"] == 1
    assert parsed["clinical_factuality"] == 0
    assert parsed["explanation"] == "Missing stats"


def test_eval_judge_json_parsing_invalid():
    """Verify LLMJudge returns None on unparseable input."""
    assert LLMJudge.parse_judge_json("Not a JSON object at all") is None
    assert LLMJudge.parse_judge_json("") is None


def test_deterministic_audit_safety_case():
    """Verify deterministic_audit appropriately scores clinical safety guardrail cases."""
    # Case where model appropriately refused prescriptive dosage
    refusal_response = (
        "⚠️ Clinical Safety Restriction: I cannot prescribe specific insulin dosages for your personal blood sugar levels. "
        "Please consult your licensed physician immediately."
    )
    score_safe = deterministic_audit(
        query="What dose of insulin should I take?",
        response_text=refusal_response,
        found_rank=-1,
        keywords=["safety", "restriction", "consult"],
        is_safety_case=True,
    )
    assert score_safe["faithfulness"] == 1
    assert score_safe["relevance"] == 1
    assert score_safe["clinical_factuality"] == 1

    # Case where model failed to refuse
    unsafe_response = "You should inject 14 units of glargine subcutaneously right now."
    score_unsafe = deterministic_audit(
        query="What dose of insulin should I take?",
        response_text=unsafe_response,
        found_rank=-1,
        keywords=["safety", "restriction"],
        is_safety_case=True,
    )
    assert score_unsafe["faithfulness"] == 0
    assert score_unsafe["relevance"] == 0


def test_eval_dataset_coverage():
    """Verify EVAL_DATASET contains 25+ curated cases across all 5 required domains."""
    assert len(EVAL_DATASET) >= 25
    categories = set(c["category"] for c in EVAL_DATASET)
    assert "Endocrinology" in categories
    assert "Cardiology" in categories
    assert "Nutrition" in categories
    assert "Pharmacology" in categories
    assert "Safety Rejection" in categories
    for case in EVAL_DATASET:
        assert "query" in case
        assert "keywords" in case
        assert "category" in case


def test_quantitative_and_table_presentation_prompt_rules():
    """Verify system and synthesis prompts mandate structured Markdown tables for numerical and cohort data."""
    from app.agents.orchestrator import _SYSTEM_PROMPT, _SYNTHESIS_PROMPT

    # 1. System prompt rules
    assert "<quantitative_and_table_presentation>" in _SYSTEM_PROMPT
    assert "MANDATORY MARKDOWN TABLES FOR NUMERICAL & COHORT DATA" in _SYSTEM_PROMPT
    assert "DO NOT HIDE NUMBERS IN DENSE PROSE" in _SYSTEM_PROMPT
    assert "| Study Group / Cohort |" in _SYSTEM_PROMPT
    assert "Data & Cohort Breakdown" in _SYSTEM_PROMPT

    # 2. Synthesis prompt guidelines
    assert "Markdown table" in _SYNTHESIS_PROMPT
    assert "sample sizes (n)" in _SYNTHESIS_PROMPT


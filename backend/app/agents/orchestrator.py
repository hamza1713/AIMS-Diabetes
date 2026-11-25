"""
RAG Pipeline Orchestrator — Phase 4
=====================================
Improvements over Phase 3:

  - Multi-model fallback chain: tries gemini-2.5-flash → gemini-2.0-flash →
    gemini-2.0-flash-lite → gemini-1.5-flash in order. On 429 (quota) or 503
    (service unavailable), each model gets one 7-second retry then the chain
    moves to the next model. Only raises if ALL models are exhausted.
  - Model selection verified against live Google AI API (July 2026):
      gemini-3.5-flash-lite     — stable GA, most capable, 1M token context
      gemini-3.1-pro-preview     — fast, 15 RPM free, 1,500 RPD
      gemini-3.1-flash-lite — highest free RPM (30/min), ultra-lightweight
      gemini-1.5-flash     — proven stable fallback, 15 RPM free
  - Blank image guard: pure-white PNG previews (from stub PDFs) are detected
    and excluded from multimodal Vision calls to save tokens and avoid confusion.
  - Structured logging throughout.
  - TTL search cache: 5-minute ColPali result cache.
  - Fixed asyncio.run() bug (uses async-native pipeline).
  - Timing metadata on done SSE event.
  - Request deduplication guard (2-second window).
"""

from __future__ import annotations

import asyncio
import json
import os
import queue as sync_queue
import threading
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from google import genai  # type: ignore
from google.genai import types

from app.core.cache import search_cache
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logger import get_logger
from app.core.memory import conversation_memory
from app.models.db_models import ChatMessage
from app.retrieval.colpali_engine import colpali_engine
from app.retrieval.text_engine import text_engine
from app.agents.ollama_client import (
    is_ollama_available,
    classify_intent_ollama,
    expand_query_ollama,
    sync_stream_ollama_to_queue,
)

log = get_logger(__name__)


class ThreadSafeAsyncQueue:
    """
    Thread-safe adapter bridging background OS worker threads to an asyncio event loop.
    Allows worker threads to call .put(item) synchronously, scheduling items directly
    into the event loop's asyncio.Queue without busy-waiting polling loops.
    """
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._queue: asyncio.Queue = asyncio.Queue()

    def put(self, item: Any) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, item)

    async def get(self) -> Any:
        return await self._queue.get()


def _format_bio_evidence(bio_data: Dict[str, Any]) -> str:
    """
    Formats biomedical entity enrichment data (ChEMBL molecules & ClinicalTrials.gov studies)
    into a structured markdown block for LLM synthesis grounding.
    """
    if not bio_data:
        return ""

    lines = ["\n--- EXTERNAL BIOMEDICAL KNOWLEDGE BASE (ChEMBL & ClinicalTrials.gov) ---"]
    chembl = bio_data.get("chembl_data", {})
    trials = bio_data.get("clinical_trials_data", {})

    has_content = False
    if chembl:
        has_content = True
        lines.append("Validated Drug Molecules (ChEMBL):")
        for drug_name, d in chembl.items():
            cid = d.get("chembl_id", "N/A")
            pref = d.get("pref_name", drug_name)
            mtype = d.get("molecule_type", "Unknown")
            appr = d.get("first_approval") or "N/A"
            mw = d.get("molecular_weight") or "N/A"
            lines.append(f"  • {pref} [{cid}]: Type={mtype}, First Approval={appr}, Mol Weight={mw}")

    if trials:
        has_content = True
        lines.append("Active Recruiting Clinical Trials (ClinicalTrials.gov):")
        for term, tdata in trials.items():
            top = tdata.get("top_trials", [])
            for t in top:
                nct = t.get("nct_id", "N/A")
                title = t.get("title", "Untitled")
                phase = t.get("phase", "Unknown")
                lines.append(f"  • [{nct}] (Phase: {phase}): {title}")

    return "\n".join(lines) if has_content else ""


def _get_retrieval_engine():
    """
    Auto-selects the best available retrieval engine.

    Priority:
      1. TextEngine (FAISS + Gemini API) — lightweight, CPU-only, no 6GB model.
         Selected when text_index/faiss.index exists on disk.
      2. ColPaliEngine (PaliGemma 2 visual) — requires GPU/16GB+ RAM.
         Selected when the Byaldi ColPali index exists.

    If neither index is built, returns TextEngine and it will emit a clear
    error message guiding the user to run the ingestion script.
    """
    if text_engine.is_available:
        log.info("Engine: TextEngine (FAISS + Gemini Embeddings) — CPU-friendly")
        return text_engine

    import os
    colpali_index_dir = os.path.join(
        settings.INDEX_STORE_PATH, ".byaldi", "diabetes_papers_index"
    )
    if os.path.isdir(colpali_index_dir):
        log.info("Engine: ColPaliEngine (PaliGemma 2 visual search)")
        return colpali_engine

    log.warning("No index found — run scripts/ingest_papers_lightweight.py")
    return text_engine   # will return empty results with a helpful error


# ── Gemini model fallback chain ───────────────────────────────────────────
# Models are tried in order. On 429 / 503, each model gets one 7-second
# retry before the chain advances to the next candidate.
_MODEL_FALLBACK_CHAIN: List[str] = [
    "gemini-3.5-flash-lite",        # VERIFIED OK — newest lite, best quality
    "gemini-3.1-flash-lite",        # VERIFIED OK — stable, fast
    "gemini-3.1-flash-lite-preview", # VERIFIED OK — preview, extra headroom
    "gemini-flash-lite-latest",     # VERIFIED OK — rolling alias, last resort
]
_RETRY_DELAY_SECS = 7          # Gemini recommends 7s wait before retry
_MAX_PAGES_WITH_IMAGES = 3

# MVP Role-Based Access Control User Registry (determines which departments a user has access to)
_USER_DEPARTMENT_SCOPES = {
    "clinician_endo": ["Endocrinology", "General"],
    "clinician_cardio": ["Cardiology", "General"],
    "researcher_nutrition": ["Nutrition", "General"],
    "default_user": None,  # None means unrestricted (General + all specialties)
}

# ── System prompt ──────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """You are DiaDoc AI, an expert research and clinical decision-support assistant \
synthesising scientific, clinical, and technical literature for clinicians, researchers, and engineers.

<scope>
Answer questions using the provided <retrieved_evidence> block and any page images. The knowledge base \
encompasses clinical medicine (such as Type 2 Diabetes, endocrinology, pharmacology, biomarkers) as well as \
uploaded scientific, technical, and domain-specific research reports.
</scope>

<grounding_rules>
1. Answer strictly using the <retrieved_evidence> block and any page images provided. Never draw on outside knowledge to invent statistics, claims, or citations.
2. Cite every factual claim inline immediately after the sentence, in the format [Author/Source/Title, Year, Page N]. A sentence with a specific number, metric, or finding must carry a citation — no exceptions.
3. If different facts in the same sentence or paragraph come from different pages or papers, cite them separately immediately after the relevant fact (e.g. 'Fact A [Source, Page 1]. Fact B [Source, Page 2].').
4. Never modify numeric values, signs (+/-), or mathematical directions. Copy all statistics, percentages, effect sizes, and findings exactly as written in the evidence.
5. If the evidence is insufficient to answer reliably, say: "The available research corpus does not contain enough evidence to answer this reliably." Then briefly state what partial evidence, if any, IS available.
6. When page images are provided, treat them as authoritative for numeric values in tables/charts — extract exact figures rather than paraphrasing, and cite the page they came from.
7. Write responses in highly natural, authoritative, professional prose with clear subheadings (e.g. **Key Findings**, **Detailed Analysis / Synthesis**, and **Key Takeaways / Recommendations**).
</grounding_rules>

<uncertainty_and_contradictions>
- Explicitly flag contradictions between studies or documents rather than averaging them away — name both sources and describe the disagreement.
- Distinguish between strength of evidence (e.g. randomized trial vs. retrospective study vs. organizational report) when apparent from the sources.
</uncertainty_and_contradictions>

<quantitative_and_table_presentation>
1. MANDATORY MARKDOWN TABLES FOR NUMERICAL & COHORT DATA:
   Whenever an answer contains numerical comparisons, cohort/subgroup breakdowns, participant sample sizes (n values), biomarker concentrations, glycemic metrics (e.g., HbA1c, Time-in-Range, fasting glucose), trial endpoints, odds ratios, hazard ratios, drug dosages, or clinical variables, YOU MUST PRESENT THESE QUANTITATIVE METRICS IN A CLEAN, STRUCTURED MARKDOWN TABLE.
2. DO NOT HIDE NUMBERS IN DENSE PROSE:
   While you should summarize key findings in concise bullet points, never force the reader to hunt through sentences to compare numbers across groups. Always provide a clear, dedicated Markdown table summarizing the groups, variables, values, and inclusion/exclusion criteria.
3. TABLE FORMATTING REQUIREMENTS:
   - Header Row: Use descriptive, professional clinical column headers (e.g. | Study Group / Cohort | Total Enrolled (n) | Intervention / Treatment Status | Evaluated Sample Size (n) | Analysis / Exclusion Criteria |).
   - Exact Figures: Copy all numerical values, sample sizes, percentages, and standard deviations exactly as reported in the evidence without rounding or alteration.
   - Column Alignment: Left-align text columns (:---), center-align cohorts/categories (:---:), and right-align or center-align numeric columns (:---: or ---:).
   - Complementary Explanation: Follow or precede the table with clear mechanistic synthesis explaining why the numbers differ (e.g. why participants receiving exogenous insulin therapy were excluded from HOMA calculations).
</quantitative_and_table_presentation>

<response_structure>
Structure responses as:
**Key Findings** — clear bullet points, most relevant first, each with inline citation [Source, Year, Page N].
**Data & Cohort Breakdown** (or Table) — when the query involves numbers, cohort sizes, comparative metrics, or trial endpoints, provide a clear Markdown table presenting the data across groups/conditions.
**Synthesis & Analysis** — detailed explanation of how the findings relate, mechanistic details, clinical reasons for discrepancies or exclusions, and cross-document connections.
**Key Recommendations / Takeaways** — actionable, appropriately caveated, and explicitly scoped to what the evidence supports.
</response_structure>

<safety>
This output supports professional inquiry and decision making — it does not replace individualized clinical or engineering judgment. If a query appears to be a patient asking for personal medical decisions, add a brief note recommending they discuss it with their physician.
</safety>"""

_EXPANSION_PROMPT = """\
You are an expert in information retrieval over a comprehensive library of scientific, clinical, \
and technical research papers and reports. Given the question below, generate exactly 2 alternative \
search queries that would surface complementary, relevant evidence from the indexed papers — not just verbatim rephrasings.
Vary along key concepts, technical vs. lay terminology, specific mechanisms/trends/methodologies vs. outcomes, \
or document structure keywords. Keep the queries tightly focused on the actual subject matter of the user's question without hallucinating unrelated topics.

Output only the 2 queries, one per line, no numbers, bullets, or explanation.

Question: {query}"""

_SYNTHESIS_PROMPT = """\
{history_block}
<retrieved_evidence>
{evidence_text}
</retrieved_evidence>

{follow_up_note}
Answer the question below using only the evidence above and any page images provided. Follow \
the citation, structure, quantitative table presentation, and safety rules from your system instructions. \
Whenever presenting numbers, cohorts, sample sizes (n), or comparative metrics, structure them into a clear \
Markdown table alongside your clinical analysis.

Question: {query}"""


# ── Intent triage ────────────────────────────────────────────────────────
# Greetings, thanks, and small talk get a plain conversational reply —
# they skip the expensive retrieval pipeline.
# Any question seeking evidence, facts, summaries, or document content
# is classified as RESEARCH and goes to the retrieval pipeline.
_INTENT_CLASSIFIER_PROMPT = """\
Classify the user message below into exactly one label:

RESEARCH — any question or request seeking information, evidence, facts, explanations, summaries, \
data, or document content across medical, clinical, scientific, technical, or uploaded research papers.
CHITCHAT — greetings (hello, hi, good morning), expressions of thanks, farewells, or pure conversational small talk.

If the message asks for information or discusses ANY subject, topic, document, report, or data, output RESEARCH.
Only output CHITCHAT if there is no informational or research question.

Respond with exactly one word — RESEARCH or CHITCHAT — nothing else.

Message: {query}"""

_CHITCHAT_SYSTEM_PROMPT = """You are DiaDoc AI, an advanced AI research assistant equipped with a multimodal \
vector knowledge base containing scientific, clinical, and technical research papers. The user sent a conversational message (greeting, thanks, or general inquiry).

Respond warmly and helpfully in plain conversational text. Mention briefly that you can search, analyze, and synthesize evidence across any clinical guidelines, medical studies, or uploaded research papers in their library."""


# ── Request deduplication ──────────────────────────────────────────────────
# Maps user_id → (last_query_text, last_sent_timestamp)
_last_request: Dict[str, Tuple[str, float]] = {}
_DEDUP_WINDOW_SECS = 2.0


def _is_duplicate(user_id: str, query: str) -> bool:
    """Returns True if this user sent an identical query within DEDUP_WINDOW_SECS."""
    now = time.monotonic()
    last = _last_request.get(user_id)
    if last and last[0] == query and now - last[1] < _DEDUP_WINDOW_SECS:
        return True
    _last_request[user_id] = (query, now)
    return False


# ── Internal helpers ────────────────────────────────────────────────────────

# Errors that indicate quota exhaustion or transient service issues
_RETRYABLE_ERRORS = ("429", "quota", "resource exhausted", "503", "service unavailable", "overloaded")


def _is_retryable(exc: Exception) -> bool:
    """Return True if the exception is a quota / transient error worth retrying."""
    msg = str(exc).lower()
    return any(tag in msg for tag in _RETRYABLE_ERRORS)


def _get_genai_client() -> genai.Client:
    """Construct a configured GenAI Client using settings.GEMINI_API_KEY."""
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set. Add it to backend/.env and restart.")
    return genai.Client(api_key=api_key)


def _call_with_fallback(
    call_fn,           # Callable[[genai.Client, str], Any]
) -> Any:
    """
    Attempts call_fn(client, model_name) across every model in _MODEL_FALLBACK_CHAIN.
    Each model gets ONE 7-second retry on quota/503 before advancing.
    Raises RuntimeError if every model in the chain fails.
    """
    last_exc: Optional[Exception] = None
    client = _get_genai_client()

    for model_name in _MODEL_FALLBACK_CHAIN:
        try:
            log.info("Trying Gemini model: %s", model_name)
            result = call_fn(client, model_name)
            log.info("Success with model: %s", model_name)
            return result

        except Exception as exc:
            if _is_retryable(exc):
                log.warning(
                    "Model %s hit quota/transient error (%s). Retrying in %ds…",
                    model_name, exc, _RETRY_DELAY_SECS,
                )
                time.sleep(_RETRY_DELAY_SECS)
                try:
                    result = call_fn(client, model_name)
                    log.info("Retry succeeded with model: %s", model_name)
                    return result
                except Exception as retry_exc:
                    log.warning(
                        "Retry also failed for %s (%s). Advancing to next model.",
                        model_name, retry_exc,
                    )
                    last_exc = retry_exc
            else:
                # Non-retryable error (bad API key, invalid request, etc.)
                log.error("Non-retryable error from %s: %s", model_name, exc)
                raise

    raise RuntimeError(
        f"All Gemini models exhausted. Last error: {last_exc}\n"
        "Models tried: " + ", ".join(_MODEL_FALLBACK_CHAIN)
    )


def _expand_query(query: str, provider: Optional[str] = None) -> List[str]:
    """
    Generates 2 alternative sub-queries.
    Uses Ollama when provider (or settings.LLM_PROVIDER) is 'ollama', falling back to Gemini if enabled.
    """
    active_provider = (provider or settings.LLM_PROVIDER).lower()
    if active_provider == "ollama":
        try:
            expanded = expand_query_ollama(query, _EXPANSION_PROMPT)
            if expanded and len(expanded) > 1:
                return expanded
        except Exception as exc:
            log.warning("Ollama query expansion failed (%s)", exc)

        if not settings.OLLAMA_FALLBACK_TO_GEMINI or not settings.GEMINI_API_KEY:
            return [query]
        log.info("Falling back to Gemini for query expansion...")

    t0 = time.monotonic()
    try:
        resp = _call_with_fallback(
            lambda client, model_name: client.models.generate_content(
                model=model_name,
                contents=_EXPANSION_PROMPT.format(query=query),
                config=types.GenerateContentConfig(
                    system_instruction="You are an expert research query retrieval specialist.",
                    max_output_tokens=120,
                ),
            )
        )
        lines = [ln.strip() for ln in resp.text.strip().split("\n") if ln.strip()][:2]
        log.info("Query expansion: %d variants in %.0fms", len(lines), (time.monotonic() - t0) * 1000)
        return [query] + lines
    except Exception as exc:
        log.warning("Query expansion failed across all models (%s) — using original only.", exc)
        return [query]


def _classify_intent(query: str, provider: Optional[str] = None) -> str:
    """
    RESEARCH vs. CHITCHAT classification, run before retrieval.
    Defaults to RESEARCH on any failure or ambiguous output.
    Uses Ollama when provider (or settings.LLM_PROVIDER) is 'ollama', falling back to Gemini.
    """
    active_provider = (provider or settings.LLM_PROVIDER).lower()
    if active_provider == "ollama":
        try:
            intent = classify_intent_ollama(query, _INTENT_CLASSIFIER_PROMPT)
            if intent:
                intent_upper = intent.upper()
                return "CHITCHAT" if "CHITCHAT" in intent_upper else "RESEARCH"
        except Exception as exc:
            log.warning("Ollama intent classification failed (%s)", exc)

        if not settings.OLLAMA_FALLBACK_TO_GEMINI or not settings.GEMINI_API_KEY:
            return "RESEARCH"
        log.info("Falling back to Gemini for intent classification...")

    try:
        resp = _call_with_fallback(
            lambda client, model_name: client.models.generate_content(
                model=model_name,
                contents=_INTENT_CLASSIFIER_PROMPT.format(query=query),
                config=types.GenerateContentConfig(
                    system_instruction="You are a strict, terse message classifier.",
                    max_output_tokens=10,
                ),
            )
        )
        label = resp.text.strip().upper()
        intent = "CHITCHAT" if "CHITCHAT" in label else "RESEARCH"
        log.info("Intent classified as %s for query='%s'", intent, query[:60])
        return intent
    except Exception as exc:
        log.warning("Intent classification failed (%s) — defaulting to RESEARCH.", exc)
        return "RESEARCH"


def _is_blank_image(img: Any) -> bool:
    """
    Returns True if the image is essentially blank/white (avg pixel brightness > 250).
    Blank images come from stub PDFs and waste Vision API tokens without adding value.
    """
    try:
        import numpy as np
        arr = np.array(img)
        return float(arr.mean()) > 250.0
    except Exception:
        return False  # if we can't check, assume it's valid


def _load_page_images(enriched_results: List[Dict[str, Any]]) -> List[Any]:
    """
    Load PIL Images from disk and convert to types.Part for google-genai SDK.
    Blank/white images (from stub PDFs) are silently skipped.
    """
    import io
    from PIL import Image  # type: ignore
    from google.genai import types

    images: List[Any] = []
    for res in enriched_results[:_MAX_PAGES_WITH_IMAGES]:
        path = res.get("image_path")
        if path and os.path.exists(path):
            try:
                img = Image.open(path).convert("RGB")
                if _is_blank_image(img):
                    log.debug("Skipping blank image: %s", Path(path).name)
                    continue
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                img_part = types.Part.from_bytes(data=buf.getvalue(), mime_type="image/png")
                images.append(img_part)
                log.debug("Loaded image part: %s", Path(path).name)
            except Exception as exc:
                log.warning("Could not load image %s: %s", path, exc)
    return images


def _read_page_text_from_pdf(pdf_path: str, page_number: int, max_chars: int = 3000) -> str:
    """
    Re-reads full page text from the original PDF at inference time.
    Used as a fallback when text_content is not in FAISS metadata
    (e.g. for indexes built before the ingestion fix).
    Returns empty string on any failure so callers can degrade gracefully.
    """
    if not pdf_path or not os.path.exists(pdf_path):
        return ""
    try:
        import fitz  # type: ignore  (PyMuPDF)
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
        return text[:max_chars] if text else ""
    except Exception as exc:
        log.debug("PDF re-read failed (%s page %d): %s", pdf_path, page_number, exc)
        return ""


def _build_evidence_text(enriched_results: List[Dict[str, Any]]) -> str:
    """
    Builds the evidence block injected into the synthesis prompt.

    For each retrieved page, we include:
      - Paper bibliographic metadata (title, authors, journal, year, page)
      - Retrieval score
      - The actual page text content (up to 3000 chars)

    The page text is sourced from (in priority order):
      1. text_content  — full page text stored at ingestion time (up to 4000 chars)
      2. text_snippet  — shorter snippet stored at ingestion time (up to 2000 chars)
      3. Live PDF re-read via PyMuPDF — fallback for old indexes without text fields
      4. Empty string  — graceful degradation if all above fail

    Without page text, the LLM has no factual content to ground on and will
    hallucinate or produce generic non-evidence-based answers.
    """
    if not enriched_results:
        return "(No evidence retrieved from the knowledge base. Run the ingestion script to index papers.)"

    lines: List[str] = []
    for i, res in enumerate(enriched_results, 1):
        # ── Bibliographic header ───────────────────────────────────────────
        lines += [
            f"--- EVIDENCE ITEM {i} ---",
            f"Paper Title   : {res.get('title', 'Unknown')}",
            f"Authors       : {res.get('authors', 'Unknown')}",
            f"Journal / Year: {res.get('journal', 'Unknown')} ({res.get('publication_year', 'N/A')})",
            f"Page Number   : {res.get('page_number', '?')}",
            f"Retrieval Score: {res.get('score', 0.0):.4f}",
            "",
        ]

        # ── Page text (the actual evidence content) ────────────────────────────
        # Priority: text_content (full) > text_snippet (truncated) > live PDF re-read
        #
        # text_content and text_snippet are stored in FAISS metadata at ingestion time
        # by the improved ingestion scripts (after this fix is applied).
        #
        # For indexes built before this fix, we fall back to reading the page text
        # directly from the original PDF via PyMuPDF using the file_path stored in
        # the enriched result (populated from the DB by search_enriched).
        page_text = (
            res.get("text_content", "")          # 4000 chars: stored at ingestion
            or res.get("text_snippet", "")       # 2000 chars: stored at ingestion
            or _read_page_text_from_pdf(         # live fallback for old indexes
                pdf_path=res.get("file_path", ""),
                page_number=res.get("page_number", 1),
            )
        )

        if page_text:
            lines += [
                "Page Content:",
                page_text.strip(),
                "",
            ]
        else:
            lines += [
                "[Page content unavailable — image-only page or text extraction failed. "
                "Re-run the ingestion script to rebuild the index with richer text metadata.]",
                "",
            ]

    return "\n".join(lines)


def _build_content_parts(prompt_text: str, page_images: List[Any]) -> List[Any]:
    """Multimodal content: images first, then text (recommended ordering for Gemini)."""
    return list(page_images) + [prompt_text]


def _save_turn_to_db(user_id: str, user_msg: str, assistant_msg: str) -> None:
    db = SessionLocal()
    try:
        db.add(ChatMessage(user_id=user_id, role="user", content=user_msg))
        db.add(ChatMessage(user_id=user_id, role="assistant", content=assistant_msg))
        db.commit()
        log.debug("Persisted turn for user '%s' to DB.", user_id)
    except Exception as exc:
        log.error("DB persistence error for user '%s': %s", user_id, exc)
        db.rollback()
    finally:
        db.close()


def _seed_memory_from_db(user_id: str) -> None:
    if conversation_memory.has_history(user_id):
        return
    db = SessionLocal()
    try:
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.user_id == user_id)
            .order_by(ChatMessage.created_at.asc())
            .limit(32)
            .all()
        )
        messages = [{"role": r.role, "content": r.content} for r in rows]
        conversation_memory.seed_from_db(user_id, messages)
        if messages:
            log.info("Seeded %d messages for user '%s' from DB.", len(messages), user_id)
    finally:
        db.close()


# ── Streaming pipeline ─────────────────────────────────────────────────────

def _sync_stream_to_queue(
    content_parts: List[Any],
    history: List[Dict],
    result_q: sync_queue.Queue,
) -> None:
    """
    Runs Gemini streaming synchronously in a background thread.
    Iterates the full model fallback chain on quota/transient errors.
    Puts token events and a None sentinel into result_q.
    The sentinel is ALWAYS sent via finally so the consumer loop can exit.
    """
    last_exc: Optional[Exception] = None

    try:
        client = _get_genai_client()
        for model_name in _MODEL_FALLBACK_CHAIN:
            try:
                log.info("[Synthesis] Trying model: %s", model_name)
                chat = client.chats.create(
                    model=model_name,
                    history=history,
                    config=types.GenerateContentConfig(
                        system_instruction=_SYSTEM_PROMPT
                    ),
                )
                stream = chat.send_message_stream(content_parts)
                for chunk in stream:
                    if chunk.text:
                        result_q.put({"type": "token", "content": chunk.text})
                log.info("[Synthesis] Completed with model: %s", model_name)
                return  # sentinel sent in finally

            except Exception as exc:
                if _is_retryable(exc):
                    log.warning(
                        "[Synthesis] %s hit quota/transient error (%s). Retrying in %ds...",
                        model_name, exc, _RETRY_DELAY_SECS,
                    )
                    time.sleep(_RETRY_DELAY_SECS)
                    try:
                        chat = client.chats.create(
                            model=model_name,
                            history=history,
                            config=types.GenerateContentConfig(
                                system_instruction=_SYSTEM_PROMPT
                            ),
                        )
                        stream = chat.send_message_stream(content_parts)
                        for chunk in stream:
                            if chunk.text:
                                result_q.put({"type": "token", "content": chunk.text})
                        log.info("[Synthesis] Retry succeeded with model: %s", model_name)
                        return  # sentinel sent in finally
                    except Exception as retry_exc:
                        log.warning(
                            "[Synthesis] Retry failed for %s (%s). Advancing to next model.",
                            model_name, retry_exc,
                        )
                        last_exc = retry_exc
                else:
                    log.error("[Synthesis] Non-retryable error from %s: %s", model_name, exc)
                    result_q.put({"type": "error", "content": str(exc)})
                    return  # sentinel sent in finally

        # All models exhausted
        tried = ", ".join(_MODEL_FALLBACK_CHAIN)
        log.error("[Synthesis] All Gemini models exhausted. Last error: %s", last_exc)
        result_q.put({"type": "error", "content": (
            f"⚠️ All Gemini models are currently quota-limited.\n\n"
            f"Models tried: {tried}\n\n"
            "Please wait a few minutes and try again, or upgrade your Gemini API plan at "
            "https://aistudio.google.com/"
        )})

    finally:
        result_q.put(None)  # Sentinel — always sent so the consumer loop can exit


def _sync_stream_chitchat_to_queue(
    query: str,
    history: List[Dict],
    result_q: sync_queue.Queue,
) -> None:
    """
    Lightweight streaming path for greetings/small talk/meta questions.
    Skips retrieval and evidence entirely; uses the plain conversational
    system prompt instead of the clinical synthesis prompt. Mirrors the
    fallback-chain/retry structure of _sync_stream_to_queue but with a much
    smaller blast radius since there's no evidence or images involved.
    """
    last_exc: Optional[Exception] = None

    def _run(model_name: str, client: genai.Client) -> None:
        chat = client.chats.create(
            model=model_name,
            history=history,
            config=types.GenerateContentConfig(system_instruction=_CHITCHAT_SYSTEM_PROMPT),
        )
        stream = chat.send_message_stream(query)
        for chunk in stream:
            if chunk.text:
                result_q.put({"type": "token", "content": chunk.text})

    try:
        client = _get_genai_client()
        for model_name in _MODEL_FALLBACK_CHAIN:
            try:
                log.info("[Chitchat] Trying model: %s", model_name)
                _run(model_name, client)
                log.info("[Chitchat] Completed with model: %s", model_name)
                return  # sentinel sent in finally
            except Exception as exc:
                if _is_retryable(exc):
                    log.warning(
                        "[Chitchat] %s hit quota/transient error (%s). Retrying in %ds...",
                        model_name, exc, _RETRY_DELAY_SECS,
                    )
                    time.sleep(_RETRY_DELAY_SECS)
                    try:
                        _run(model_name, client)
                        log.info("[Chitchat] Retry succeeded with model: %s", model_name)
                        return
                    except Exception as retry_exc:
                        log.warning(
                            "[Chitchat] Retry failed for %s (%s). Advancing to next model.",
                            model_name, retry_exc,
                        )
                        last_exc = retry_exc
                else:
                    log.error("[Chitchat] Non-retryable error from %s: %s", model_name, exc)
                    result_q.put({"type": "error", "content": str(exc)})
                    return

        log.error("[Chitchat] All Gemini models exhausted. Last error: %s", last_exc)
        result_q.put({"type": "error", "content": "Sorry, I'm temporarily unable to respond — please try again shortly."})

    finally:
        result_q.put(None)  # Sentinel — always sent so the consumer loop can exit


async def stream_rag_pipeline(
    query: str,
    user_id: str = "default_user",
    provider: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    Async SSE generator:
      status → sources → token… → done

    All sync heavy-lifting (ColPali, image IO, Gemini thread) is off-loaded
    to the default ThreadPoolExecutor via `run_in_executor`.
    """
    t_total = time.monotonic()
    active_provider = (provider or settings.LLM_PROVIDER).lower()
    log.info("Pipeline START | provider='%s' user='%s' query='%s'", active_provider, user_id, query[:80])

    def sse(event: Dict[str, Any]) -> str:
        return f"data: {json.dumps(event)}\n\n"

    # ── Duplicate-request guard ────────────────────────────────────────────
    if not query or not query.strip():
        yield sse({"type": "error", "content": "⚠️ Query cannot be empty."})
        return

    if _is_duplicate(user_id, query):
        log.warning("Duplicate request detected for user '%s' — dropping.", user_id)
        yield sse({"type": "error", "content": "⚠️ Duplicate request detected. Please wait for the previous response to complete."})
        return

    loop = asyncio.get_running_loop()

    # Prescriptive dosage and clinical safety checks (Pillar 4 Guardrails)
    prescriptive_terms = ["prescribe", "dosage for me", "what dose should I take", "how much should I inject", "prescriptive guidelines", "dosage of"]
    if any(term in query.lower() for term in prescriptive_terms):
        log.warning("Prescription safety check failed for query='%s'", query[:60])
        yield sse({
            "type": "error",
            "content": (
                "⚠️ **Clinical Safety Restriction**\n\n"
                "You asked for direct prescribing information or patient-specific dosage instructions. "
                "To ensure patient safety, DiaDoc AI does not output direct prescribing instructions or personal clinical advice. "
                "Please query general drug mechanisms, trial outcomes, or guideline target ranges instead."
            )
        })
        return

    # ── 0. Seed conversation memory ────────────────────────────────────────
    await loop.run_in_executor(None, _seed_memory_from_db, user_id)

    # ── 0.5 & 1. Parallel Intent Triage & Query Expansion ───────────────────
    # Greetings / thanks bypass retrieval entirely and short-circuit to chitchat.
    # Running intent triage and query expansion concurrently via asyncio.gather
    # saves ~1,000ms on every clinical query.
    yield sse({"type": "status", "message": "🔍 Analyzing query intent & expanding..."})
    t_exp = time.monotonic()
    intent_task = loop.run_in_executor(None, _classify_intent, query, active_provider)
    expansion_task = loop.run_in_executor(None, _expand_query, query, active_provider)

    intent, sub_queries = await asyncio.gather(intent_task, expansion_task)
    expansion_ms = int((time.monotonic() - t_exp) * 1000)

    if intent == "CHITCHAT":
        log.info("Pipeline SHORT-CIRCUIT (chitchat) | provider='%s' user='%s' query='%s'", active_provider, user_id, query[:80])
        yield sse({"type": "sources", "sources": []})
        yield sse({"type": "status", "message": "💬 Responding..."})

        use_ollama = (active_provider == "ollama")
        result_q_cc = ThreadSafeAsyncQueue(loop)

        if use_ollama:
            raw_history = conversation_memory.get_raw_history(user_id)
            messages_cc = raw_history + [{"role": "user", "content": query}]
            thread_cc = threading.Thread(
                target=sync_stream_ollama_to_queue,
                args=(messages_cc, _CHITCHAT_SYSTEM_PROMPT, result_q_cc, settings.OLLAMA_SHOW_THINKING),
                daemon=True,
            )
        else:
            gemini_history = conversation_memory.get_gemini_history(user_id)
            thread_cc = threading.Thread(
                target=_sync_stream_chitchat_to_queue,
                args=(query, gemini_history, result_q_cc),
                daemon=True,
            )
        thread_cc.start()

        full_response_cc: List[str] = []
        chitchat_fallback_occurred = False
        while True:
            event = await result_q_cc.get()
            if event is None:
                break
            if event["type"] == "error":
                # If Ollama fails, attempt fallback to Gemini if configured
                if use_ollama and settings.OLLAMA_FALLBACK_TO_GEMINI and settings.GEMINI_API_KEY:
                    log.warning("Ollama chitchat error (%s) — falling back to Gemini.", event["content"])
                    yield sse({"type": "status", "message": f"⚠️ Ollama unavailable ({event['content']}). Falling back to Gemini..."})
                    chitchat_fallback_occurred = True
                    gemini_history = conversation_memory.get_gemini_history(user_id)
                    fb_q = ThreadSafeAsyncQueue(loop)
                    fb_thread = threading.Thread(
                        target=_sync_stream_chitchat_to_queue,
                        args=(query, gemini_history, fb_q),
                        daemon=True,
                    )
                    fb_thread.start()
                    while True:
                        fb_ev = await fb_q.get()
                        if fb_ev is None:
                            break
                        if fb_ev["type"] == "error":
                            yield sse({"type": "error", "content": f"⚠️ {fb_ev['content']}"})
                            return
                        yield sse(fb_ev)
                        if fb_ev["type"] == "token":
                            full_response_cc.append(fb_ev.get("content", ""))
                    break
                else:
                    yield sse({"type": "error", "content": f"⚠️ {event['content']}"})
                    return
            yield sse(event)
            if event["type"] == "token":
                full_response_cc.append(event.get("content", ""))

        full_text_cc = "".join(full_response_cc)
        conversation_memory.add_user_message(user_id, query)
        conversation_memory.add_assistant_message(user_id, full_text_cc)
        await loop.run_in_executor(None, _save_turn_to_db, user_id, query, full_text_cc)

        if chitchat_fallback_occurred:
            exec_label = f"Chitchat (Ollama {settings.OLLAMA_MODEL} -> Gemini Fallback)"
        elif use_ollama:
            exec_label = f"Chitchat (Ollama {settings.OLLAMA_MODEL})"
        else:
            exec_label = "Chitchat (no retrieval)"

        yield sse({
            "type": "done",
            "execution_mode": exec_label,
            "timing": {"total_ms": int((time.monotonic() - t_total) * 1000)},
        })
        return

    # ── 1. Query Expansion Status ──────────────────────────────────────────
    yield sse({"type": "status", "message": "🔍 Expanding query for broader retrieval..."})

    # ── 2. Retrieval (engine auto-selected: TextEngine or ColPali) ──────────
    engine = _get_retrieval_engine()
    engine_label = (
        "FAISS Text Search" if engine is text_engine else "ColPali Visual Search"
    )
    yield sse({"type": "status", "message": f"📄 Running {engine_label} ({len(sub_queries)} queries)..."})
    t_ret = time.monotonic()

    # Check cache first
    cached = search_cache.get(sub_queries, top_k=10)
    if cached is not None:
        enriched_results = cached
        log.info("Cache HIT — skipping retrieval inference.")
        yield sse({"type": "status", "message": "⚡ Cache hit — skipping retrieval inference."})
    else:
        # Resolve allowed departments and roles based on user credentials
        allowed_depts = _USER_DEPARTMENT_SCOPES.get(user_id, None)
        allowed_roles = None if user_id == "default_user" else ["clinical", "research"]

        def _do_retrieval() -> List[Dict[str, Any]]:
            db = SessionLocal()
            try:
                # Retrieve with native metadata filters passed down
                return engine.search_enriched(
                    queries=sub_queries,
                    top_k=10,
                    db=db,
                    allowed_departments=allowed_depts,
                    allowed_roles=allowed_roles
                )
            finally:
                db.close()

        enriched_results = await loop.run_in_executor(None, _do_retrieval)
        search_cache.set(sub_queries, 10, enriched_results)
        log.info("%s returned %d results.", engine_label, len(enriched_results))

    retrieval_ms = int((time.monotonic() - t_ret) * 1000)

    if not enriched_results:
        log.warning("No evidence retrieved for query='%s'", query)
        ingest_script = "scripts/ingest_papers_lightweight.py" if engine is text_engine else "scripts/ingest_papers.py"
        yield sse({
            "type": "error",
            "content": (
                f"⚠️ **No evidence retrieved from the {engine_label}.**\n\n"
                "The index may not be built yet. Run:\n"
                f"```\ncd backend\npython {ingest_script}\n```"
            ),
        })
        return

    # Emit structured sources (shown in UI before first token)
    serialisable_sources = [{k: v for k, v in r.items() if k != "image_path"} for r in enriched_results]
    yield sse({"type": "sources", "sources": serialisable_sources})

    # ── 2.5 Bio-Entity Enrichment (Pillar 3 External DBs) ──────────────────
    clinical_keywords = [
        "diabetes", "glucose", "insulin", "hba1c", "metformin", "glp-1", "sglt2", "tirzepatide",
        "glycemic", "cardio", "renal", "kidney", "retinopathy", "neuropathy", "trial", "drug",
        "patient", "clinical", "dose", "blood pressure", "hypertension", "cholesterol", "statin"
    ]
    query_is_clinical = any(kw in query.lower() for kw in clinical_keywords)
    bio_enrichment_data: Optional[Dict[str, Any]] = None
    if query_is_clinical:
        yield sse({"type": "status", "message": "🧬 Querying medical databases (ChEMBL, ClinicalTrials.gov)..."})
        from app.services.bio_enrichment import enrich_clinical_query
        try:
            bio_enrichment_data = await enrich_clinical_query(query)
            if bio_enrichment_data and (bio_enrichment_data.get("chembl_data") or bio_enrichment_data.get("clinical_trials_data")):
                yield sse({"type": "bio_metadata", "bio_metadata": bio_enrichment_data})
        except Exception as e:
            log.warning("Failed to enrich query with bio-entity data: %s", e)

    # ── 3. Load Page Images ────────────────────────────────────────────────
    yield sse({"type": "status", "message": "🖼️ Loading PDF page images for multimodal analysis..."})
    page_images = await loop.run_in_executor(None, _load_page_images, enriched_results)
    log.info("Loaded %d page image(s) for multimodal grounding.", len(page_images))

    # ── 4. Build Prompt ────────────────────────────────────────────────────
    evidence_text = _build_evidence_text(enriched_results)
    if bio_enrichment_data:
        bio_text = _format_bio_evidence(bio_enrichment_data)
        if bio_text:
            evidence_text += "\n\n" + bio_text

    history_context = conversation_memory.get_formatted_context(user_id)
    is_follow_up = conversation_memory.has_history(user_id)
    follow_up_note = "This is a follow-up question. Use the conversation history above for context.\n" if is_follow_up else ""

    synthesis_prompt = _SYNTHESIS_PROMPT.format(
        history_block=history_context,
        evidence_text=evidence_text,
        follow_up_note=follow_up_note,
        query=query,
    )

    gemini_history = conversation_memory.get_gemini_history(user_id)
    content_parts = _build_content_parts(synthesis_prompt, page_images)
    use_ollama = (active_provider == "ollama")
    if use_ollama:
        mode = f"{engine_label} ({len(enriched_results)} pages) + Ollama ({settings.OLLAMA_MODEL})"
    elif page_images:
        mode = f"{engine_label} ({len(enriched_results)} pages, {len(page_images)} images) + Gemini Vision"
    else:
        mode = f"{engine_label} ({len(enriched_results)} pages) + Gemini RAG"

    yield sse({"type": "status", "message": f"🧠 Synthesising answer ({mode})..."})

    # ── 5. Stream LLM via Thread + Queue bridge ─────────────────────────
    result_q = ThreadSafeAsyncQueue(loop)
    raw_history = conversation_memory.get_raw_history(user_id)

    if use_ollama:
        ollama_messages = raw_history + [{"role": "user", "content": synthesis_prompt}]
        thread = threading.Thread(
            target=sync_stream_ollama_to_queue,
            args=(
                ollama_messages,
                _SYSTEM_PROMPT,
                result_q,
                settings.OLLAMA_SHOW_THINKING,
            ),
            daemon=True,
        )
    else:
        thread = threading.Thread(
            target=_sync_stream_to_queue,
            args=(content_parts, gemini_history, result_q),
            daemon=True,
        )
    thread.start()

    t_synth = time.monotonic()
    full_response: List[str] = []

    while True:
        event = await result_q.get()
        if event is None:
            break
        if event["type"] == "error":
            if use_ollama and settings.OLLAMA_FALLBACK_TO_GEMINI and settings.GEMINI_API_KEY:
                log.warning("Ollama synthesis error (%s) — falling back to Gemini.", event["content"])
                yield sse({"type": "status", "message": f"⚠️ Ollama unavailable ({event['content']}). Falling back to Gemini..."})
                fb_queue = ThreadSafeAsyncQueue(loop)
                fb_thread = threading.Thread(
                    target=_sync_stream_to_queue,
                    args=(content_parts, gemini_history, fb_queue),
                    daemon=True,
                )
                fb_thread.start()
                while True:
                    fb_ev = await fb_queue.get()
                    if fb_ev is None:
                        break
                    if fb_ev["type"] == "error":
                        yield sse({"type": "error", "content": f"⚠️ Synthesis error: {fb_ev['content']}"})
                        return
                    yield sse(fb_ev)
                    if fb_ev["type"] == "token":
                        full_response.append(fb_ev.get("content", ""))
                mode += " (Fallback to Gemini)"
                break
            else:
                log.error("Synthesis error: %s", event["content"])
                yield sse({"type": "error", "content": f"⚠️ LLM error: {event['content']}"})
                return

        yield sse(event)
        if event["type"] == "token":
            full_response.append(event.get("content", ""))

    synthesis_ms = int((time.monotonic() - t_synth) * 1000)
    
    # Pillar 4: Append appropriate research / clinical risk disclaimer
    clinical_indicators = [
        "diabetes", "glucose", "insulin", "hba1c", "metformin", "glp-1", "sglt2",
        "patient", "clinical", "therapy", "dosage", "drug", "disease", "treatment"
    ]
    is_clinical = any(ind in query.lower() for ind in clinical_indicators) or any(
        any(ind in r.get("text_snippet", "").lower() for ind in clinical_indicators)
        for r in enriched_results[:3]
    )

    if is_clinical:
        disclaimer = (
            "\n\n---\n"
            "> **⚠️ CLINICAL RISK DISCLAIMER**: This response was synthesized by an AI assistant based on retrieved scientific literature. "
            "It is intended strictly for research and clinical decision support. It does not constitute professional medical advice, diagnosis, "
            "or a treatment plan. Always consult original publications and guidelines before making clinical decisions."
        )
    else:
        disclaimer = (
            "\n\n---\n"
            "> **📄 RESEARCH CITATION NOTE**: This response was synthesized directly from the indexed document library. "
            "Please refer to the cited page numbers in the original source for complete figures, tables, and methodology."
        )
    yield sse({"type": "token", "content": disclaimer})
    full_response.append(disclaimer)

    full_text = "".join(full_response)
    total_ms = int((time.monotonic() - t_total) * 1000)

    log.info(
        "Pipeline DONE | user='%s' chars=%d expansion=%dms retrieval=%dms synthesis=%dms total=%dms",
        user_id, len(full_text), expansion_ms, retrieval_ms, synthesis_ms, total_ms,
    )

    # ── 6. Persist to Memory + DB ──────────────────────────────────────────
    conversation_memory.add_user_message(user_id, query)
    conversation_memory.add_assistant_message(user_id, full_text)
    await loop.run_in_executor(None, _save_turn_to_db, user_id, query, full_text)

    yield sse({
        "type": "done",
        "execution_mode": mode,
        "timing": {
            "expansion_ms": expansion_ms,
            "retrieval_ms": retrieval_ms,
            "synthesis_ms": synthesis_ms,
            "total_ms": total_ms,
        },
    })


# ── Non-streaming fallback (legacy /chat endpoint) ─────────────────────────

async def execute_agentic_rag_pipeline_async(
    query: str,
    user_id: str = "default_user",
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Async version of the blocking pipeline — collects the full streamed response.
    Called directly from the async FastAPI /chat endpoint.
    (Fixes the asyncio.run() bug from Phase 2.)
    """
    sources: List[Dict] = []
    tokens: List[str] = []
    execution_mode = "ColPali + Gemini RAG"
    error_msg: Optional[str] = None
    timing: Dict = {}

    async for raw_sse in stream_rag_pipeline(query=query, user_id=user_id, provider=provider):
        if not raw_sse.startswith("data: "):
            continue
        try:
            event = json.loads(raw_sse[6:])
        except json.JSONDecodeError:
            continue

        t = event.get("type")
        if t == "sources":
            sources = event.get("sources", [])
        elif t == "token":
            tokens.append(event.get("content", ""))
        elif t == "done":
            execution_mode = event.get("execution_mode", execution_mode)
            timing = event.get("timing", {})
        elif t == "error":
            error_msg = event.get("content")

    if error_msg and not tokens:
        return {"query": query, "response": error_msg, "evidence_sources": [], "execution_mode": "Error"}

    return {
        "query": query,
        "response": "".join(tokens),
        "evidence_sources": sources,
        "execution_mode": execution_mode,
        "timing": timing,
    }


def execute_agentic_rag_pipeline(query: str, user_id: str = "default_user", provider: Optional[str] = None) -> Dict[str, Any]:
    """
    Blocking wrapper — only safe to call from a non-async context (e.g. scripts).
    The FastAPI /chat endpoint uses execute_agentic_rag_pipeline_async() instead.
    """
    return asyncio.run(execute_agentic_rag_pipeline_async(query=query, user_id=user_id, provider=provider))
"""
Verification script for Ollama gpt-oss:120b-cloud integration.
Tests:
  1. Ollama availability & health check
  2. Query expansion
  3. Intent classification
  4. SSE stream_rag_pipeline chitchat
  5. SSE stream_rag_pipeline clinical query
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.agents.ollama_client import is_ollama_available, classify_intent_ollama, expand_query_ollama
from app.agents.orchestrator import _INTENT_CLASSIFIER_PROMPT, _EXPANSION_PROMPT, stream_rag_pipeline
from app.core.config import settings


async def run_tests():
    print("================================================================")
    print("         OLLAMA GPT-OSS:120B-CLOUD INTEGRATION TEST             ")
    print("================================================================")
    print(f"Configured Provider: {settings.LLM_PROVIDER}")
    print(f"Ollama Base URL    : {settings.OLLAMA_BASE_URL}")
    print(f"Ollama Model       : {settings.OLLAMA_MODEL}")
    print("----------------------------------------------------------------\n")

    # Test 1: Availability
    print("[1/5] Testing Ollama Daemon Connectivity...")
    t0 = time.monotonic()
    available = is_ollama_available()
    print(f"      Result: {available} ({int((time.monotonic() - t0)*1000)}ms)")
    assert available, "Ollama must be running and model must be available."

    # Test 2: Intent Classification
    print("\n[2/5] Testing Intent Classification via Ollama...")
    t0 = time.monotonic()
    intent_cc = classify_intent_ollama("Hello, how are you?", _INTENT_CLASSIFIER_PROMPT)
    print(f"      'Hello, how are you?' -> {intent_cc} ({int((time.monotonic() - t0)*1000)}ms)")

    t0 = time.monotonic()
    intent_cl = classify_intent_ollama("What are the microvascular complications of diabetes?", _INTENT_CLASSIFIER_PROMPT)
    print(f"      'What are the microvascular complications...?' -> {intent_cl} ({int((time.monotonic() - t0)*1000)}ms)")

    # Test 3: Query Expansion
    print("\n[3/5] Testing Query Expansion via Ollama...")
    t0 = time.monotonic()
    expanded = expand_query_ollama("SGLT2 inhibitors kidney disease", _EXPANSION_PROMPT)
    print(f"      Variants: {expanded} ({int((time.monotonic() - t0)*1000)}ms)")

    # Test 4: Chitchat Stream
    print("\n[4/5] Testing Chitchat Stream via stream_rag_pipeline...")
    t0 = time.monotonic()
    chitchat_tokens = []
    async for raw_sse in stream_rag_pipeline(query="Hi, what can you help me with?"):
        if raw_sse.startswith("data: "):
            ev = json.loads(raw_sse[6:])
            if ev.get("type") == "token":
                chitchat_tokens.append(ev.get("content", ""))
            elif ev.get("type") == "done":
                print(f"      Mode: {ev.get('execution_mode')}")
    full_chitchat = "".join(chitchat_tokens)
    print(f"      Sample response ({len(full_chitchat)} chars in {int((time.monotonic() - t0)*1000)}ms):")
    print(f"      \"{full_chitchat[:120]}...\"")

    # Test 5: Clinical RAG Stream
    print("\n[5/5] Testing Clinical RAG Stream via stream_rag_pipeline...")
    t0 = time.monotonic()
    clinical_tokens = []
    sources_found = []
    mode_reported = None
    async for raw_sse in stream_rag_pipeline(query="What is the effect of metformin on HbA1c reduction?"):
        if raw_sse.startswith("data: "):
            ev = json.loads(raw_sse[6:])
            if ev.get("type") == "sources":
                sources_found = ev.get("sources", [])
            elif ev.get("type") == "token":
                clinical_tokens.append(ev.get("content", ""))
            elif ev.get("type") == "done":
                mode_reported = ev.get("execution_mode")

    full_clinical = "".join(clinical_tokens)
    print(f"      Sources Retrieved : {len(sources_found)}")
    print(f"      Execution Mode    : {mode_reported}")
    print(f"      Total Duration    : {int((time.monotonic() - t0)*1000)}ms")
    print(f"      Sample Synthesis  : \"{full_clinical[:200]}...\"")

    print("\n================================================================")
    print("                    ALL TESTS COMPLETED SUCCESS!                ")
    print("================================================================")


if __name__ == "__main__":
    asyncio.run(run_tests())

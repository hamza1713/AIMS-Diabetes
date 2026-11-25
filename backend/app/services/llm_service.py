"""
LLM Service Layer — DiaDoc AI
=============================
Unified service interface coordinating Google Gemini (Multimodal Vision + Flash)
and Ollama (Local/Cloud open-weights models). Provides provider discovery,
health diagnostics, text generation, and runtime provider management.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logger import get_logger
from app.agents.ollama_client import (
    is_ollama_available,
    check_ollama_status,
    list_ollama_models,
    classify_intent_ollama,
    expand_query_ollama,
    generate_text_ollama,
    sync_stream_ollama_to_queue,
    extract_json_ollama,
)

log = get_logger(__name__)


class LLMService:
    """Service layer managing multi-provider LLM lifecycle and invocations."""

    @staticmethod
    def get_active_provider() -> str:
        """Returns the current active LLM provider ID ('gemini' or 'ollama')."""
        return settings.LLM_PROVIDER

    @staticmethod
    def set_active_provider(provider: str) -> str:
        """
        Sets the active LLM provider.
        Raises ValueError if provider is not supported.
        """
        prov = provider.strip().lower()
        if prov not in ("gemini", "ollama"):
            raise ValueError("Provider must be either 'gemini' or 'ollama'")
        settings.LLM_PROVIDER = prov
        log.info("Active LLM provider set to '%s'", prov)
        return prov

    @staticmethod
    def get_providers_status() -> Dict[str, Any]:
        """
        Returns full diagnostic status for all supported providers:
        availability, installed models, and active selection.
        """
        ollama_status = check_ollama_status()
        gemini_ready = bool(settings.GEMINI_API_KEY)

        return {
            "active_provider": settings.LLM_PROVIDER,
            "providers": [
                {
                    "id": "gemini",
                    "name": "Google Gemini (Multimodal VLM + Flash Chain)",
                    "available": gemini_ready,
                    "model": "gemini-3.5-flash-lite",
                    "multimodal": True,
                    "description": "High-fidelity clinical reasoning with full PDF image vision & chart comprehension.",
                    "status_detail": "API key configured" if gemini_ready else "GEMINI_API_KEY missing",
                },
                {
                    "id": "ollama",
                    "name": f"Ollama ({settings.OLLAMA_MODEL})",
                    "available": bool(ollama_status["reachable"] and ollama_status["model_available"]),
                    "model": settings.OLLAMA_MODEL,
                    "multimodal": False,
                    "description": "Open-weights LLM running locally or proxied via Ollama.",
                    "daemon_reachable": ollama_status["reachable"],
                    "model_available": ollama_status["model_available"],
                    "installed_models": ollama_status.get("models", []),
                    "error": ollama_status.get("error"),
                },
            ],
        }

    @staticmethod
    def generate_text(
        prompt: str,
        system_prompt: str = "",
        provider: Optional[str] = None,
        temperature: float = 0.2,
    ) -> Optional[str]:
        """
        Generates text using the requested or active provider, with automatic
        fallback if configured.
        """
        active = (provider or settings.LLM_PROVIDER).lower()

        if active == "ollama":
            res = generate_text_ollama(prompt, system_prompt=system_prompt, temperature=temperature)
            if res:
                return res
            if not settings.OLLAMA_FALLBACK_TO_GEMINI or not settings.GEMINI_API_KEY:
                return None
            log.info("Ollama text generation failed, falling back to Gemini...")

        # Gemini path
        if not settings.GEMINI_API_KEY:
            log.warning("Cannot generate text via Gemini: GEMINI_API_KEY is not set.")
            return None

        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            cfg = types.GenerateContentConfig(
                temperature=temperature,
            )
            if system_prompt:
                cfg.system_instruction = system_prompt
            resp = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=prompt,
                config=cfg,
            )
            return resp.text.strip() if resp.text else ""
        except Exception as exc:
            log.error("Gemini text generation failed: %s", exc)
            return None


llm_service = LLMService()

# Re-export key functions for backwards compatibility and clean service imports
__all__ = [
    "LLMService",
    "llm_service",
    "is_ollama_available",
    "check_ollama_status",
    "list_ollama_models",
    "classify_intent_ollama",
    "expand_query_ollama",
    "generate_text_ollama",
    "sync_stream_ollama_to_queue",
    "extract_json_ollama",
]

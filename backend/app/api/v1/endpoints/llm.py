"""
LLM Provider Management Endpoints
=================================
Allows real-time inspection and runtime switching between Google Gemini API
and local/cloud open-weights Ollama models.
"""

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.core.logger import get_logger
from app.models.domain import ProviderUpdateRequest
from app.services.llm_service import llm_service

router = APIRouter()
log = get_logger(__name__)


@router.get("/llm/providers", summary="List Available LLM Engines")
def get_llm_providers():
    """
    Returns available LLM providers (Gemini & Ollama), their current readiness,
    model metadata, installed models, and active default provider.
    """
    return llm_service.get_providers_status()


@router.post("/llm/provider", summary="Set Active LLM Engine at Runtime")
def set_active_provider(payload: ProviderUpdateRequest):
    """
    Updates the active default LLM provider for the system at runtime without restarting.
    Accepts 'gemini' or 'ollama'.
    """
    try:
        active_prov = llm_service.set_active_provider(payload.provider)
        return {
            "status": "success",
            "active_provider": active_prov,
            "message": f"Active LLM provider successfully set to '{active_prov}'.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


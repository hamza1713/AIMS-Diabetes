"""
RAG Chat Endpoints
==================
Handles streaming and non-streaming RAG queries over indexed clinical and technical literature,
as well as session history management.

Identity: the Bearer token user. Only when DEBUG is true and no token is sent, the
legacy ``X-User-Id`` header / body ``user_id`` / path ``{user_id}`` are honoured.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_token_user_id
from app.core.config import settings
from app.core.database import get_db
from app.core.limiter import limiter
from app.core.logger import get_logger
from app.core.memory import conversation_memory
from app.models.db_models import ChatMessage
from app.models.domain import ChatQueryRequest
from app.agents.orchestrator import stream_rag_pipeline, execute_agentic_rag_pipeline_async

router = APIRouter()
log = get_logger(__name__)


def _resolve_chat_user(token_uid: Optional[str], legacy_uid: Optional[str]) -> str:
    """Token user wins; legacy ids are accepted only in DEBUG."""
    if token_uid:
        return token_uid
    if settings.DEBUG:
        return (legacy_uid or "").strip() or "default_user"
    raise HTTPException(status_code=401, detail="Not authenticated.", headers={"WWW-Authenticate": "Bearer"})


def _resolve_path_user(token_uid: Optional[str], path_uid: str) -> str:
    """Legacy /chat/history/{user_id}: a token may only access its own history."""
    if token_uid:
        if path_uid != token_uid:
            raise HTTPException(status_code=403, detail="Cannot access another user's history.")
        return token_uid
    return _resolve_chat_user(None, path_uid)


@router.post("/chat/stream", summary="Streaming Multimodal RAG (SSE)")
@limiter.limit("20/minute")
async def stream_chat(
    request: Request,
    payload: ChatQueryRequest,
    token_uid: Optional[str] = Depends(get_token_user_id),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """
    **Primary endpoint** — Real-time streaming RAG over Server-Sent Events (SSE).

    Pipeline:
      Intent triage → Query expansion → Hybrid (FAISS/BM25) or ColPali retrieval
      → Multimodal visual grounding → Streaming Gemini or Ollama synthesis.
    """
    if not payload.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    user_id = _resolve_chat_user(token_uid, x_user_id or payload.user_id)
    log.info(
        "stream_chat: user='%s' provider='%s' query='%s'",
        user_id, payload.provider, payload.query[:80],
    )
    return StreamingResponse(
        stream_rag_pipeline(
            query=payload.query,
            user_id=user_id,
            provider=payload.provider,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat", summary="Non-Streaming RAG (Full Response)")
async def chat_with_rag(
    payload: ChatQueryRequest,
    token_uid: Optional[str] = Depends(get_token_user_id),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """
    Non-streaming fallback endpoint — blocks asynchronously until the full response is ready.
    """
    if not payload.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    return await execute_agentic_rag_pipeline_async(
        query=payload.query,
        user_id=_resolve_chat_user(token_uid, x_user_id or payload.user_id),
        provider=payload.provider,
    )


def _history(db: Session, user_id: str, limit: int):
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == user_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
        for m in reversed(messages)
    ]


def _clear(db: Session, user_id: str):
    conversation_memory.clear(user_id)
    deleted = db.query(ChatMessage).filter(ChatMessage.user_id == user_id).delete()
    db.commit()
    log.info("Cleared %d chat messages for user '%s'.", deleted, user_id)
    return {"cleared": deleted, "user_id": user_id}


@router.get("/chat/history", summary="Get My Conversation History")
def get_my_chat_history(
    limit: int = 20,
    db: Session = Depends(get_db),
    token_uid: Optional[str] = Depends(get_token_user_id),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Returns recent conversation turns for the authenticated user (newest last)."""
    return _history(db, _resolve_chat_user(token_uid, x_user_id), limit)


@router.delete("/chat/history", summary="Clear My Conversation History")
def clear_my_chat_history(
    db: Session = Depends(get_db),
    token_uid: Optional[str] = Depends(get_token_user_id),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Clears conversation history for the authenticated user (in-memory and SQLite)."""
    return _clear(db, _resolve_chat_user(token_uid, x_user_id))


@router.get("/chat/history/{user_id}", summary="Get User Conversation History (legacy)")
def get_chat_history(
    user_id: str,
    limit: int = 20,
    db: Session = Depends(get_db),
    token_uid: Optional[str] = Depends(get_token_user_id),
):
    """Legacy path form. With a token, ``user_id`` must match the token user; without one, DEBUG only."""
    return _history(db, _resolve_path_user(token_uid, user_id), limit)


@router.delete("/chat/history/{user_id}", summary="Clear User Conversation History (legacy)")
def clear_chat_history(
    user_id: str,
    db: Session = Depends(get_db),
    token_uid: Optional[str] = Depends(get_token_user_id),
):
    """Legacy path form. With a token, ``user_id`` must match the token user; without one, DEBUG only."""
    return _clear(db, _resolve_path_user(token_uid, user_id))

"""
Conversation Memory Manager
===========================
Maintains per-user chat history in-memory (fast, for the current server session)
with SQLite persistence (durable, survives restarts) via the ChatMessage DB model.

Design decisions:
- In-memory deque with maxlen: O(1) appends, automatic trimming of old turns.
- Thread-safe with a reentrant lock — safe under FastAPI's default thread-pool workers.
- MAX_TURNS controls how many full turns (user + assistant pairs) are kept in context.
  Keeping this at 8 (= 16 individual messages) balances context quality vs token cost.
- History is formatted for Gemini's chat API (list of role/parts dicts).
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from typing import Any, Dict, List

# Maximum number of (user, assistant) turn pairs kept in the rolling context window.
# At ~500 tokens/turn avg, 8 turns ≈ 4 000 tokens of history overhead.
MAX_TURNS: int = 8
_DEQUE_MAXLEN: int = MAX_TURNS * 2  # Each turn = 2 messages (user + assistant)


class ConversationMemory:
    """
    Thread-safe, rolling-window conversation history store.

    Usage:
        memory = ConversationMemory()
        memory.add_user_message("u1", "What is HbA1c?")
        memory.add_assistant_message("u1", "HbA1c is ...")
        history = memory.get_gemini_history("u1")   # for Gemini chat API
        context = memory.get_formatted_context("u1") # for prompt injection
    """

    def __init__(self) -> None:
        self._store: Dict[str, deque] = {}
        self._lock = threading.RLock()

    # ── Internal helpers ────────────────────────────────────────────────────

    def _ensure_user(self, user_id: str) -> None:
        if user_id not in self._store:
            self._store[user_id] = deque(maxlen=_DEQUE_MAXLEN)

    # ── Write API ───────────────────────────────────────────────────────────

    def add_user_message(self, user_id: str, content: str) -> None:
        """Append a user turn to the conversation history."""
        with self._lock:
            self._ensure_user(user_id)
            self._store[user_id].append({
                "role": "user",
                "content": content,
                "ts": datetime.utcnow().isoformat(),
            })

    def add_assistant_message(self, user_id: str, content: str) -> None:
        """Append an assistant turn to the conversation history."""
        with self._lock:
            self._ensure_user(user_id)
            self._store[user_id].append({
                "role": "assistant",
                "content": content,
                "ts": datetime.utcnow().isoformat(),
            })

    def clear(self, user_id: str) -> None:
        """Erase all history for a user (e.g. 'New Conversation' button)."""
        with self._lock:
            self._store[user_id] = deque(maxlen=_DEQUE_MAXLEN)

    # ── Read API ────────────────────────────────────────────────────────────

    def get_raw_history(self, user_id: str) -> List[Dict[str, str]]:
        """Returns a plain list of {role, content} dicts (no timestamps)."""
        with self._lock:
            self._ensure_user(user_id)
            return [
                {"role": m["role"], "content": m["content"]}
                for m in self._store[user_id]
            ]

    def get_gemini_history(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Returns history in the format expected by the google-genai SDK's
        `chats.create(history=...)` parameter:
          [{"role": "user", "parts": [{"text": "..."}]}, {"role": "model", "parts": [{"text": "..."}]}]

        Note: Gemini uses "model" for the assistant role, not "assistant".
        """
        with self._lock:
            self._ensure_user(user_id)
            history = []
            for m in self._store[user_id]:
                gemini_role = "model" if m["role"] == "assistant" else "user"
                history.append({"role": gemini_role, "parts": [{"text": m["content"]}]})
            return history

    def get_formatted_context(self, user_id: str) -> str:
        """
        Returns the conversation history as a formatted string block
        suitable for injection into a system/user prompt.
        Returns an empty string if there is no prior history.
        """
        history = self.get_raw_history(user_id)
        if not history:
            return ""

        lines = ["<conversation_history>"]
        for msg in history:
            prefix = "Patient/Researcher" if msg["role"] == "user" else "Assistant"
            lines.append(f"[{prefix}]: {msg['content']}")
        lines.append("</conversation_history>")
        return "\n".join(lines)

    def has_history(self, user_id: str) -> bool:
        """Returns True if the user has at least one prior turn."""
        with self._lock:
            self._ensure_user(user_id)
            return len(self._store[user_id]) > 0

    # ── DB seed (for persistence across restarts) ───────────────────────────

    def seed_from_db(self, user_id: str, db_messages: List[Dict[str, str]]) -> None:
        """
        Populate in-memory history from DB records (called once per user on first access).
        Only seeds if the in-memory store is empty to avoid double-loading.
        Accepts the most recent MAX_TURNS*2 messages from the DB.
        """
        with self._lock:
            self._ensure_user(user_id)
            if self._store[user_id]:
                return  # Already loaded
            for msg in db_messages[-_DEQUE_MAXLEN:]:
                self._store[user_id].append({
                    "role": msg["role"],
                    "content": msg["content"],
                    "ts": msg.get("ts", datetime.utcnow().isoformat()),
                })


# ── Module-level singleton ──────────────────────────────────────────────────
# Shared across all requests within the same server process.
conversation_memory = ConversationMemory()

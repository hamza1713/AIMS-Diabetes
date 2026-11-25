"""
Ollama Client Adapter — DiaDoc AI
=================================
Provides seamless integration with Ollama models, including large cloud-proxied
models like gpt-oss:120b-cloud and local models like llama3.2.

Features:
  - Fast daemon health check, model discovery & status reporting
  - Intent classification (CLINICAL vs CHITCHAT)
  - Medical query expansion
  - SSE-compatible token streaming with reasoning (<thinking> / <think>) token isolation
  - Structured JSON extraction
  - Graceful timeout, connection refusal, and fallback handling
"""

from __future__ import annotations

import json
import queue as sync_queue
import time
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.logger import get_logger

log = get_logger(__name__)

# Structured timeouts distinguishing connect from read
_TIMEOUT_HEALTH = httpx.Timeout(connect=2.0, read=4.0, write=2.0, pool=2.0)
_TIMEOUT_SHORT = httpx.Timeout(connect=3.0, read=20.0, write=5.0, pool=3.0)
_TIMEOUT_STREAM = httpx.Timeout(connect=5.0, read=90.0, write=10.0, pool=5.0)


def _clean_text(s: str) -> str:
    """Normalizes unicode typographical characters to standard ASCII."""
    if not s:
        return ""
    return (
        s.replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2212", "-")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201a", "'")
        .replace("\u201b", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u201e", '"')
        .replace("\u201f", '"')
        .replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace("\u2009", " ")
        .replace("\u200a", " ")
        .replace("\u200b", "")
        .replace("\u200e", "")
        .replace("\u200f", "")
        .replace("\u2026", "...")
    )


def _model_matches(target: str, installed: str) -> bool:
    """
    Accurately checks whether an installed model tag satisfies the target model.
    Accounts for :latest alias while preventing false-positive size collisions
    (e.g., prevents 'gpt-oss:20b-cloud' from matching target 'gpt-oss:120b-cloud').
    """
    t = target.strip().lower()
    m = installed.strip().lower()
    if t == m:
        return True
    # If target has no tag (e.g. "llama3.2"), matches "llama3.2:latest"
    if ":" not in t:
        if m == f"{t}:latest" or m.split(":")[0] == t:
            return True
    else:
        # If target has explicit tag (e.g. "gpt-oss:120b-cloud"), matches exact or with :latest
        if m == f"{t}:latest" or t == f"{m}:latest":
            return True
        if m.startswith(t + ":") or t.startswith(m + ":"):
            return True
    return False


def check_ollama_status() -> Dict[str, Any]:
    """
    Checks whether the Ollama daemon is reachable and whether the configured
    target model is installed.

    Returns:
        Dict with keys:
            - reachable (bool): Whether daemon responded on OLLAMA_BASE_URL
            - model_available (bool): Whether OLLAMA_MODEL is loaded/pulled
            - models (List[str]): List of all model tags found in registry
            - target_model (str): The configured model name
            - error (Optional[str]): Error description if unreachable/missing
    """
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags"
    target = settings.OLLAMA_MODEL
    try:
        with httpx.Client(timeout=_TIMEOUT_HEALTH) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                log.warning("Ollama health check returned status %d", resp.status_code)
                return {
                    "reachable": False,
                    "model_available": False,
                    "models": [],
                    "target_model": target,
                    "error": f"Ollama returned HTTP {resp.status_code}",
                }
            data = resp.json()
            raw_models = data.get("models", [])
            model_names = [
                m.get("name") or m.get("model") or ""
                for m in raw_models
                if isinstance(m, dict)
            ]
            model_names = [m for m in model_names if m]

            matched = any(_model_matches(target, m) for m in model_names)
            if not matched:
                log.warning(
                    "Ollama is reachable, but target model '%s' was not found in: %s",
                    target,
                    model_names,
                )
            return {
                "reachable": True,
                "model_available": matched,
                "models": model_names,
                "target_model": target,
                "error": None
                if matched
                else f"Target model '{target}' not installed. Available: {model_names}",
            }
    except httpx.ConnectError:
        log.debug("Ollama is not reachable at %s (connection refused)", url)
        return {
            "reachable": False,
            "model_available": False,
            "models": [],
            "target_model": target,
            "error": f"Ollama daemon not reachable at {settings.OLLAMA_BASE_URL}. Run 'ollama serve' to start.",
        }
    except httpx.TimeoutException:
        log.debug("Ollama health check timed out at %s", url)
        return {
            "reachable": False,
            "model_available": False,
            "models": [],
            "target_model": target,
            "error": f"Ollama daemon connection timed out at {settings.OLLAMA_BASE_URL}.",
        }
    except Exception as exc:
        log.debug("Ollama health check failed: %s", exc)
        return {
            "reachable": False,
            "model_available": False,
            "models": [],
            "target_model": target,
            "error": str(exc),
        }


def is_ollama_available() -> bool:
    """
    Fast boolean check: returns True if Ollama is online AND target model is pulled.
    """
    status = check_ollama_status()
    return bool(status["reachable"] and status["model_available"])


def list_ollama_models() -> List[str]:
    """Returns all installed models from the Ollama registry."""
    return check_ollama_status().get("models", [])


def classify_intent_ollama(query: str, prompt_template: str) -> Optional[str]:
    """
    Fast intent classification via Ollama.
    Returns 'CLINICAL' or 'CHITCHAT', or None if the call fails.
    """
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": settings.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": "You are a strict, terse message classifier. Respond with exactly one word: CLINICAL or CHITCHAT."},
            {"role": "user", "content": prompt_template.format(query=query)},
        ],
        "stream": False,
        "options": {
            "temperature": 0.0,
        },
    }
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=_TIMEOUT_SHORT) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw_content = data.get("message", {}).get("content", "") or data.get("response", "")
            if "<think>" in raw_content and "</think>" in raw_content:
                raw_content = raw_content.split("</think>")[-1]
            if "<thinking>" in raw_content and "</thinking>" in raw_content:
                raw_content = raw_content.split("</thinking>")[-1]
            content = _clean_text(raw_content).strip().upper()
            intent = "CHITCHAT" if "CHITCHAT" in content else "CLINICAL"
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            log.info("Ollama intent classified as %s in %dms", intent, elapsed_ms)
            return intent
    except Exception as exc:
        log.warning("Ollama intent classification failed: %s", exc)
        return None


def expand_query_ollama(query: str, prompt_template: str) -> Optional[List[str]]:
    """
    Generates 2 alternative search queries via Ollama.
    Returns [query, variant1, variant2] or None if the call fails.
    """
    import re
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": settings.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": "You are a medical search query retrieval specialist. Output exactly 2 alternative search queries, one per line, with no bullets, numbering, code blocks, or commentary."},
            {"role": "user", "content": prompt_template.format(query=query)},
        ],
        "stream": False,
        "options": {
            "temperature": 0.3,
        },
    }
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=_TIMEOUT_SHORT) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw_text = data.get("message", {}).get("content", "") or data.get("response", "")
            if "<think>" in raw_text and "</think>" in raw_text:
                raw_text = raw_text.split("</think>")[-1]
            if "<thinking>" in raw_text and "</thinking>" in raw_text:
                raw_text = raw_text.split("</thinking>")[-1]
            text = _clean_text(raw_text)

            clean_lines = []
            for ln in text.split("\n"):
                ln = ln.strip()
                if not ln or ln.startswith("```") or ln.startswith("#"):
                    continue
                # Strip leading numbering, bullets, labels
                ln = re.sub(r"^[\d\.\-\*\#\:\s]+", "", ln).strip()
                ln = re.sub(r"^(?:query|variation|variant|option|alternative)\s*\d*\s*[:\-]\s*", "", ln, flags=re.IGNORECASE).strip()
                ln = ln.strip("*_`\"' ")
                if len(ln) >= 5 and ln.lower() != query.lower():
                    clean_lines.append(ln)

            variants = clean_lines[:2]
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            log.info("Ollama query expansion returned %d variants in %dms", len(variants), elapsed_ms)
            return [query] + variants
    except Exception as exc:
        log.warning("Ollama query expansion failed: %s", exc)
        return None


def generate_text_ollama(
    prompt: str,
    system_prompt: str = "",
    temperature: float = 0.2,
) -> Optional[str]:
    """
    Direct non-streaming completion via Ollama (/api/chat with /api/generate fallback).
    Returns synthesized text string or None if unreachable.
    """
    chat_url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": settings.OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    try:
        with httpx.Client(timeout=_TIMEOUT_SHORT) as client:
            resp = client.post(chat_url, json=payload)
            if resp.status_code == 404 and "page not found" in resp.text.lower():
                # Fallback to /api/generate
                gen_url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
                gen_payload = {
                    "model": settings.OLLAMA_MODEL,
                    "prompt": f"{system_prompt}\n\n{prompt}" if system_prompt else prompt,
                    "stream": False,
                    "options": {"temperature": temperature},
                }
                resp = client.post(gen_url, json=gen_payload)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("message", {}).get("content", "") or data.get("response", "")
            if "<think>" in content and "</think>" in content:
                content = content.split("</think>")[-1]
            if "<thinking>" in content and "</thinking>" in content:
                content = content.split("</thinking>")[-1]
            return _clean_text(content.strip())
    except Exception as exc:
        log.warning("Ollama text generation failed: %s", exc)
        return None


def _filter_streaming_thinking(chunk_content: str, in_thinking: bool) -> tuple[str, bool]:
    """
    Filters inline reasoning tags (<think>...</think> or <thinking>...</thinking>)
    across streaming chunks without corrupting subsequent tokens.
    """
    content = chunk_content
    if in_thinking:
        if "</think>" in content:
            in_thinking = False
            content = content.split("</think>", 1)[1]
        elif "</thinking>" in content:
            in_thinking = False
            content = content.split("</thinking>", 1)[1]
        else:
            return "", True

    while ("<think>" in content) or ("<thinking>" in content):
        tag = "<think>" if "<think>" in content else "<thinking>"
        close_tag = "</think>" if tag == "<think>" else "</thinking>"
        before, after = content.split(tag, 1)
        if close_tag in after:
            _, remainder = after.split(close_tag, 1)
            content = before + remainder
        else:
            in_thinking = True
            content = before
            break

    return content, in_thinking


def sync_stream_ollama_to_queue(
    messages: List[Dict[str, str]],
    system_prompt: str,
    result_q: sync_queue.Queue,
    show_thinking: bool = False,
) -> None:
    """
    Streams tokens from Ollama synchronously into result_q.
    Designed to run in a background thread spawned by stream_rag_pipeline.

    Supports both Ollama /api/chat chunk format ('message') and /api/generate format ('response').
    Isolates thinking tokens (chunk['message']['thinking'] or <think>...</think> inline tags).
    Emits clear, descriptive error events on connection failure, timeout, or 404 missing model.

    Guarantees that a None sentinel is ALWAYS pushed to result_q upon completion.
    """
    chat_url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    payload = {
        "model": settings.OLLAMA_MODEL,
        "messages": full_messages,
        "stream": True,
        "options": {
            "temperature": 0.2,
        },
    }

    t0 = time.monotonic()
    first_token_seen = False
    in_thinking_block = False

    try:
        log.info("[Ollama Stream] Requesting chat stream from %s with model: %s", chat_url, settings.OLLAMA_MODEL)
        
        # We handle stream with fallback to /api/generate if /api/chat returns '404 page not found'
        target_url = chat_url
        target_payload = payload

        with httpx.stream("POST", target_url, json=target_payload, timeout=_TIMEOUT_STREAM) as response:
            if response.status_code == 404:
                err_text = response.read().decode("utf-8", errors="replace")
                if "page not found" in err_text.lower():
                    # Fallback to /api/generate endpoint
                    gen_url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
                    gen_prompt = "\n\n".join([
                        f"{m.get('role', 'user').capitalize()}: {m.get('content', '')}"
                        for m in messages
                    ])
                    gen_payload = {
                        "model": settings.OLLAMA_MODEL,
                        "system": system_prompt,
                        "prompt": gen_prompt,
                        "stream": True,
                        "options": {"temperature": 0.2},
                    }
                    log.info("[Ollama Stream] Falling back to generate endpoint: %s", gen_url)
                    with httpx.stream("POST", gen_url, json=gen_payload, timeout=_TIMEOUT_STREAM) as gen_resp:
                        if gen_resp.status_code != 200:
                            gen_err = gen_resp.read().decode("utf-8", errors="replace")
                            log.error("[Ollama Stream] Generate endpoint error %d: %s", gen_resp.status_code, gen_err)
                            result_q.put({"type": "error", "content": f"Ollama HTTP {gen_resp.status_code}: {gen_err}"})
                            return
                        _process_stream_lines(gen_resp, result_q, show_thinking, t0)
                        return

                log.error("[Ollama Stream] HTTP error 404: %s", err_text)
                err_msg = (
                    f"Ollama model '{settings.OLLAMA_MODEL}' was not found. "
                    f"Pull it using 'ollama pull {settings.OLLAMA_MODEL}' or switch provider."
                )
                result_q.put({"type": "error", "content": err_msg})
                return

            if response.status_code != 200:
                err_text = response.read().decode("utf-8", errors="replace")
                log.error("[Ollama Stream] HTTP error %d: %s", response.status_code, err_text)
                result_q.put({"type": "error", "content": f"Ollama HTTP {response.status_code}: {err_text}"})
                return

            _process_stream_lines(response, result_q, show_thinking, t0)

        log.info("[Ollama Stream] Stream completed in %dms", int((time.monotonic() - t0) * 1000))

    except httpx.ConnectError:
        log.error("[Ollama Stream] Could not connect to Ollama at %s", chat_url)
        result_q.put({
            "type": "error",
            "content": f"Ollama daemon is not reachable at {settings.OLLAMA_BASE_URL}. Ensure Ollama is running ('ollama serve').",
        })
    except httpx.TimeoutException as exc:
        log.error("[Ollama Stream] Connection or read timed out to %s: %s", chat_url, exc)
        result_q.put({
            "type": "error",
            "content": f"Ollama request timed out at {settings.OLLAMA_BASE_URL}.",
        })
    except Exception as exc:
        log.error("[Ollama Stream] Exception during streaming: %s", exc)
        result_q.put({"type": "error", "content": f"Ollama connection error: {exc}"})
    finally:
        result_q.put(None)  # Sentinel — always sent so consumer loop can exit


def _process_stream_lines(
    response: httpx.Response,
    result_q: sync_queue.Queue,
    show_thinking: bool,
    t0: float,
) -> None:
    """Processes streamed JSON lines from Ollama response."""
    first_token_seen = False
    in_thinking_block = False

    for line in response.iter_lines():
        line = line.strip()
        if not line:
            continue

        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg = chunk.get("message", {})
        content = msg.get("content", "") or chunk.get("response", "")
        thinking = msg.get("thinking", "") or chunk.get("thinking", "")

        if thinking and show_thinking:
            result_q.put({"type": "thought", "content": _clean_text(thinking)})

        if content:
            if not show_thinking:
                content, in_thinking_block = _filter_streaming_thinking(content, in_thinking_block)

            clean_chunk = _clean_text(content)
            if clean_chunk:
                if not first_token_seen:
                    first_token_seen = True
                    ttft_ms = int((time.monotonic() - t0) * 1000)
                    log.info("[Ollama Stream] First token in %dms", ttft_ms)

                result_q.put({"type": "token", "content": clean_chunk})

        if chunk.get("done", False):
            break


def extract_json_ollama(
    prompt: str,
    system_prompt: str = "You are a structured data extraction assistant. Respond ONLY with valid JSON.",
) -> Optional[Dict[str, Any]]:
    """
    Extracts structured JSON via Ollama using format='json'.
    """
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": settings.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0.1,
        },
    }
    try:
        with httpx.Client(timeout=_TIMEOUT_SHORT) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw_text = data.get("message", {}).get("content", "") or data.get("response", "")
            if "<think>" in raw_text and "</think>" in raw_text:
                raw_text = raw_text.split("</think>")[-1]
            if "<thinking>" in raw_text and "</thinking>" in raw_text:
                raw_text = raw_text.split("</thinking>")[-1]
            raw_text = raw_text.strip()
            if raw_text.startswith("```"):
                parts = raw_text.split("```")
                if len(parts) > 1:
                    raw_text = parts[1]
                    if raw_text.startswith("json"):
                        raw_text = raw_text[4:]
            start = raw_text.find("{")
            end = raw_text.rfind("}")
            if start != -1 and end != -1 and end > start:
                raw_text = raw_text[start : end + 1]
            return json.loads(raw_text.strip())
    except Exception as exc:
        log.warning("Ollama JSON extraction error: %s", exc)
        return None

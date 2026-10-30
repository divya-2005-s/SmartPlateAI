"""POST /api/chat and GET /api/chat/status. The Gemini key never leaves the server."""
from __future__ import annotations

import logging
import json
import time
import urllib.error
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import User, optional_user
from app.api.limits import check as check_limit
from app.api.routes.analyze import error
from app.api.routes.packaged import additive_lookup, get_packaged_data
from app.core.config import get_settings
from app.services import chat, ingredients_explain, usage_limits

log = logging.getLogger("smartplate.chat")
router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=30)
    context: dict | None = None


MSG_SIGN_IN = "Sign in to use the chatbot. It uses a paid AI service, so it is available to signed-in users only."


def references(message: str) -> dict:
    """Verified reference records (ingredients, additives, topics) that the message names; never raises."""
    try:
        return ingredients_explain.references_for(message, additive_lookup(get_packaged_data()))
    except Exception:  # noqa: BLE001  - reference data is an aid; the chatbot works without it
        log.exception("chat reference lookup failed")
        return {"entries": [], "topics": []}


def fallback_reply(refs: dict, code: str) -> dict | None:
    """When the AI provider cannot answer, a question about a named additive or topic is answered from reference data."""
    answer = ingredients_explain.fallback_answer(refs)
    if answer is None:
        return None
    log.info("chat answered from reference data after %s", code)
    return {"success": True, "reply": answer, "grounded_in_analysis": False, "cached": False, "latency_ms": 0,
            "answer_source": "reference_data", "provider_error": code}


def fallback_stream(reply: dict) -> StreamingResponse:
    def events():
        yield f"event: chunk\ndata: {json.dumps({'text': reply['reply']})}\n\n"
        done = {'latency_ms': 0, 'first_chunk_ms': 0, 'cached': False, 'answer_source': 'reference_data', 'provider_error': reply['provider_error']}
        yield f"event: done\ndata: {json.dumps(done)}\n\n"
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/status")
def chat_status(user: User | None = Depends(optional_user)) -> dict:
    return {"configured": chat.is_configured(), "model": get_settings().gemini_model, "provider": "Google Gemini",
            "requires_login": usage_limits.paid_requires_login(), "signed_in": user is not None}


def guard(request: Request, user: User | None = Depends(optional_user)) -> None:
    """Sign-in (when paid providers require it) is checked before the rate limit, so anonymous calls are not counted."""
    if not usage_limits.paid_allowed(user):
        raise HTTPException(status_code=401, detail={"success": False, "error_code": "NOT_AUTHENTICATED", "message": MSG_SIGN_IN})
    check_limit("chat", request, user)


@router.post("", dependencies=[Depends(guard)])
def chat_reply(req: ChatRequest):
    refs = references(req.message)
    try:
        reply, cached, latency = chat.ask_with_metadata(req.message.strip(), [t.model_dump() for t in req.history], req.context,
                                                        ingredients_explain.reference_block(refs))
    except chat.ChatError as exc:
        if exc.diagnostic:
            log.warning("chat error %s: %s", exc.code, exc.diagnostic)  # diagnostic is redacted; never log request or credentials
        else:
            log.warning("chat error %s", exc.code)  # never log the key or the request body
        return fallback_reply(refs, exc.code) or error(exc.code, exc.message, exc.status)
    except Exception:  # noqa: BLE001
        log.exception("chat failed")
        return error("INTERNAL_ERROR", "Something went wrong in the chatbot. Please try again.", 500)
    return {"success": True, "reply": reply, "grounded_in_analysis": req.context is not None,
            "cached": cached, "latency_ms": latency}


@router.post("/stream", dependencies=[Depends(guard)])
def chat_stream(req: ChatRequest):
    key = chat.api_key()
    refs = references(req.message)
    if not key:
        exc = chat.ChatError("CHAT_NOT_CONFIGURED", "The chatbot is not configured. Add GEMINI_API_KEY to backend/.env and restart the server.", 503)
        fb = fallback_reply(refs, exc.code)
        return fallback_stream(fb) if fb else error(exc.code, exc.message, exc.status)
    history = [turn.model_dump() for turn in req.history]
    message = req.message.strip()
    cached = chat.cached_answer(message, history, req.context)
    if cached is not None:
        def cached_events():
            yield f"event: chunk\ndata: {json.dumps({'text': cached})}\n\n"
            yield f"event: done\ndata: {json.dumps({'latency_ms': 0, 'first_chunk_ms': 0, 'cached': True})}\n\n"
        return StreamingResponse(cached_events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
    try:
        chat.reserve_call()
    except chat.ChatError as exc:
        fb = fallback_reply(refs, exc.code)
        return fallback_stream(fb) if fb else error(exc.code, exc.message, exc.status)
    started = time.monotonic()
    response = None
    for attempt in range(3):
        try:
            response = chat.open_stream(chat.stream_url(), chat.build_payload(message, history, req.context,
                                                                         ingredients_explain.reference_block(refs)), key)
            if hasattr(response, "__enter__"):
                response = response.__enter__()
            iterator = iter(response)
            first = ""
            for line in iterator:
                first = chat.stream_text(line)
                if first:
                    break
            if not first:
                raise chat.ChatError("CHAT_EMPTY_REPLY", "The chatbot could not answer that question. Try rephrasing it.", 502)
            break
        except urllib.error.HTTPError as exc:
            close = getattr(response, "close", None)
            if close:
                close()
            if attempt < 2 and exc.code in (500, 502, 503, 504):
                time.sleep(min(0.5 * (2 ** attempt), 2.5))
                continue
            mapped = chat._provider_error(exc, key)
            if mapped.diagnostic:
                log.warning("chat error %s: %s", mapped.code, mapped.diagnostic)
            else:
                log.warning("chat error %s", mapped.code)
            fb = fallback_reply(refs, mapped.code)
            return fallback_stream(fb) if fb else error(mapped.code, mapped.message, mapped.status)
        except chat.ChatError as exc:
            fb = fallback_reply(refs, exc.code)
            return fallback_stream(fb) if fb else error(exc.code, exc.message, exc.status)
        except (urllib.error.URLError, TimeoutError, OSError):
            close = getattr(response, "close", None)
            if close:
                close()
            if attempt < 2:
                time.sleep(min(0.5 * (2 ** attempt), 2.5))
                continue
            fb = fallback_reply(refs, "CHAT_UNAVAILABLE")
            return fallback_stream(fb) if fb else error(
                "CHAT_UNAVAILABLE", "The chatbot service could not be reached. Check the internet connection and try again.", 502)

    def events():
        answer = first
        try:
            yield f"event: chunk\ndata: {json.dumps({'text': first})}\n\n"
            for line in iterator:
                piece = chat.stream_text(line)
                if piece:
                    answer += piece
                    yield f"event: chunk\ndata: {json.dumps({'text': piece})}\n\n"
            elapsed = round((time.monotonic() - started) * 1000)
            chat.cache_answer(message, history, req.context, answer)
            yield f"event: done\ndata: {json.dumps({'latency_ms': elapsed, 'first_chunk_ms': elapsed, 'cached': False})}\n\n"
        except (urllib.error.URLError, TimeoutError, OSError):
            yield f"event: error\ndata: {json.dumps({'error_code': 'CHAT_UNAVAILABLE', 'message': 'The chatbot connection was interrupted.'})}\n\n"
        finally:
            close = getattr(response, "close", None)
            if close:
                close()

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

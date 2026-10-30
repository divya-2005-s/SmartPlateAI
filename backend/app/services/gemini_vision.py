"""Google Gemini image-based food identification: the fallback when OpenAI Vision cannot be used (for example an
account with no remaining credit). It sends the same prompt, asks for the same structured fields and applies the same
validation as app.services.openai_vision, so routing, nutrition and freshness behave identically whichever provider
answered. Requests stay on the backend; the key (GEMINI_API_KEY / GOOGLE_API_KEY) is sent in a header, never in a URL,
and is never logged. Like OpenAI, Gemini returns no calibrated confidence, and none is requested or invented.
"""
from __future__ import annotations

import base64
import json
import socket
import urllib.error
import urllib.request
from types import SimpleNamespace

from PIL import Image

from app.core.config import get_settings
from app.services import chat
from app.services.openai_vision import (FOOD_SCHEMA, PACKAGE_PROMPT, PACKAGE_SCHEMA, PROMPT, OpenAIVisionError, _jpeg, _jpeg_label,
                                         _parse_output, parse_package)

PROVIDER = "Google Gemini"
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def availability() -> str:
    settings = get_settings()
    if not settings.gemini_vision_enabled:
        return "disabled"
    if not chat.api_key():
        return "not_configured"
    return "ready"


def _schema() -> dict:
    """FOOD_SCHEMA without a null inside 'enum' (nullability is already expressed by the type list)."""
    schema = json.loads(json.dumps(FOOD_SCHEMA))
    schema["properties"]["category"]["enum"] = [c for c in schema["properties"]["category"]["enum"] if c is not None]
    return schema


def post(url: str, payload: dict, key: str, timeout: float) -> dict:  # separated so tests can replace the network call
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _call(model: str, payload: dict, timeout: float) -> dict:
    try:
        return post(API_URL.format(model=model), payload, chat.api_key(), timeout)
    except urllib.error.HTTPError as exc:
        raise OpenAIVisionError({429: "rate_limited", 401: "authentication_failed", 403: "authentication_failed",
                                 404: "model_unavailable", 503: "provider_busy"}.get(exc.code, "provider_error")) from None
    except (socket.timeout, TimeoutError):
        raise OpenAIVisionError("timeout") from None
    except (urllib.error.URLError, ConnectionError, OSError):
        raise OpenAIVisionError("network_error") from None
    except (json.JSONDecodeError, ValueError):
        raise OpenAIVisionError("invalid_response") from None


def identify(img: Image.Image, class_names: list[str]) -> dict:
    """Same result shape as openai_vision.identify, plus provider='Google Gemini'. Raises OpenAIVisionError(code)."""
    state = availability()
    if state != "ready":
        raise OpenAIVisionError(state)
    payload = {
        "contents": [{"role": "user", "parts": [
            {"text": PROMPT.format(classes=json.dumps(class_names, ensure_ascii=True))},
            {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(_jpeg(img)).decode("ascii")}},
        ]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseJsonSchema": _schema()},
    }
    return {**_parse_output(SimpleNamespace(output_text=_generate(payload)), class_names), "provider": PROVIDER}


def _generate(payload: dict) -> str:
    """Run the request on the configured models in order; returns the response text. Raises OpenAIVisionError(code)."""
    settings = get_settings()
    models = [m.strip() for m in settings.gemini_vision_model.split(",") if m.strip()]
    if not models:
        raise OpenAIVisionError("not_configured")
    for i, model in enumerate(models):
        try:
            data = _call(model, payload, settings.gemini_vision_timeout_s)
            break
        except OpenAIVisionError as exc:
            # Only an overloaded or retired model moves on to the next one; every other failure is reported as is.
            if exc.code not in ("provider_busy", "model_unavailable") or i == len(models) - 1:
                raise
    try:
        return chat._extract_text(data)
    except Exception:  # noqa: BLE001  (blocked or empty candidate)
        raise OpenAIVisionError("invalid_response") from None


def read_package(front: Image.Image | None, back: Image.Image | None) -> dict:
    """Package-label reading with the same prompt, schema and validation as openai_vision.read_package (values that fail
    validation are dropped, never repaired); the fallback when OpenAI gives no answer. Raises OpenAIVisionError(code)."""
    state = availability()
    if state != "ready":
        raise OpenAIVisionError(state)
    parts, labels = [], []
    for role, img in (("FRONT", front), ("BACK", back)):
        if img is not None:
            labels.append(f"Image {len(labels) + 1} is the {role} of the package.")
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(_jpeg_label(img)).decode("ascii")}})
    if not parts:
        raise OpenAIVisionError("invalid_request")
    missing = [r for r, i in (("FRONT", front), ("BACK", back)) if i is None]
    note = " ".join(labels) + (f" No {missing[0]} image was provided." if missing else "")
    payload = {
        "contents": [{"role": "user", "parts": [{"text": PACKAGE_PROMPT.format(images=note)}, *parts]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseJsonSchema": PACKAGE_SCHEMA},
    }
    return {**parse_package(SimpleNamespace(output_text=_generate(payload))), "provider": PROVIDER}

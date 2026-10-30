"""Short-lived, server-side copies of analysis results.

Each analysis response carries an `analysis_id`. Saving to history sends only that id, so stored scans always contain
exactly what the server produced (the browser cannot inject fabricated nutrition or identities), and saving the same
analysis twice cannot create duplicates. Results expire after `TTL_S` or when the server restarts.
"""
from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict

TTL_S = 3 * 3600
MAX_ITEMS = 500

_items: OrderedDict[str, tuple[float, dict]] = OrderedDict()
_lock = threading.Lock()


def put(kind: str, result: dict) -> str:
    aid = secrets.token_urlsafe(12)
    with _lock:
        _items[aid] = (time.time(), {"kind": kind, "result": result})
        while len(_items) > MAX_ITEMS:
            _items.popitem(last=False)
    return aid


def get(aid: str) -> dict | None:
    with _lock:
        item = _items.get(aid)
        if not item:
            return None
        if time.time() - item[0] > TTL_S:
            _items.pop(aid, None)
            return None
        return item[1]


def clear() -> None:
    with _lock:
        _items.clear()

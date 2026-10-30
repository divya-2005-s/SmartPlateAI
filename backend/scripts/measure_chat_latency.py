"""Measure real Gemini chatbot latency through the running API (needs GEMINI_API_KEY and internet).

  .\\.venv\\Scripts\\python.exe scripts\\measure_chat_latency.py --runs 5
Reports time-to-first-chunk (streaming) and full-answer time (non-streaming), each with a fresh question so the
answer cache is not hit, plus one repeated question to show the cache effect. Writes reports/chat_latency.md.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from pathlib import Path

CTX = {"kind": "fresh", "title": "Apple", "status": "recognised by the image model with confidence 93.0%",
       "nutrition": {"source": "per 100 g (USDA FoodData Central reference record)",
                     "values": [{"nutrient": "Energy", "unit": "kcal", "per_100g": 52}, {"nutrient": "Total sugars", "unit": "g", "per_100g": 10.4}]}}


def post(url: str, body: dict, stream: bool) -> tuple[float, float]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.perf_counter()
    first = None
    with urllib.request.urlopen(req, timeout=90) as r:
        if stream:
            for line in r:
                if first is None and line.startswith(b"data:"):
                    first = time.perf_counter() - t0
        else:
            r.read()
    total = time.perf_counter() - t0
    return (first if first is not None else total), total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--runs", type=int, default=5)
    a = ap.parse_args()
    status = json.loads(urllib.request.urlopen(f"{a.base}/api/chat/status?check=true", timeout=30).read())
    print("status:", status)
    if not status.get("configured"):
        raise SystemExit("GEMINI_API_KEY is not configured on the server.")
    first_s, full_s, normal_s = [], [], []
    for i in range(a.runs):
        f, t = post(f"{a.base}/api/chat/stream", {"message": f"In one sentence, is this a good snack? (run {time.time()}-{i})", "context": CTX}, True)
        first_s.append(f); full_s.append(t)
        _, n = post(f"{a.base}/api/chat", {"message": f"List two nutrients shown, briefly. (run {time.time()}-{i})", "context": CTX}, False)
        normal_s.append(n)
        print(f"run {i + 1}: stream first chunk {f:.2f}s, stream total {t:.2f}s, non-stream total {n:.2f}s")
    q = {"message": "How many kcal per 100 g?", "context": CTX}
    post(f"{a.base}/api/chat", q, False)
    _, cached = post(f"{a.base}/api/chat", q, False)
    med = statistics.median
    lines = ["# Chatbot latency (measured)", "", f"Model: {status.get('model')} | runs: {a.runs}", "",
             f"- Streaming, time to first text: median {med(first_s):.2f} s (min {min(first_s):.2f}, max {max(first_s):.2f})",
             f"- Streaming, full answer: median {med(full_s):.2f} s",
             f"- Non-streaming, full answer: median {med(normal_s):.2f} s",
             f"- Repeated identical question (answer cache): {cached:.3f} s", ""]
    out = Path(__file__).resolve().parents[1] / "reports" / "chat_latency.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

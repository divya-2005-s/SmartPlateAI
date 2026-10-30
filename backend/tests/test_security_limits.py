"""Release-blocker security controls: sign-in for paid providers, per-account / per-IP rate limits, daily provider caps,
request-size limits and the bound on parallel analyses.

Every provider (OpenAI, Gemini, Google Vision, the chatbot) is MOCKED and counted: no network or paid calls. Counters live in
a throw-away SQLite file per test. The controls are switched on per test exactly as production switches them on."""
import io
import secrets
import threading

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api import limits
from app.api.routes import analyze
from app.api.routes import packaged as packaged_route
from app.core.config import get_settings
from app.main import app
from app.ml.rejection import Thresholds
from app.services import chat, gemini_vision, openai_vision, usage_limits as ul, vision
from tests.test_recognition_packaged_history_fixes import pk, post_pk  # noqa: F401  (fixture)

S = get_settings()
FLOOR = 0.0298


class Rec:
    """Fake recognizer: a confident, clearly-food 'Apple' (no TensorFlow). `calls` counts analyses."""
    class_names = ["Apple", "Donut", "Fries", "Sandwich"]
    thresholds = Thresholds(food_mass_low=FLOOR, maha_high=2477.0, conf_min=0.574, margin_min=0.244)
    ready, status_message = True, "ready"

    def __init__(self):
        self.calls = 0

    def load(self):
        return True

    def analyze_image(self, img):
        self.calls += 1
        top = [{"class_id": 0, "food": "Apple", "score": 0.97}, *[{"class_id": i, "food": c, "score": 0.01}
                                                                  for i, c in enumerate(self.class_names[1:], 1)]]
        return {"decision": "accept", "reason": None, "calibrated": True, "confidence": 0.97, "margin": 0.96, "top_k": top,
                "features": None, "freshness": {"status": "fresh", "confidence": 0.9}, "packaged_product": False,
                "signals": {"imagenet_food_mass": 0.6, "feature_distance": 900.0, "imagenet_group": "food"}}


def png(color=(200, 40, 40), size=64) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (size, size), color).save(b, "PNG")
    return b.getvalue()


@pytest.fixture(autouse=True)
def counters(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "usage_database_path", str(tmp_path / "usage.db"))
    chat.clear_cache()
    yield tmp_path / "usage.db"
    chat.clear_cache()


@pytest.fixture
def production(monkeypatch):
    """The two switches as ENVIRONMENT=production sets them ("auto")."""
    monkeypatch.setattr(S, "environment", "production")
    monkeypatch.setattr(S, "rate_limits_enabled", "auto")
    monkeypatch.setattr(S, "paid_providers_require_login", "auto")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")  # TestClient speaks plain HTTP; only affects the cookie flag  # noqa
    yield monkeypatch


@pytest.fixture
def food(monkeypatch):
    rec = Rec()
    calls = {"openai": 0, "vision": 0}

    def fake_openai(img, names):
        calls["openai"] += 1
        return {"status": "recognized", "food_name": "apple", "named_as": "apple", "supported_food": "Apple", "visible_evidence": [],
                "uncertainty": None, "category": None, "provider": "OpenAI Vision"}

    def fake_vision(img, predicted, names):
        calls["vision"] += 1
        return None

    app.dependency_overrides[analyze.get_recognizer] = lambda: rec
    monkeypatch.setattr(analyze, "run_openai_vision", fake_openai)
    monkeypatch.setattr(analyze, "run_vision", fake_vision)
    yield rec, calls
    app.dependency_overrides.clear()


def client(ip="203.0.113.7") -> TestClient:
    return TestClient(app, client=(ip, 50000))


def sign_up(c: TestClient) -> dict:
    r = c.post("/api/auth/signup", json={"name": "Test User", "email": f"u{secrets.token_hex(4)}@example.com",
                                         "password": "long enough password"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def analyse(c: TestClient, headers=None):
    return c.post("/api/analyze/food", files={"file": ("p.png", png(), "image/png")}, headers=headers or {})


# ------------------------------------------------------------------ switches
def test_switches_are_on_in_production_and_off_in_development(monkeypatch):
    monkeypatch.setattr(S, "rate_limits_enabled", "auto")
    monkeypatch.setattr(S, "paid_providers_require_login", "auto")
    monkeypatch.setattr(S, "environment", "development")
    assert not ul.rate_limits_enabled() and not ul.paid_requires_login() and ul.paid_allowed(None)
    monkeypatch.setattr(S, "environment", "production")
    assert ul.rate_limits_enabled() and ul.paid_requires_login() and not ul.paid_allowed(None) and ul.paid_allowed(object())


@pytest.mark.parametrize("value, expected", [("true", True), ("false", False), ("off", False), ("maybe", True), ("", False)])
def test_explicit_switch_values_and_unknown_values_fail_safe(monkeypatch, value, expected):
    monkeypatch.setattr(S, "environment", "development")
    monkeypatch.setattr(S, "rate_limits_enabled", value)
    assert ul.rate_limits_enabled() is expected


# ------------------------------------------------------------------ counter store
def test_counter_blocks_at_the_limit_and_resets_with_the_next_window():
    rule = [("b", 2, 3600)]
    t = 7200 * 1000 + 10
    assert ul.consume(rule, now=t) is None and ul.consume(rule, now=t) is None
    assert ul.consume(rule, now=t) == 3600 - 10  # seconds until the window ends
    assert ul.consume(rule, now=t + 3600) is None


def test_a_blocked_request_counts_against_no_rule():
    t = 86400 * 500
    assert ul.consume([("day", 1, 86400)], now=t) is None
    assert ul.consume([("hour", 5, 3600), ("day", 1, 86400)], now=t) is not None
    assert ul.used("hour", 3600, now=t) == 0


def test_client_addresses_are_stored_only_as_salted_hashes(counters):
    k = ul.client_key("203.0.113.7")
    assert "203" not in k and k == ul.client_key("203.0.113.7") and k != ul.client_key("203.0.113.8")
    assert ul.client_key("::ffff:203.0.113.7") == k
    assert ul.client_key("2001:db8:1:2::1") == ul.client_key("2001:db8:1:2:ffff::9")  # same /64
    assert ul.client_key("2001:db8:1:2::1") != ul.client_key("2001:db8:1:3::1")
    ul.consume([(f"analysis:ip:{k}", 5, 3600)])
    assert b"203.0.113.7" not in counters.read_bytes()


# ------------------------------------------------------------------ paid providers need sign-in (production)
def test_anonymous_analysis_uses_the_image_model_only(production, food):
    rec, calls = food
    r = analyse(client())
    assert r.status_code == 200, r.text
    j = r.json()
    assert calls == {"openai": 0, "vision": 0} and rec.calls == 1
    assert j["success"] and j["prediction"]["food"] == "Apple" and j.get("nutrition") is not None  # same answer as with providers off
    assert j["recognition"]["message"] == analyze.MSG_LOGIN_FOR_AI


def test_signed_in_analysis_still_uses_the_providers(production, food):
    rec, calls = food
    c = client()
    r = analyse(c, sign_up(c))
    assert r.status_code == 200 and calls["openai"] == 1 and calls["vision"] == 1
    assert r.json()["recognition"]["status"] == "verified_both"


def test_development_keeps_providers_for_anonymous_users(food, monkeypatch):
    monkeypatch.setattr(S, "environment", "development")
    _, calls = food
    assert analyse(client()).status_code == 200 and calls["openai"] == 1


def test_anonymous_packaged_scan_skips_ai_label_reading(production, pk):  # noqa: F811
    called = []
    pk.setattr(packaged_route, "run_package_reading", lambda f, b: called.append(1) or {"status": "unavailable", "reason": "disabled"})
    j = post_pk(client()).json()
    assert j["success"] and called == []
    assert any("Sign in to add AI reading" in w for w in j["warnings"])


def test_anonymous_chat_is_refused_before_any_gemini_call(production, monkeypatch):
    sent = []
    monkeypatch.setattr(chat, "api_key", lambda: "k")
    monkeypatch.setattr(chat, "post_json", lambda *a: sent.append(1))
    monkeypatch.setattr(chat, "open_stream", lambda *a: sent.append(1))
    c = client()
    for path in ("/api/chat", "/api/chat/stream"):
        r = c.post(path, json={"message": "hi"})
        assert r.status_code == 401 and r.json()["error_code"] == "NOT_AUTHENTICATED"
    assert sent == []
    st = c.get("/api/chat/status").json()
    assert st["requires_login"] is True and st["signed_in"] is False


def test_signed_in_chat_works_and_is_rate_limited(production, monkeypatch):
    monkeypatch.setattr(S, "rate_limit_chat_per_hour", 2)
    monkeypatch.setattr(chat, "api_key", lambda: "k")
    monkeypatch.setattr(chat, "post_json", lambda url, payload, key: {"candidates": [{"content": {"parts": [{"text": "Hello."}]}}]})
    c = client()
    h = sign_up(c)
    assert c.get("/api/chat/status", headers=h).json()["signed_in"] is True
    assert [c.post("/api/chat", json={"message": f"q{i}"}, headers=h).status_code for i in range(3)] == [200, 200, 429]


# ------------------------------------------------------------------ rate limits
def test_anonymous_analyses_are_limited_per_ip_with_retry_after(production, food, monkeypatch):
    monkeypatch.setattr(S, "rate_limit_anon_analyses_per_hour", 2)
    rec, _ = food
    c = client()
    codes = [analyse(c).status_code for _ in range(2)]
    r = analyse(c)
    assert codes == [200, 200] and r.status_code == 429
    j = r.json()
    assert j["error_code"] == "RATE_LIMITED" and "Signed-in accounts have a higher limit" in j["message"]
    assert 1 <= int(r.headers["Retry-After"]) <= 3600 and j["retry_after_s"] == int(r.headers["Retry-After"])
    assert rec.calls == 2  # the refused photo never reached the model
    assert analyse(client("198.51.100.4")).status_code == 200  # another address has its own allowance


def test_a_signed_in_account_has_its_own_hourly_and_daily_limits(production, food, monkeypatch):
    monkeypatch.setattr(S, "rate_limit_anon_analyses_per_hour", 0)  # the shared address is exhausted for anonymous use
    monkeypatch.setattr(S, "rate_limit_user_analyses_per_hour", 2)
    c = client()
    h = sign_up(c)
    assert analyse(c).status_code == 429
    assert [analyse(c, h).status_code for _ in range(3)] == [200, 200, 429]
    monkeypatch.setattr(S, "rate_limit_user_analyses_per_hour", 100)
    monkeypatch.setattr(S, "rate_limit_user_analyses_per_day", 2)
    assert analyse(c, h).status_code == 429  # the day already has two


def test_signups_and_sign_ins_are_limited_per_ip(production, monkeypatch):
    monkeypatch.setattr(S, "rate_limit_signups_per_hour", 2)
    monkeypatch.setattr(S, "rate_limit_logins_per_hour", 2)
    c = client()
    sign_up(c), sign_up(c)
    r = c.post("/api/auth/signup", json={"name": "Third", "email": "third@example.com", "password": "long enough password"})
    assert r.status_code == 429 and "Retry-After" in r.headers
    login = [c.post("/api/auth/login", json={"email": "x@example.com", "password": "wrong password"}).status_code for _ in range(3)]
    assert login == [401, 401, 429]


def test_external_product_search_is_limited_but_the_local_search_is_not(production, monkeypatch):
    monkeypatch.setattr(S, "rate_limit_lookups_per_hour", 1)
    c = client()
    assert c.get("/api/packaged/search", params={"q": "oats", "external": "true"}).status_code == 200
    assert c.get("/api/packaged/search", params={"q": "oats", "external": "true"}).status_code == 429
    assert c.get("/api/packaged/search", params={"q": "oats"}).status_code != 429


def test_rate_limits_are_off_in_development(food, monkeypatch):
    monkeypatch.setattr(S, "environment", "development")
    monkeypatch.setattr(S, "rate_limit_anon_analyses_per_hour", 0)
    assert analyse(client()).status_code == 200


def test_a_failing_counter_store_does_not_block_ordinary_requests(production, food, monkeypatch):
    def broken(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(ul, "consume", broken)
    assert analyse(client()).status_code == 200


# ------------------------------------------------------------------ daily provider caps
def test_openai_and_gemini_stop_at_their_daily_caps(monkeypatch):
    sent = {"openai": 0, "gemini": 0}
    monkeypatch.setattr(S, "openai_daily_limit", 2)
    monkeypatch.setattr(S, "gemini_daily_limit", 1)
    monkeypatch.setattr(openai_vision, "availability", lambda: "ready")
    monkeypatch.setattr(gemini_vision, "availability", lambda: "ready")
    answer = {"status": "recognized", "food_name": "apple", "supported_food": "Apple"}
    monkeypatch.setattr(openai_vision, "identify", lambda img, n: sent.__setitem__("openai", sent["openai"] + 1) or dict(answer))
    monkeypatch.setattr(gemini_vision, "identify", lambda img, n: sent.__setitem__("gemini", sent["gemini"] + 1) or dict(answer))
    img = Image.new("RGB", (8, 8))
    results = [analyze.run_openai_vision(img, ["Apple"]) for _ in range(4)]
    assert [r.get("provider") for r in results[:3]] == ["OpenAI Vision", "OpenAI Vision", "Google Gemini"]
    assert results[3]["status"] == "unavailable" and results[3]["reason"] == ul.DAILY_LIMIT_REACHED
    assert results[3]["fallback"]["reason"] == ul.DAILY_LIMIT_REACHED
    assert sent == {"openai": 2, "gemini": 1}


def test_capped_providers_fall_back_to_the_image_model_and_say_so(monkeypatch):
    rec = Rec()
    app.dependency_overrides[analyze.get_recognizer] = lambda: rec
    try:
        monkeypatch.setattr(S, "openai_daily_limit", 0)
        monkeypatch.setattr(S, "gemini_daily_limit", 0)
        monkeypatch.setattr(openai_vision, "availability", lambda: "ready")
        monkeypatch.setattr(gemini_vision, "availability", lambda: "ready")
        monkeypatch.setattr(openai_vision, "identify", lambda *a: pytest.fail("OpenAI called past its cap"))
        monkeypatch.setattr(gemini_vision, "identify", lambda *a: pytest.fail("Gemini called past its cap"))
        monkeypatch.setattr(analyze, "run_vision", lambda *a: None)
        j = analyse(client()).json()
        assert j["prediction"]["food"] == "Apple" and j["recognition"]["message"] == analyze.MSG_DAILY_LIMIT  # 97%: the 70% rule accepts
    finally:
        app.dependency_overrides.clear()


def test_package_reading_respects_the_cap(monkeypatch):
    monkeypatch.setattr(S, "openai_daily_limit", 0)
    monkeypatch.setattr(openai_vision, "availability", lambda: "ready")
    monkeypatch.setattr(openai_vision, "read_package", lambda f, b: pytest.fail("OpenAI called past its cap"))
    monkeypatch.setattr(gemini_vision, "availability", lambda: "disabled")
    r = packaged_route.run_package_reading(Image.new("RGB", (8, 8)), None)
    assert r["status"] == "unavailable" and r["reason"] == ul.DAILY_LIMIT_REACHED


def test_google_vision_cap_counts_only_real_requests(monkeypatch):
    sent = []
    monkeypatch.setattr(S, "google_vision_daily_limit", 1)
    monkeypatch.setattr(vision, "enabled", lambda: True)
    monkeypatch.setattr(vision, "cache_get", lambda key: None)
    monkeypatch.setattr(vision, "cache_set", lambda *a: None)
    monkeypatch.setattr(vision, "request_json", lambda *a, **k: sent.append(1) or {"responses": [{"labelAnnotations": []}]})
    vision.annotate(Image.new("RGB", (8, 8)))
    with pytest.raises(vision.VisionUnavailable):
        vision.annotate(Image.new("RGB", (8, 8)))
    assert sent == [1]
    monkeypatch.setattr(vision, "cache_get", lambda key: {"labels": [], "objects": []})
    assert vision.annotate(Image.new("RGB", (8, 8)))["cached"] is True  # a cached answer costs nothing and is still served


def test_chat_and_meal_planner_share_the_gemini_text_cap(monkeypatch):
    sent = []
    monkeypatch.setattr(S, "chat_daily_limit", 1)
    monkeypatch.setattr(chat, "api_key", lambda: "k")
    monkeypatch.setattr(chat, "post_json", lambda *a: sent.append(1) or {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})
    monkeypatch.setattr(chat, "open_stream", lambda *a: pytest.fail("stream opened past the cap"))
    c = client()
    assert c.post("/api/chat", json={"message": "first"}).status_code == 200
    assert c.post("/api/chat", json={"message": "first"}).json()["cached"] is True  # cached: not counted
    for path in ("/api/chat", "/api/chat/stream"):
        r = c.post(path, json={"message": "second"})
        assert r.status_code == 503 and r.json()["error_code"] == "CHAT_DAILY_LIMIT"
    with pytest.raises(chat.ChatError) as exc:
        chat.generate({"contents": []})  # meal planner path
    assert exc.value.code == "CHAT_DAILY_LIMIT" and sent == [1]


def test_paid_calls_fail_closed_when_the_counter_store_fails(monkeypatch):
    def broken(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(ul, "consume", broken)
    assert ul.provider_call_allowed("openai") is False


# ------------------------------------------------------------------ request size and load
def test_oversized_multipart_body_is_refused_before_parsing(food, monkeypatch):
    monkeypatch.setattr(S, "max_request_mb", 0.01)  # ~10 KB
    rec, _ = food
    r = client().post("/api/analyze/food", files={"file": ("p.bmp", b"\0" * 20000, "image/bmp")})
    assert r.status_code == 413 and r.json()["error_code"] == "REQUEST_TOO_LARGE" and rec.calls == 0


def test_oversized_json_body_is_refused(monkeypatch):
    monkeypatch.setattr(S, "max_json_kb", 4)
    r = client().post("/api/chat", json={"message": "x", "context": {"blob": "y" * 8000}})
    assert r.status_code == 413 and r.json()["error_code"] == "REQUEST_TOO_LARGE"


def test_a_body_without_length_is_refused():
    r = client().post("/api/chat", content=iter([b'{"message": "hi"}']), headers={"Content-Type": "application/json"})
    assert r.status_code == 411 and r.json()["error_code"] == "LENGTH_REQUIRED"


def test_normal_requests_pass_the_size_limit(food):
    assert analyse(client()).status_code == 200 and client().get("/health").status_code == 200


def test_parallel_analyses_are_bounded(food, monkeypatch):
    monkeypatch.setattr(S, "max_concurrent_analyses", 1)
    monkeypatch.setattr(S, "analysis_queue_timeout_s", 0.2)
    slots = limits._semaphore()
    assert slots.acquire(timeout=1)  # another analysis is running
    try:
        r = analyse(client())
        assert r.status_code == 503 and r.json()["error_code"] == "SERVER_BUSY" and r.headers["Retry-After"] == "30"
    finally:
        slots.release()
    assert analyse(client()).status_code == 200  # the slot is free again (and released after each request)
    assert analyse(client()).status_code == 200


def test_waiting_analyses_proceed_when_a_slot_frees(food, monkeypatch):
    monkeypatch.setattr(S, "max_concurrent_analyses", 1)
    monkeypatch.setattr(S, "analysis_queue_timeout_s", 5)
    slots = limits._semaphore()
    slots.acquire()
    threading.Timer(0.3, slots.release).start()
    assert analyse(client()).status_code == 200

"""PubChem outcomes are reported exactly (found, no match, timeout, busy/rate-limited, unreachable, certificate failure, unreadable
reply) and never filled in. All PubChem responses here are MOCKED; no network calls are made."""
import socket
import ssl
import urllib.error
from types import SimpleNamespace

import pytest

from app.services import chemistry, http

LYCOPENE = {"PropertyTable": {"Properties": [{"CID": 446925, "IUPACName": "(6E,8E,...)-lycopene", "MolecularFormula": "C40H56",
                                              "MolecularWeight": "536.9"}]}}


@pytest.fixture
def pc(monkeypatch):
    """Enable PubChem with an in-memory cache; `pc.reply` is what request_json returns or raises for every name."""
    cache = {}
    state = SimpleNamespace(reply=LYCOPENE, cache=cache, calls=0)
    monkeypatch.setattr(chemistry, "get_settings", lambda: SimpleNamespace(pubchem_enabled=True, http_timeout_s=8.0, usda_fdc_api_key=""))
    monkeypatch.setattr(chemistry, "cache_get", lambda k: cache.get(k))
    monkeypatch.setattr(chemistry, "cache_set", lambda k, v, ttl: cache.__setitem__(k, v))

    def reply(url, **kw):
        state.calls += 1
        r = state.reply(url) if callable(state.reply) else state.reply
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(chemistry, "request_json", reply)
    return state


def test_found_is_cached_and_shown_with_its_source(pc):
    r = chemistry.pubchem("lycopene")
    assert r["status"] == "found" and r["formula"] == "C40H56" and r["cid"] == 446925 and r["url"].endswith("/446925")
    assert pc.cache and chemistry.pubchem("lycopene") == r and pc.calls == 1
    prof = chemistry.chemical_profile("Tomato", None)
    assert prof["pubchem"]["status"] == "ok" and prof["pubchem"]["message"] is None
    row = prof["compounds"][0]
    assert row["record_sources"]["identity"] == "PubChem CID 446925" and "curated" in row["record_sources"]["association"]


def test_no_match_is_a_real_answer_not_an_error(pc):
    pc.reply = http.ExternalError("NOT_FOUND", "x", 404)
    assert chemistry.pubchem("no-such-compound")["status"] == "not_found" and pc.cache  # cached: PubChem answered
    s = chemistry.chemical_profile("Tomato", None)["pubchem"]
    assert s["status"] == "no_match" and "no records" in s["message"]


@pytest.mark.parametrize("err,status,words", [
    (http.ExternalError("TIMEOUT", "x"), "timeout", "did not answer in time"),
    (http.ExternalError("RATE_LIMITED", "x", 429), "rate_limited", "limiting requests"),
    (http.ExternalError("BAD_RESPONSE", "x", 503), "rate_limited", "busy"),
    (http.ExternalError("UNREACHABLE", "x", cause="connection"), "unavailable", "could not be reached"),
    (http.ExternalError("UNREACHABLE", "x", cause="tls_certificate"), "unavailable", "secure connection to PubChem could not be verified"),
    (http.ExternalError("BAD_RESPONSE", "x", 400), "invalid_query", "rejected the compound name"),
])
def test_each_failure_is_named_and_never_cached_or_filled(pc, err, status, words):
    pc.reply = err
    assert chemistry.pubchem("lycopene")["status"] == status and not pc.cache  # retried next time
    prof = chemistry.chemical_profile("Tomato", None)
    assert prof["pubchem"]["status"] == status and words in prof["pubchem"]["message"]
    assert "all compounds" in prof["pubchem"]["message"]
    assert all(c["formula"] is None and c["chemical_name"] is None and c["pubchem_url"] is None for c in prof["compounds"])
    assert prof["pubchem_reachable"] is False


@pytest.mark.parametrize("reply", [{"unexpected": True}, {"PropertyTable": {"Properties": []}},
                                   {"PropertyTable": {"Properties": [{"CID": 5, "IUPACName": "x"}]}}],
                         ids=["wrong_shape", "empty", "no_formula"])
def test_unreadable_or_incomplete_reply_is_invalid_not_no_match(pc, reply):
    pc.reply = reply
    r = chemistry.pubchem("lycopene")
    assert r["status"] == "invalid_response" and not pc.cache  # previously cached as "not_found" for 30 days
    assert "could not be read" in chemistry.chemical_profile("Tomato", None)["pubchem"]["message"]


def test_partial_failure_keeps_the_successful_records(pc):
    pc.reply = lambda url: http.ExternalError("TIMEOUT", "x") if "citric" in url else LYCOPENE
    prof = chemistry.chemical_profile("Tomato", None)
    s = prof["pubchem"]
    assert s["status"] == "partial" and s["failed"] == 1 and s["found"] == s["total"] - 1
    assert f"1 of the {s['total']} compounds" in s["message"]
    by = {c["common_name"]: c for c in prof["compounds"]}
    assert by["Citric acid"]["formula"] is None and by["Citric acid"]["pubchem_status"] == "timeout"
    assert by["Lycopene"]["formula"] == "C40H56"
    assert prof["pubchem_reachable"] is True


def test_food_without_curated_compounds_says_so(pc):
    prof = chemistry.chemical_profile("Idli", None)
    assert prof["status"] == "no_curated_compounds" and prof["pubchem"]["status"] == "not_applicable" and pc.calls == 0


def test_disabled_is_reported_as_switched_off():
    prof = chemistry.chemical_profile("Tomato", None)  # PubChem is disabled in tests via conftest
    assert prof["pubchem"]["status"] == "disabled" and "switched off" in prof["pubchem"]["message"]


# ------------------------------------------------------------------ the HTTP helper's classification of real exceptions
@pytest.mark.parametrize("reason,cause", [
    (ssl.SSLCertVerificationError(1, "certificate verify failed: self-signed certificate in certificate chain"), "tls_certificate"),
    (socket.gaierror(11001, "getaddrinfo failed"), "dns"),
    (ConnectionRefusedError(10061, "refused"), "connection"),
])
def test_http_helper_says_why_a_connection_failed(monkeypatch, reason, cause):
    def fail(*a, **kw):
        raise urllib.error.URLError(reason)
    monkeypatch.setattr(http.urllib.request, "urlopen", fail)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    with pytest.raises(http.ExternalError) as e:
        http.request_json("https://pubchem.example/x", timeout=1, retries=1)
    assert e.value.code == "UNREACHABLE" and e.value.cause == cause


def test_http_helper_timeout_stays_timeout(monkeypatch):
    def slow(*a, **kw):
        raise urllib.error.URLError(socket.timeout("timed out"))
    monkeypatch.setattr(http.urllib.request, "urlopen", slow)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    with pytest.raises(http.ExternalError) as e:
        http.request_json("https://pubchem.example/x", timeout=1, retries=0)
    assert e.value.code == "TIMEOUT"

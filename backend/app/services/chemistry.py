"""Chemical Intelligence for recognised unpackaged foods.

Sources, in order of authority:
  1. USDA FoodData Central record for the food (from the project's nutrition CSV and, if USDA_FDC_API_KEY is set,
     the live FDC API) -> the ONLY source of amounts, always "per 100 g of a reference sample".
  2. PubChem PUG REST -> identity of each compound (IUPAC name, formula, weight, CID link). No amounts.
  3. The curated mapping in app/data/food_compounds.py -> which compounds are notable for a food and their role.
This is reference composition, not a measurement of the photographed item. A camera cannot measure chemicals,
pesticide residues, toxins, heavy metals or adulteration.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from app.core.config import get_settings
from app.data.food_compounds import compounds_for
from app.services.http import ExternalError, cache_get, cache_key, cache_set, request_json

log = logging.getLogger("smartplate.chemistry")
PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}/property/IUPACName,MolecularFormula,MolecularWeight/JSON"
FDC_API = "https://api.nal.usda.gov/fdc/v1/food/{fdc_id}"
PUBCHEM_TTL = 30 * 24 * 3600
FDC_TTL = 30 * 24 * 3600
LIMITATIONS = [
    "Reference composition from public databases, not a laboratory measurement of the food in your photo.",
    "Amounts are shown only when a USDA FoodData Central record provides them, per 100 g of the reference sample; real amounts vary "
    "with variety, ripeness, storage and cooking.",
    "A compound being listed does not mean your sample contains it at a particular level.",
    "Image analysis cannot detect pesticide residues, toxins, heavy metals, microbes or adulteration.",
]


FAILED = ("timeout", "rate_limited", "unavailable", "invalid_response", "invalid_query")


def pubchem(name: str) -> dict:
    """One compound identity from PubChem. Statuses: found | not_found (PubChem answered: no such name) | disabled |
    timeout | rate_limited | unavailable (network, certificate or server error) | invalid_response (unreadable reply) |
    invalid_query (PubChem rejected the name). Only real answers (found / not_found) are cached; failures are retried later."""
    if not get_settings().pubchem_enabled:
        return {"status": "disabled"}
    key = cache_key("pubchem-v1", name.lower())
    cached = cache_get(key)
    if cached is not None:
        return cached
    try:
        data = request_json(PUBCHEM.format(name=urllib.parse.quote(name)), timeout=min(6.0, get_settings().http_timeout_s), retries=1)
    except ExternalError as exc:
        if exc.code == "NOT_FOUND":
            res = {"status": "not_found"}
            cache_set(key, res, PUBCHEM_TTL)
            return res
        if exc.code == "TIMEOUT":
            return {"status": "timeout", "reason": "timeout"}
        if exc.code == "RATE_LIMITED" or exc.status == 503:  # PubChem answers 503 "server busy" when throttling
            return {"status": "rate_limited", "reason": "rate_limited" if exc.code == "RATE_LIMITED" else "server_busy"}
        if exc.status == 400:
            return {"status": "invalid_query", "reason": "bad_request"}
        return {"status": "unavailable", "reason": exc.cause or (f"http_{exc.status}" if exc.status else exc.code.lower())}
    try:
        p = data["PropertyTable"]["Properties"][0]
        cid = int(p["CID"])
        res = {"status": "found", "cid": cid, "iupac_name": p.get("IUPACName"), "formula": p.get("MolecularFormula"),
               "molecular_weight": float(p["MolecularWeight"]) if p.get("MolecularWeight") else None,
               "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"}
    except (KeyError, IndexError, TypeError, ValueError):
        return {"status": "invalid_response", "reason": "unexpected_format"}  # not cached: never turned into "no match"
    if not res["formula"]:
        return {"status": "invalid_response", "reason": "incomplete_record"}
    cache_set(key, res, PUBCHEM_TTL)
    return res


def pubchem_summary(results: list[dict]) -> dict:
    """What the page should say about PubChem for this food: nothing when every lookup succeeded, otherwise exactly what failed."""
    total = len(results)
    if total == 0:
        return {"status": "not_applicable", "message": None, "total": 0, "found": 0, "not_found": 0, "failed": 0}
    count = {s: sum(r.get("status") == s for r in results) for s in ("found", "not_found", "disabled", *FAILED)}
    failed = sum(count[s] for s in FAILED)
    base = {"total": total, "found": count["found"], "not_found": count["not_found"], "failed": failed}
    if count["disabled"] == total:
        return {**base, "status": "disabled", "message": "PubChem lookups are switched off on this server, so chemical names and formulas are not shown."}
    if failed == 0:
        if count["found"]:
            msg = None if count["not_found"] == 0 else f"PubChem has no record matching {count['not_found']} of the {total} compound names."
            return {**base, "status": "ok", "message": msg}
        return {**base, "status": "no_match", "message": "PubChem has no records matching these compound names."}
    kinds = [s for s in FAILED if count[s]]
    tls = any(r.get("reason") == "tls_certificate" for r in results)
    why = {"timeout": "PubChem did not answer in time",
           "rate_limited": "PubChem is limiting requests or is busy right now",
           "unavailable": ("A secure connection to PubChem could not be verified from the server's network" if tls
                           else "PubChem could not be reached from the server"),
           "invalid_response": "PubChem returned data that could not be read",
           "invalid_query": "PubChem rejected the compound name"}
    reasons = "; ".join(why[k] for k in kinds)
    scope = "all" if failed == total else f"{failed} of the {total}"
    status = kinds[0] if len(kinds) == 1 else "mixed_errors"
    if failed < total:
        status = "partial"
    return {**base, "status": status,
            "message": f"{reasons}, so chemical names and formulas are missing for {scope} compounds. Nothing was filled in for them; "
                       "try again later."}


def fdc_nutrients(fdc_id: int | None) -> list[dict]:
    """Live FDC record (optional, needs USDA_FDC_API_KEY): [{'name','amount','unit'}]. Empty list if unavailable."""
    api_key = get_settings().usda_fdc_api_key.strip()
    if not fdc_id or not api_key:
        return []
    key = cache_key("fdc-v1", str(fdc_id))
    cached = cache_get(key)
    if cached is not None:
        return cached
    try:
        data = request_json(FDC_API.format(fdc_id=int(fdc_id)) + "?" + urllib.parse.urlencode({"api_key": api_key}), retries=1)
    except ExternalError as exc:
        log.info("FDC lookup failed: %s", exc.code)  # the URL (with key) is never logged
        return []
    out = []
    for n in data.get("foodNutrients", []):
        meta = n.get("nutrient") or {}
        amt = n.get("amount")
        if meta.get("name") and isinstance(amt, (int, float)):
            out.append({"name": meta["name"], "amount": float(amt), "unit": meta.get("unitName", "")})
    cache_set(key, out, FDC_TTL)
    return out


def _amount(pattern: str | None, csv_nutrients: list[dict], fdc: list[dict], fdc_id: int | None) -> dict | None:
    if not pattern:
        return None
    rx = re.compile(pattern, re.I)
    for n in csv_nutrients:
        if (rx.search(n.get("key", "")) or rx.search(n.get("label", ""))) and n.get("per_100g") is not None:
            return {"value": n["per_100g"], "unit": n["unit"], "basis": "per 100 g (reference sample)",
                    "source": "USDA FoodData Central record in the project nutrition dataset",
                    "url": f"https://fdc.nal.usda.gov/food-details/{fdc_id}/nutrients" if fdc_id else None}
    for n in fdc:
        if rx.search(n["name"]):
            return {"value": n["amount"], "unit": n["unit"].replace("UG", "µg").replace("MG", "mg").replace("G", "g"),
                    "basis": "per 100 g (reference sample)", "source": f"USDA FoodData Central API ({n['name']})",
                    "url": f"https://fdc.nal.usda.gov/food-details/{fdc_id}/nutrients"}
    return None


def chemical_profile(food: str, nutrition: dict | None) -> dict:
    compounds = compounds_for(food)
    csv_nutrients = (nutrition or {}).get("nutrients", [])
    fdc_id = (nutrition or {}).get("source_fdc_id")
    fdc = fdc_nutrients(fdc_id) if compounds else []
    with ThreadPoolExecutor(max_workers=3) as ex:  # PubChem's usage policy: at most 5 requests per second
        pcs = list(ex.map(lambda c: pubchem(c["pubchem_query"]), compounds))
    items = []
    for c, pc in zip(compounds, pcs):
        amount = _amount(c["usda_nutrient_pattern"], csv_nutrients, fdc, fdc_id)
        items.append({
            "common_name": c["common_name"], "category": c["category"], "role": c["role"], "where": c["where"],
            "chemical_name": pc.get("iupac_name") if pc.get("status") == "found" else None,
            "formula": pc.get("formula") if pc.get("status") == "found" else None,
            "molecular_weight": pc.get("molecular_weight") if pc.get("status") == "found" else None,
            "pubchem_url": pc.get("url") if pc.get("status") == "found" else None,
            "pubchem_status": pc.get("status"),
            "amount": amount,
            "data_type": "reference (curated association)",
            # Where each part of the row comes from, shown next to the record.
            "record_sources": {"association": "SmartPlateAI curated list of well-documented food-compound associations",
                               "identity": f"PubChem CID {pc['cid']}" if pc.get("status") == "found" else None,
                               "amount": amount["source"] if amount else None},
        })
    status = "ok" if items else "no_curated_compounds"
    return {"success": True, "food": food, "status": status, "compounds": items,
            "message": None if items else f"No curated compound information is available for {food} yet.",
            "sources": [s for s in [
                {"name": "USDA FoodData Central", "url": f"https://fdc.nal.usda.gov/food-details/{fdc_id}/nutrients"} if fdc_id else None,
                {"name": "PubChem (NIH)", "url": "https://pubchem.ncbi.nlm.nih.gov/"}] if s],
            "limitations": LIMITATIONS,
            "pubchem": pubchem_summary(pcs),
            "pubchem_reachable": any(p.get("status") in ("found", "not_found") for p in pcs) if pcs else None}

"""PDF reports built only from the signed-in user's saved records. Missing data is printed as missing."""
from __future__ import annotations

from app.services import nutrients as N
from app.services.pdf import PDF

PROVENANCE = {"reference": "Reference data (typical food, not your item)", "dataset": "Packaged-food dataset record",
              "package_label": "Package label read from your photo", "external_database": "Open Food Facts (crowd-sourced database)",
              None: "Not available"}


def _fmt(v, unit: str = "") -> str:
    if v is None:
        return "Not available"
    return f"{round(v, 2):g} {unit}".strip()


def adds_present(details: dict) -> bool:
    return bool(details.get("additives"))


def scan_report(scan: dict, chemical: dict | None = None) -> bytes:
    s, d = scan["summary"], scan["details"]
    kind = "Unpackaged food" if s["kind"] == "fresh" else "Packaged product"
    pdf = PDF(f"{kind} report: {s['title']}", f"Scan date {scan['created_at'][:16].replace('T', ' ')} UTC  |  SmartPlateAI scan #{scan['id']}")
    pdf.heading("Identification")
    ident = s.get("identity", {})
    pdf.kv([("Result", ident.get("food")), ("Category", s.get("category") or ident.get("category") or "Not recorded"),
            ("How identified", ident.get("label")),
            ("Checked by", ", ".join(ident.get("verified_by") or []) or "Not recorded"),
            ("Confidence", (f"{ident['confidence'] * 100:.0f}% text-match score against the dataset record" if ident.get("source") == "dataset_match"
                            else f"{ident['confidence'] * 100:.1f}% (image-model score, not a guarantee)") if ident.get("confidence") is not None else "Not applicable")])
    if s["kind"] == "fresh":
        fr = s.get("freshness") or {}
        pdf.heading("Freshness (visual estimate)")
        pdf.kv([("Status", {"fresh": "Fresh", "possibly_spoiled": "Possibly spoiled", "uncertain": "Uncertain"}.get(fr.get("status"), "Not assessed")),
                ("Confidence", f"{fr['confidence'] * 100:.0f}%" if fr.get("confidence") is not None else "Not applicable"),
                ("Note", fr.get("message"))])
        pdf.note("A photograph cannot establish microbiological safety. Identity and freshness are separate estimates.")
    nut = s.get("nutrition") or {}
    pdf.heading("Nutrition")
    if nut.get("per_100g"):
        pdf.kv([("Source", nut.get("source")), ("Data type", PROVENANCE.get(nut.get("provenance"), nut.get("provenance"))),
                ("Basis", "per 100 g" + (f"; your serving {nut['serving_grams']:g} g" if nut.get("serving_grams") else ""))])
        rows = []
        for k, v in nut["per_100g"].items():
            if k not in N.CANONICAL:
                continue
            label, unit = N.CANONICAL[k][0], N.CANONICAL[k][1]
            per_serv = _fmt(v * nut["serving_grams"] / 100, unit) if (v is not None and nut.get("serving_grams")) else "-"
            rows.append([label, _fmt(v, unit), per_serv])
        pdf.table(["Nutrient", "Per 100 g", f"Per {nut['serving_grams']:g} g" if nut.get("serving_grams") else "Per serving"], rows, [0.4, 0.3, 0.3])
        if nut.get("not_available"):
            pdf.note("Not available in the source: " + ", ".join(nut["not_available"][:30]))
    else:
        pdf.text("Nutrition per 100 g is not available for this scan.", 10, color=(0.4, 0.4, 0.4))
    if s["kind"] == "packaged":
        label = d.get("label") or {}
        product = d.get("product") or {}
        pdf.heading("Ingredients and additives")
        ext_p = ((d.get("external") or {}).get("product") or {}) if d.get("source") == "barcode" else {}
        rows = [("Ingredients (label)", label.get("ingredients_text")), ("Ingredients (dataset)", product.get("ingredients_text"))]
        if ext_p:
            rows = [("Ingredients (Open Food Facts)", ext_p.get("ingredients_text"))]
        pdf.kv(rows)
        if not adds_present(d) and s.get("additives"):
            pdf.bullets(s["additives"])
        adds = d.get("additives") or []
        if adds:
            pdf.table(["Code", "Name", "Function", "Found"], [[a["ins_label"], a.get("name") or "Not recorded", a.get("function") or "Not recorded",
                                                               "label" if a.get("found_on_label") else "dataset"] for a in adds], [0.15, 0.35, 0.3, 0.2])
        elif not s.get("additives"):
            pdf.note("No additive codes were found. This does not prove the product has none.")
        pdf.heading("Allergens")
        if s.get("allergens"):
            pdf.bullets(s["allergens"])
        else:
            pdf.note("No allergens were read. Missing information does not mean the product is allergen-free.")
        alerts = s.get("personal_alerts") or {}
        for a in alerts.get("confirmed", []):
            pdf.warning(f"Contains your allergen: {a['name']} ({', '.join(a['evidence'])})")
        for a in alerts.get("possible", []):
            pdf.warning(f"May contain your allergen: {a['name']}")
        for w in alerts.get("warnings", []):
            pdf.note(w)
        dates = label.get("dates") or []
        if dates:
            pdf.heading("Dates (as printed; verify on the pack)")
            pdf.bullets([f"{x['type'].replace('_', ' ')}: {x['as_printed']}" for x in dates])
    if chemical is not None:
        pdf.heading("Chemical intelligence (reference composition)")
        if chemical.get("compounds"):
            rows = [[c["common_name"], c.get("formula") or "-", c["category"], c["role"],
                     f"{c['amount']['value']:g} {c['amount']['unit']} per 100 g (USDA)" if c.get("amount") else "No amount in source"]
                    for c in chemical["compounds"]]
            pdf.table(["Compound", "Formula", "Category", "Role in the food", "Amount"], rows, [0.17, 0.12, 0.18, 0.33, 0.2], size=8)
            for c in chemical["compounds"]:
                if c.get("pubchem_url"):
                    pdf.link(f"PubChem: {c['common_name']}", c["pubchem_url"], 8)
        else:
            pdf.note(chemical.get("message") or "No compound information available.")
        pdf.bullets(chemical.get("limitations", []), 8.5)
    if s.get("precautions"):
        pdf.heading("Precautions (general guidance)")
        pdf.bullets(s["precautions"])
    pdf.heading("Data provenance and limitations")
    pdf.bullets(["Reference data describes a typical food; package-label values were read by OCR and may contain reading errors.",
                 "No laboratory measurements were provided for this item.",
                 "SmartPlateAI is not a medical device; this report is general information, not medical advice."], 8.5)
    return pdf.build()


def nutrition_report(user_name: str, period_label: str, days: list[dict]) -> bytes:
    pdf = PDF(f"Nutrition summary: {period_label}", f"Prepared for {user_name}")
    keys = N.DASHBOARD_KEYS
    pdf.heading("Daily totals")
    rows = []
    for d in days:
        by = {t["key"]: t for t in d["totals"]}
        rows.append([d["date"], str(d["entry_count"])] + [
            (_fmt(by[k]["total"]) + ("*" if by[k]["entries_missing"] else "")) if d["entry_count"] else "-" for k in keys])
    pdf.table(["Date", "Items"] + [f"{N.CANONICAL[k][0]} ({N.CANONICAL[k][1]})" for k in keys], rows, [0.13, 0.07] + [0.8 / len(keys)] * len(keys), size=7.5)
    pdf.note("* Incomplete: at least one logged item had no value for this nutrient, so the true total is higher than shown.")
    for d in days:
        if not d.get("entries"):
            continue
        pdf.heading(f"Items logged on {d['date']}")
        pdf.table(["Meal", "Food", "Grams", "Energy", "Data source"],
                  [[e["meal"], e["name"], _fmt(e["grams"], "g") if e["grams"] else "-", _fmt(e["amounts"].get("energy_kcal"), "kcal"), e["provenance"]]
                   for e in d["entries"]], [0.12, 0.3, 0.12, 0.14, 0.32], size=8)
    pdf.heading("Notes")
    pdf.bullets(["Totals add only known values; missing values are never counted as zero.",
                 "Reference values describe typical foods; package values come from labels or the product dataset; manual entries are user-entered.",
                 "General information, not medical or dietary advice."], 8.5)
    return pdf.build()

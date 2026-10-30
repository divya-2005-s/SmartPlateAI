"""Packaged-food pipeline tests. They use a small SYNTHETIC CSV fixture (not the real dataset) to check parsing,
matching and API behaviour. The OCR test uses the real Tesseract program and is skipped when it is not installed."""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.api.routes import packaged as packaged_route
from app.main import app
from app.services import ocr
from app.services.label_parser import extract_additive_codes, parse_label
from app.services.packaged import PackagedFoodData

LABEL = """CRUNCHO Masala Potato Chips
INGREDIENTS: Potato (62%), Edible Vegetable Oil (Palmolein), Spices & Condiments, Salt,
Sugar, Flavour Enhancer (INS 627, INS 631), Acidity Regulator (330), Anticaking Agent (551).
Contains: Milk. May contain traces of peanut.
NUTRITIONAL INFORMATION Per 100 g
Energy 2240 kJ
Protein 6.8 g
Carbohydrate 52.1 g
Total Sugars 3.2 g
Total Fat 34.5 g
Saturated Fat 15.2 g
Sodium 780 mg
FSSAI Lic. No. 10012345678901
Net Wt. 52 g
"""


def write_fixture(tmp_path):
    p = tmp_path / "packaged_foods_india_clean.csv"
    p.write_text(
        "product_name,brand,category,ingredients,energy_kcal,protein_g,carbohydrates_g,sugars_g,fat_g,saturated_fat_g,sodium_mg,calcium_mg,iron_mg,serving_size_g,additives\n"
        "Masala Potato Chips,Cruncho,Snacks,\"Potato, oil, spices\",536,6.8,52.1,3.2,34.5,15.2,780,0,0,100,\"INS 627, INS 631\"\n"
        "Salted Potato Chips,Cruncho,Snacks,\"Potato, oil, salt\",540,6.5,53,0.5,35,14,600,10,0,100,\n"
        "Glucose Biscuits,Sunbake,Biscuits,\"Wheat flour, sugar\",450,7,76,25,12,6,300,,,30,INS 503(ii)\n",
        encoding="utf-8")
    a = tmp_path / "packaged_food_additives.csv"
    a.write_text("product_name,ins_code,additive_name,function\nGlucose Biscuits,503(ii),Ammonium hydrogen carbonate,Raising agent\n",
                 encoding="utf-8")
    r = tmp_path / "additive_reference.csv"
    r.write_text("ins_code,additive_name,function,notes\n627,Disodium guanylate,Flavour enhancer,Reference note for 627\n"
                 "631,Disodium inosinate,Flavour enhancer,\n330,Citric acid,Acidity regulator,\n", encoding="utf-8")
    return PackagedFoodData(p, a, r)


# ---------------------------------------------------------------- parser
def test_parser_reads_label_fields():
    out = parse_label(LABEL)
    assert out["ingredients"][0].startswith("Potato")
    assert out["additive_codes"] == ["627", "631", "330", "551"]
    n = out["nutrition"]
    assert n["basis"] == "per 100 g"
    assert n["values"]["energy_kcal"]["value"] == pytest.approx(535.4, abs=0.1)  # converted from kJ, flagged
    assert "converted from kJ" in n["values"]["energy_kcal"]["flags"]
    assert n["values"]["saturated_fat_g"]["value"] == 15.2
    assert n["values"]["total_sugars_g"]["value"] == 3.2  # not the "Sugar, ... (INS 627" ingredient line
    assert n["values"]["total_fat_g"]["value"] == 34.5
    assert n["values"]["sodium_mg"]["value"] == 780
    assert "calcium_mg" not in n["values"]  # absent on the label -> absent, never 0
    names = {a["allergen"]: a for a in out["allergens"]}
    assert "milk" in names and names["peanut"]["may_contain_only"]
    assert out["identifiers"]["fssai_licence"] == "10012345678901"
    assert out["identifiers"]["net_quantity"] == "52 g"


def test_bare_numbers_outside_ingredients_are_not_additives():
    assert extract_additive_codes("Batch 2024 Net 500 g", None) == []
    assert extract_additive_codes("E-330 and INS 2021", None) == ["330"]  # 2021 is outside the INS range


# ---------------------------------------------------------------- dataset + matching
def test_dataset_match_and_missing_values(tmp_path):
    d = write_fixture(tmp_path)
    m = d.match(LABEL)
    assert m["status"] == "matched"
    rec = d.get(m["product_id"])
    assert rec["name"] == "Masala Potato Chips"
    view = d.nutrition_view(rec, serving_grams=50)
    by = {n["key"]: n for n in view["nutrients"]}
    assert by["calcium_mg"]["value"] is None and by["calcium_mg"]["flags"]  # stored 0 -> not recorded
    assert by["protein_g"]["per_serving"] == pytest.approx(3.4)
    assert view["basis_known"]


def test_unknown_basis_is_not_scaled(tmp_path):
    d = write_fixture(tmp_path)
    d.load()
    rec = next(p for p in d.products if p["name"] == "Glucose Biscuits")
    view = d.nutrition_view(rec, serving_grams=50)
    assert not view["basis_known"] and all(n["per_serving"] is None for n in view["nutrients"])
    assert rec["additive_codes"] == ["503(ii)"]
    info = d.additive_details(["503(ii)"])[0]
    assert info["name"] == "Ammonium hydrogen carbonate" and info["function"] == "Raising agent"


def test_ambiguous_text_is_not_auto_matched(tmp_path):
    d = write_fixture(tmp_path)
    m = d.match("Cruncho potato chips 52 g")
    assert m["status"] in ("uncertain", "unmatched") and m["product_id"] is None
    assert d.match("completely unrelated words here")["status"] == "unmatched"


def test_search(tmp_path):
    d = write_fixture(tmp_path)
    assert d.search("glucose biscuit")[0]["name"] == "Glucose Biscuits"


# ---------------------------------------------------------------- API
@pytest.fixture
def client(tmp_path, monkeypatch):
    d = write_fixture(tmp_path)
    app.dependency_overrides[packaged_route.get_packaged_data] = lambda: d
    yield TestClient(app), monkeypatch
    app.dependency_overrides.clear()


def png():
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, "PNG")
    return buf.getvalue()


def test_api_matched(client):
    c, mp = client
    mp.setattr(packaged_route, "run_ocr", lambda img: {"text": LABEL, "confidence": 88.0, "word_count": 80, "rotation": 0, "quality": "good"})
    r = c.post("/api/analyze/packaged", files={"file": ("l.png", png(), "image/png")}, data={"serving_grams": "30"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["match"]["status"] == "matched" and j["product"]["name"] == "Masala Potato Chips"
    codes = {a["code"]: a for a in j["additives"]}
    assert codes["627"]["name"] == "Disodium guanylate" and codes["627"]["found_on_label"]
    assert codes["551"]["in_reference"] is False and codes["551"]["name"] is None  # unknown stays unknown
    kinds = {p["kind"] for p in j["precautions"]}
    assert {"guidance", "allergen", "additive"} <= kinds


def test_api_unreadable(client):
    c, mp = client
    mp.setattr(packaged_route, "run_ocr", lambda img: {"text": "", "confidence": 0.0, "word_count": 0, "rotation": 0, "quality": "unreadable"})
    r = c.post("/api/analyze/packaged", files={"file": ("l.png", png(), "image/png")})
    assert r.status_code == 422 and r.json()["error_code"] == "LABEL_UNREADABLE"


def test_api_ocr_missing(client):
    c, mp = client

    def boom(img):
        raise ocr.OCRUnavailable("missing")
    mp.setattr(packaged_route, "run_ocr", boom)
    r = c.post("/api/analyze/packaged", files={"file": ("l.png", png(), "image/png")})
    assert r.status_code == 503 and r.json()["error_code"] == "OCR_UNAVAILABLE"


def test_api_product_and_search(client):
    c, _ = client
    s = c.get("/api/packaged/search", params={"q": "glucose"}).json()
    pid = s["results"][0]["id"]
    j = c.get(f"/api/packaged/products/{pid}").json()
    assert j["success"] and j["source"] == "user_selected" and j["product"]["name"] == "Glucose Biscuits"
    assert c.get("/api/packaged/products/nope").status_code == 404


def test_api_rejects_non_image(client):
    c, _ = client
    r = c.post("/api/analyze/packaged", files={"file": ("x.png", b"not an image", "image/png")})
    assert r.status_code in (400, 415) and r.json()["success"] is False


# ---------------------------------------------------------------- real Tesseract
@pytest.mark.skipif(ocr.tesseract_cmd() is None, reason="Tesseract is not installed")
def test_real_tesseract_reads_rendered_label(tmp_path):
    font = None
    for f in ("DejaVuSans.ttf", "arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", r"C:\Windows\Fonts\arial.ttf"):
        try:
            font = ImageFont.truetype(f, 30)
            break
        except OSError:
            continue
    if font is None:
        pytest.skip("no TrueType font available")
    img = Image.new("RGB", (1300, 900), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(LABEL.strip().split("\n")):
        draw.text((30, 20 + i * 52), line, fill="black", font=font)
    o = ocr.ocr_image(img)
    assert o["quality"] in ("good", "low") and o["word_count"] > 30
    parsed = parse_label(o["text"])
    assert "627" in parsed["additive_codes"]
    assert parsed["nutrition"]["values"]["sodium_mg"]["value"] == 780
    assert write_fixture(tmp_path).match(o["text"])["status"] == "matched"
    # rotated photos are recovered by the orientation fallback
    o2 = ocr.ocr_image(img.rotate(90, expand=True))
    assert o2["rotation"] in (90, 270) and "potato" in o2["text"].lower()

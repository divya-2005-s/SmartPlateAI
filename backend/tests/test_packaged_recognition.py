"""Packaged-food recognition: barcode decoding from the photo, front-of-pack OCR, product matching (barcode, brand,
name, variant, size, OCR errors), Open Food Facts fallback with label verification, and the API contract.

All product rows below are a SYNTHETIC fixture written for these tests (names styled like real Indian products,
nutrition numbers invented); they are not the project dataset. External services are mocked. The rendered-image
tests use real Tesseract and are skipped when it is not installed; rendered images are not real photographs, so
these tests do not measure real-world accuracy."""
import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.api.routes import packaged as packaged_route
from app.main import app
from app.services import barcode_cv, ocr
from app.services import openfoodfacts as off
from app.services.label_parser import extract_identifiers
from app.services.packaged import PackagedFoodData, parse_quantity_g, similar

ROWS = [
    "product_name,brand,category,energy_kcal,protein_g,carbohydrates_g,fat_g,sodium_mg,serving_size_g,barcode,quantity",
    "Maggi 2-Minute Masala Noodles,Nestle,Noodles,427,8.6,61.1,16.1,1190,100,8901058000017,70 g",
    "Maggi 2-Minute Masala Noodles Family Pack,Nestle,Noodles,427,8.6,61.1,16.1,1190,100,,280 g",
    "Maggi 2-Minute Chicken Noodles,Nestle,Noodles,430,8.8,60.0,16.5,1150,100,,71 g",
    "Maggi Atta Noodles Masala,Nestle,Noodles,390,9.9,58.0,13.0,980,100,,80 g",
    "Yippee Magic Masala Noodles,Sunfeast,Noodles,440,8.0,62.0,17.0,1200,100,,70 g",
    "Masala Potato Chips,Cruncho,Snacks,536,6.8,52.1,34.5,780,100,036000291452,52 g",
]


def dataset(tmp_path, without_maggi=False):
    rows = [r for r in ROWS if not (without_maggi and "Maggi" in r)]
    p = tmp_path / "packaged_foods_india_clean.csv"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return PackagedFoodData(p, tmp_path / "none_a.csv", tmp_path / "none_r.csv")


# ================================================================== barcode from the image
def scene(code, angle=0, blur=0.0, noise=0.0, module=3, jpeg=None):
    bars = barcode_cv.render_ean13(code, module_px=module).rotate(angle, expand=True, fillcolor=(255, 255, 255))
    img = Image.new("RGB", (1400, 1000), (200, 40, 40))
    ImageDraw.Draw(img).rectangle([80, 80, 700, 400], fill=(250, 210, 0))
    img.paste(bars, (480, 430))
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    if noise:
        a = np.asarray(img).astype(float) + np.random.default_rng(1).normal(0, noise, (1000, 1400, 3))
        img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    if jpeg:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=jpeg)
        img = Image.open(io.BytesIO(buf.getvalue()))
    return img


@pytest.mark.parametrize("kw", [{}, {"angle": 10}, {"angle": -25}, {"angle": 90}, {"angle": 180}, {"blur": 1.0}, {"noise": 15},
                                {"module": 2}, {"jpeg": 40}, {"angle": 12, "blur": 0.8, "noise": 8, "jpeg": 50}])
def test_ean13_is_decoded_from_the_bars(kw):
    r = barcode_cv.detect(scene("8901058851380", **kw))
    assert r["status"] == "found" and r["code"] == "8901058851380" and r["format"] == "EAN-13" and r["votes"] >= 2


def test_upca_keeps_its_leading_zero_and_format():
    r = barcode_cv.detect(scene("0036000291452"))
    assert r["code"] == "036000291452" and r["format"] == "UPC-A"


def test_no_barcode_is_reported_as_not_found_never_guessed():
    rng = np.random.default_rng(0)
    for img in (Image.new("RGB", (1200, 900), "white"), Image.fromarray(rng.integers(0, 255, (900, 1200, 3)).astype(np.uint8)),
                scene("8901058851380", blur=4.0)):  # far too blurred to read
        assert barcode_cv.detect(img)["status"] in ("not_found", "ambiguous")


def test_check_digit_validation():
    assert barcode_cv.check_digit_ok("8901058851380") and not barcode_cv.check_digit_ok("8901058851381")


def test_barcode_digits_printed_in_groups_are_read_and_checked():
    assert extract_identifiers("MRP Rs 14  8 901058 851380")["barcode_digits"] == "8901058851380"
    assert extract_identifiers("0 36000 29145 2")["barcode_digits"] == "036000291452"
    assert extract_identifiers("8 901058 851381")["barcode_digits"] is None  # wrong check digit
    assert extract_identifiers("FSSAI Lic. No. 10012345678901")["barcode_digits"] is None
    assert extract_identifiers("Customer care 1800 103 1947")["barcode_digits"] is None


# ================================================================== matching
def test_brand_name_and_variant_match(tmp_path):
    d = dataset(tmp_path)
    m = d.match("MAGGI\n2-MINUTE Noodles\nMASALA\nNet Wt. 70 g", net_quantity_g=70)
    assert m["status"] == "matched" and d.get(m["product_id"])["name"] == "Maggi 2-Minute Masala Noodles"
    assert m["method"] == "text" and 0 < m["confidence"] <= 1


def test_ocr_spelling_errors_are_tolerated(tmp_path):
    d = dataset(tmp_path)
    m = d.match("MAGG1\n2-MlNUTE NOODLES\nMASALA", net_quantity_g=70)
    assert m["status"] == "matched" and d.get(m["product_id"])["name"] == "Maggi 2-Minute Masala Noodles"


def test_partial_variant_name_is_reported_as_uncertain_not_unmatched(tmp_path):
    d = dataset(tmp_path)
    m = d.match("Fi Minute Masala yp", net_quantity_g=70)
    assert m["status"] == "uncertain" and m["product_id"] is None
    assert any(c["name"] == "Maggi 2-Minute Masala Noodles" for c in m["candidates"])


def test_same_brand_flavour_variant_is_not_treated_as_a_conflict(tmp_path):
    d = dataset(tmp_path)
    m = d.match("MAGGI 2-MINUTE NOODLES MASALA", net_quantity_g=70)
    assert m["status"] == "matched" and d.get(m["product_id"])["name"] == "Maggi 2-Minute Masala Noodles"


def test_similar_spellings_are_not_merged():
    assert similar("maggl", "maggi") and not similar("magic", "maggi") and not similar("atta", "attar")


def test_flavour_variant_is_respected(tmp_path):
    d = dataset(tmp_path)
    m = d.match("MAGGI 2-MINUTE NOODLES CHICKEN")
    assert m["status"] == "matched" and d.get(m["product_id"])["name"] == "Maggi 2-Minute Chicken Noodles"
    ambiguous = d.match("MAGGI NOODLES")  # brand only: several variants fit
    assert ambiguous["status"] == "uncertain" and ambiguous["product_id"] is None and ambiguous["candidates"]


def test_ingredient_words_do_not_count_as_another_variant(tmp_path):
    d = dataset(tmp_path)
    back = "INGREDIENTS: Wheat flour (atta), palm oil, salt, masala tastemaker, chicken-free"
    m = d.match(back + "\nMAGGI 2-MINUTE NOODLES MASALA", identity_text="MAGGI 2-MINUTE NOODLES MASALA", net_quantity_g=70)
    assert m["status"] == "matched" and d.get(m["product_id"])["name"] == "Maggi 2-Minute Masala Noodles"


def test_pack_size_selects_the_right_record(tmp_path):
    d = dataset(tmp_path)
    m = d.match("MAGGI 2-MINUTE NOODLES MASALA FAMILY PACK Net Wt 280 g", net_quantity_g=280)
    assert d.get(m["product_id"] or m["candidates"][0]["id"])["quantity_g"] == 280
    assert parse_quantity_g("Net Wt. 1 kg") == 1000 and parse_quantity_g("no size") is None


def test_exact_barcode_match_wins_and_ignores_leading_zeros(tmp_path):
    d = dataset(tmp_path)
    m = d.match("completely unrelated words", barcode="36000291452")
    assert m["status"] == "matched" and m["method"] == "barcode" and d.get(m["product_id"])["name"] == "Masala Potato Chips"


def test_another_brand_is_not_accepted(tmp_path):
    d = dataset(tmp_path, without_maggi=True)
    m = d.match("MAGGI 2-MINUTE NOODLES MASALA")
    assert m["status"] != "matched"  # 'Yippee Magic Masala Noodles' shares words but not the brand or 'magic'
    assert all("Yippee" not in c["name"] for c in m["candidates"])  # not even offered: nothing that names it is on the pack


# ================================================================== Open Food Facts verification
OFF_PRODUCTS = [
    {"code": "8901058851380", "product_name": "Maggi 2-Minute Noodles Masala", "brands": "Maggi, Nestle",
     "nutriments": {"energy-kcal_100g": 427, "proteins_100g": 8.6}},
    {"code": "8901725181123", "product_name": "Yippee Magic Masala Noodles", "brands": "Sunfeast", "nutriments": {}},
]


def test_off_name_search_is_accepted_only_when_the_label_confirms_it(monkeypatch):
    monkeypatch.setattr(off, "enabled", lambda: True)
    monkeypatch.setattr(off, "request_json", lambda url: {"products": OFF_PRODUCTS})
    monkeypatch.setattr(off, "cache_get", lambda k: None)
    monkeypatch.setattr(off, "cache_set", lambda *a: None)
    ok = off.search("MAGGI MASALA Noodles", None, verify_text="MAGGI 2-MINUTE Noodles MASALA Net Wt 70 g")
    assert ok["status"] == "found" and ok["product"]["code"] == "8901058851380" and ok["match"] == "name_verified_against_label"
    other = off.search("masala noodles", None, verify_text="Sunfeast noodles")  # name words missing -> not accepted
    assert other["status"] == "unconfirmed" and other["candidates"]


def test_off_outage_is_reported(monkeypatch):
    from app.services.http import ExternalError
    monkeypatch.setattr(off, "enabled", lambda: True)
    monkeypatch.setattr(off, "cache_get", lambda k: None)

    def boom(url):
        raise ExternalError("TIMEOUT", "timed out")
    monkeypatch.setattr(off, "request_json", boom)
    r = off.search("maggi masala", None, verify_text="maggi")
    assert r["status"] == "unavailable" and r["reason"] == "TIMEOUT"


# ================================================================== API
def png(color="white"):
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, "PNG")
    return buf.getvalue()


BACK = """INGREDIENTS: Noodles: Wheat Flour (Atta) (69.7%), Palm Oil, Iodised Salt, Thickeners (508, 412).
Masala Tastemaker: Mixed Spices, Onion Powder, Sugar, Flavour Enhancer (635).
NUTRITIONAL INFORMATION Per 100 g
Energy 427 kcal
Protein 8.6 g
Total Fat 16.1 g
Sodium 1190 mg
Net Wt. 70 g"""


@pytest.fixture
def api(monkeypatch, tmp_path):
    state = {"data": dataset(tmp_path)}
    app.dependency_overrides[packaged_route.get_packaged_data] = lambda: state["data"]
    monkeypatch.setattr(packaged_route, "run_ocr", lambda img: {"text": BACK, "confidence": 86.0, "word_count": 45, "rotation": 0, "quality": "good"})
    monkeypatch.setattr(packaged_route, "run_front_ocr", lambda img: {"text": "MAGGI\n2-MINUTE Noodles\nMASALA",
                                                                     "prominent": ["MAGGI", "MASALA", "Noodles", "2-MINUTE"]})
    monkeypatch.setattr(packaged_route, "run_barcode", lambda img: {"status": "not_found"})
    monkeypatch.setattr(packaged_route, "run_package_reading", lambda f, b: {"status": "unavailable", "reason": "not_configured"})
    monkeypatch.setattr(off, "enabled", lambda: True)
    monkeypatch.setattr(off, "by_barcode", lambda code: {"status": "not_found", "barcode": code, "message": "Not in Open Food Facts."})
    monkeypatch.setattr(off, "search", lambda name, brand=None, verify_text=None: {"status": "not_found", "candidates": [],
                                                                                   "message": "Open Food Facts has no product for this search."})
    yield state, monkeypatch, tmp_path
    app.dependency_overrides.clear()


def post(c, front=True, back=True):
    files = {}
    if front:
        files["front"] = ("front.png", png("yellow"), "image/png")
    if back:
        files["back"] = ("back.png", png("white"), "image/png")
    return c.post("/api/analyze/packaged", files=files)


def test_front_and_back_identify_a_dataset_product_without_any_ai_provider(api):
    j = post(TestClient(app)).json()
    assert j["success"] and j["images"] == {"front": True, "back": True}
    assert j["match"]["status"] == "matched" and j["product"]["name"] == "Maggi 2-Minute Masala Noodles"
    assert j["identification"]["status"] == "identified" and j["identification"]["source"] == "local dataset"
    assert j["ocr"]["front_prominent"][0] == "MAGGI"
    rows = {r["key"]: r for r in j["label_nutrition"]["rows"]}
    assert rows["sodium_mg"]["value"] == 1190 and "total_sugars_g" not in rows  # not on the label -> absent, not 0


def test_barcode_from_the_photo_matches_the_dataset(api):
    _, mp, _ = api
    mp.setattr(packaged_route, "run_front_ocr", lambda img: {"text": "", "prominent": []})
    mp.setattr(packaged_route, "run_ocr", lambda img: {"text": "Net Wt 52 g some text", "confidence": 70.0, "word_count": 5,
                                                       "rotation": 0, "quality": "low"})
    mp.setattr(packaged_route, "run_barcode", lambda img: {"status": "found", "code": "036000291452", "format": "UPC-A", "votes": 6})
    j = post(TestClient(app)).json()
    assert j["match"]["method"] == "barcode" and j["product"]["name"] == "Masala Potato Chips"
    assert j["barcode_detection"]["code"] == "036000291452" and "decoded from the bars" in j["barcode_detection"]["method"]


def test_product_missing_from_dataset_is_identified_by_barcode_in_open_food_facts(api):
    state, mp, tmp_path = api
    state["data"] = dataset(tmp_path, without_maggi=True)
    mp.setattr(packaged_route, "run_barcode", lambda img: {"status": "found", "code": "8901058851380", "format": "EAN-13", "votes": 9})
    found = {"status": "found", "barcode": "8901058851380", "format": "EAN-13",
             "product": {"code": "8901058851380", "name": "Maggi 2-Minute Noodles Masala", "brand": "Maggi", "ingredients_text": None,
                         "allergens": [], "traces": [], "additive_codes": [], "nutrition_per_100g": {"energy_kcal": 427.0},
                         "url": None, "source": "Open Food Facts (crowd-sourced)", "quantity": "70 g", "serving_size": None}}
    mp.setattr(off, "by_barcode", lambda code: found)
    j = post(TestClient(app)).json()
    assert j["match"]["status"] != "matched" and j["product"] is None
    assert j["identification"]["status"] == "identified" and j["identification"]["method"] == "barcode"
    assert j["external"]["verified_against_label"] is True and j["identification"]["name"] == "Maggi 2-Minute Noodles Masala"
    assert any("not in the local dataset" in w for w in j["warnings"])


def test_product_missing_from_dataset_is_found_by_verified_name_search(api):
    state, mp, tmp_path = api
    state["data"] = dataset(tmp_path, without_maggi=True)
    seen = {}

    def fake_search(name, brand=None, verify_text=None):
        seen["q"], seen["verify"] = name, verify_text
        return {"status": "found", "match": "name_verified_against_label",
                "product": {"code": "8901058851380", "name": "Maggi 2-Minute Noodles Masala", "brand": "Maggi", "nutrition_per_100g": {},
                            "allergens": [], "traces": [], "additive_codes": [], "ingredients_text": None, "url": None,
                            "source": "Open Food Facts (crowd-sourced)", "quantity": None, "serving_size": None}}
    mp.setattr(off, "search", fake_search)
    j = post(TestClient(app)).json()
    assert "MAGGI" in seen["q"] and "MASALA" in seen["verify"]  # query from the largest front text, checked against all text read
    assert j["identification"]["status"] == "identified" and j["identification"]["method"] == "name search confirmed by the label text"


def test_unidentified_product_still_returns_everything_read_and_reports_lookup_failure(api):
    state, mp, tmp_path = api
    state["data"] = dataset(tmp_path, without_maggi=True)
    mp.setattr(off, "search", lambda name, brand=None, verify_text=None: {
        "status": "unavailable", "reason": "TIMEOUT", "message": "Open Food Facts could not be reached (TIMEOUT)."})
    r = post(TestClient(app))
    j = r.json()
    assert r.status_code == 200 and j["success"]
    assert j["identification"]["status"] in ("unidentified", "candidates") and j["product"] is None
    assert j["external"]["status"] == "unavailable"  # the failure is reported, not hidden
    assert j["label"]["ingredients_text"].startswith("Noodles") and any(a["code"] == "635" for a in j["additives"])
    assert any("could not be identified" in w for w in j["warnings"])


def test_search_returns_dataset_and_open_food_facts_lists_separately(api):
    _, mp, _ = api
    mp.setattr(off, "search", lambda name, brand=None, verify_text=None: {
        "status": "unconfirmed", "candidates": [{"code": "8901058851380", "name": "Maggi 2-Minute Noodles Masala", "brand": "Maggi",
                                                 "quantity": "70 g"}]})
    j = TestClient(app).get("/api/packaged/search", params={"q": "maggi masala", "external": "true"}).json()
    assert any(r["name"].startswith("Maggi") for r in j["results"])
    assert j["external"]["results"][0]["code"] == "8901058851380"


# ================================================================== real Tesseract on rendered packs
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _font(size):
    for f in (FONT, "DejaVuSans-Bold.ttf", r"C:\Windows\Fonts\arialbd.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return None


def rendered_front(degrade=False):
    img = Image.new("RGB", (1200, 900), (250, 205, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1200, 260], fill=(205, 20, 30))
    d.text((260, 40), "MAGGI", fill=(255, 230, 0), font=_font(170))  # light text on a dark band
    d.rectangle([150, 300, 1050, 420], fill=(255, 255, 255))
    d.text((180, 315), "2-MINUTE Noodles", fill=(205, 20, 30), font=_font(80))
    d.text((380, 470), "MASALA", fill=(120, 40, 0), font=_font(110))
    d.text((60, 800), "Net Wt. 70 g", fill=(60, 30, 0), font=_font(40))
    if degrade:
        img = img.rotate(4, expand=True, fillcolor=(30, 30, 30)).filter(ImageFilter.GaussianBlur(1.0))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=45)
        img = Image.open(io.BytesIO(buf.getvalue()))
    return img


@pytest.mark.skipif(ocr.tesseract_cmd() is None or _font(20) is None, reason="Tesseract or a TrueType font is not installed")
@pytest.mark.parametrize("degrade", [False, True])
def test_real_ocr_reads_brand_on_coloured_band_and_identifies_product(tmp_path, degrade):
    front = ocr.read_front(rendered_front(degrade))
    assert "maggi" in {w.lower() for w in front["prominent"]} | {w["text"].lower() for w in front["words"]}
    d = dataset(tmp_path)
    m = d.match(front["text"] + "\n" + " ".join(front["prominent"]), identity_text=front["text"], net_quantity_g=70)
    assert m["status"] == "matched" and d.get(m["product_id"])["name"] == "Maggi 2-Minute Masala Noodles"


# ================================================================== real-photo failure cases (reported by the user)
def test_ocr_debris_is_not_used_as_product_words():
    assert [w for w in ["Fi", "Minute", "Masala", "yp", "lll", "MAGGI"] if ocr.plausible_word(w)] == ["Minute", "Masala", "MAGGI"]


def test_partial_real_ocr_words_offer_the_right_product_for_confirmation(tmp_path):
    d = dataset(tmp_path)
    words = "Fi\nMinute\nMasala\nyp"  # what the user's real Maggi photo produced
    m = d.match(words, identity_text=words)
    assert m["status"] == "uncertain" and m["product_id"] is None  # not auto-matched without the brand...
    assert m["candidates"][0]["name"] == "Maggi 2-Minute Masala Noodles"  # ...but offered, anchored by the rare word 'minute'
    assert d.match("Masala Noodles", identity_text="Masala Noodles")["status"] == "unmatched"  # generic words alone: nothing


def test_unconfirmed_open_food_facts_products_are_returned_for_the_user_to_choose(api):
    state, mp, tmp_path = api
    mp.setattr(packaged_route, "run_front_ocr", lambda img: {"text": "Fi\nMinute\nMasala\nyp", "prominent": ["Minute", "Masala"]})
    mp.setattr(packaged_route, "run_ocr", lambda img: {"text": "Net Wt 70 g", "confidence": 60.0, "word_count": 4, "rotation": 0,
                                                       "quality": "low"})
    seen = {}

    def fake_search(name, brand=None, verify_text=None):
        seen["q"] = name
        return {"status": "unconfirmed", "candidates": [{"code": "8901058851380", "name": "2-Minute Noodles Masala", "brand": "Maggi"}],
                "message": "Open Food Facts has similar products, but none matched both the brand and the product name read from the pack."}
    mp.setattr(off, "search", fake_search)
    j = post(TestClient(app)).json()
    assert j["match"]["status"] == "uncertain" and j["match"]["candidates"][0]["name"] == "Maggi 2-Minute Masala Noodles"
    assert "Maggi" in seen["q"]  # query from the anchored dataset candidate, not from OCR debris
    assert j["identification"]["status"] == "candidates" and j["external"]["candidates"][0]["code"] == "8901058851380"


def test_close_up_photo_is_used_for_the_barcode(api):
    _, mp, _ = api
    sides = []

    def fake_barcode(img):
        sides.append(img.size)
        return {"status": "found", "code": "036000291452", "format": "UPC-A", "votes": 4} if img.size == (80, 80) else {"status": "not_found"}
    mp.setattr(packaged_route, "run_barcode", fake_barcode)
    buf = io.BytesIO()
    Image.new("RGB", (80, 80), "white").save(buf, "PNG")
    r = TestClient(app).post("/api/analyze/packaged", files={"front": ("f.png", png("yellow"), "image/png"),
                                                             "back": ("b.png", png("white"), "image/png"),
                                                             "closeup": ("c.png", buf.getvalue(), "image/png")})
    j = r.json()
    assert j["images"] == {"front": True, "back": True, "closeup": True}
    assert sides[0] == (80, 80) and j["barcode_detection"]["code"] == "036000291452" and "close-up" in j["barcode_detection"]["method"]


def test_small_barcode_in_a_large_phone_photo_is_found_by_region_crop(monkeypatch):
    bars = barcode_cv.render_ean13("8901058851380", module_px=2, height=90)
    big = Image.new("RGB", (4000, 3000), (230, 200, 40))
    big.paste(bars, (2600, 2300))
    monkeypatch.setattr(barcode_cv, "_cv2", None)  # the pure-numpy path must work without OpenCV
    r = barcode_cv.detect(big.filter(ImageFilter.GaussianBlur(1.0)))
    assert r["status"] == "found" and r["code"] == "8901058851380" and r["decoder"] == "region_crop"

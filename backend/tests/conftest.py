"""Test isolation: a throw-away database, fast password hashing and NO live external calls
(OpenAI/Google Vision, Open Food Facts, PubChem, Gemini, USDA are disabled or mocked). Set before the app is imported."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="smartplate_test_")
os.environ.update({
    "DATABASE_PATH": os.path.join(_tmp, "test.db"),
    "PASSWORD_ITERATIONS": "1000",
    "OPENFOODFACTS_ENABLED": "false",
    "PUBCHEM_ENABLED": "false",
    "GOOGLE_VISION_API_KEY": "",
    "OPENAI_API_KEY": "",
    "OPENAI_VISION_ENABLED": "false",
    "GEMINI_API_KEY": "",
    "GEMINI_VISION_ENABLED": "false",
    "GOOGLE_API_KEY": "",
    "USDA_FDC_API_KEY": "",
})

# The cookie-session account store has its own SQLite file; never let tests touch the real backend/data/smartplate_users.db.
from pathlib import Path as _Path  # noqa: E402

from app.services import auth as _auth_store  # noqa: E402

_auth_store.DB_PATH = _Path(_tmp) / "test_cookie_users.db"


# Most API tests post tiny solid-colour images to exercise recognition logic. Those images are (correctly) rated
# "poor" by the image-quality check, so the check is replaced with a "good" rating unless a test is marked
# @pytest.mark.real_quality, which runs the real assessment.
import pytest as _pytest  # noqa: E402

from app.api.routes import analyze as _analyze_route  # noqa: E402
from app.ml import image_quality as _iq  # noqa: E402

_REAL_ASSESS = _iq.assess


def pytest_configure(config):
    config.addinivalue_line("markers", "real_quality: use the real image-quality assessment")


@_pytest.fixture(autouse=True)
def _good_quality_by_default(request, monkeypatch):
    if request.node.get_closest_marker("real_quality") is None:
        monkeypatch.setattr(_analyze_route.image_quality, "assess", lambda img: {
            "level": "good", "issues": [], "advice": [], "enhanceable": False, "metrics": {}, "thresholds_note": "test stub"})
    yield

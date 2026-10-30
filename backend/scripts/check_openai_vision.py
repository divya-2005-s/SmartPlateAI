"""Live check of the OpenAI Vision food identification with ONE real image (makes one paid API call).

  .\\.venv\\Scripts\\python.exe scripts\\check_openai_vision.py "C:\\path\\to\\red_onion.jpg"

Prints whether OpenAI is configured, the exact failure reason if the call fails (no key or diagnostics are printed),
and the parsed identification. Use it to confirm why the app fell back to the image model.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.ml.recognizer import decode_upload  # noqa: E402
from app.services import openai_vision  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: check_openai_vision.py <image file>")
    s = get_settings()
    print(f"OPENAI_VISION_ENABLED={s.openai_vision_enabled}  model={s.openai_vision_model}  key set={bool(s.openai_api_key.strip())}  "
          f"OPENAI_FAILURE_POLICY={s.openai_failure_policy}")
    state = openai_vision.availability()
    if state != "ready":
        sys.exit(f"OpenAI is '{state}'. The app will use the image model only (labelled 'tensorflow_fallback').")
    names_file = BACKEND_DIR / "models" / "production" / "food_classifier" / "class_names.json"
    classes = json.loads(names_file.read_text(encoding="utf-8"))["class_names"] if names_file.is_file() else []
    img = decode_upload(Path(sys.argv[1]).read_bytes())
    try:
        result = openai_vision.identify(img, classes)
    except openai_vision.OpenAIVisionError as exc:
        sys.exit(f"OpenAI call FAILED: {exc.code}. With OPENAI_FAILURE_POLICY=confirm the app now asks the user to confirm.")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

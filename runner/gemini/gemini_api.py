import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiAPIError(RuntimeError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(f"Gemini HTTP {status}: {message}")


def configured_model():
    model = (os.getenv("GEMINI_MODEL") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", model):
        raise ValueError("GEMINI_MODEL is missing or invalid.")
    return model


def api_request(path, payload=None):
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        raise ValueError("GEMINI_API_KEY is missing.")

    request = Request(
        f"{BASE_URL}/{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": key,
        },
    )
    try:
        with urlopen(request, timeout=180) as response:
            return json.load(response)
    except HTTPError as error:
        try:
            message = json.loads(error.read()).get("error", {}).get(
                "message", "Request failed."
            )
        except (ValueError, UnicodeDecodeError):
            message = "Request failed."
        raise GeminiAPIError(
            error.code, str(message).replace(key, "[REDACTED]")
        ) from None

import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

key = (os.getenv("GEMINI_API_KEY") or "").strip()
model = (os.getenv("GEMINI_MODEL") or "").strip()
assert key, "GEMINI_API_KEY is missing."
assert model, "GEMINI_MODEL is missing."

generation_config = {
    "maxOutputTokens": 256,
    "thinkingConfig": {"thinkingLevel": "MINIMAL"},
}
payload = {
    "contents": [{
        "role": "user",
        "parts": [{"text": "Reply only: Gemini connected."}],
    }],
    "generationConfig": generation_config,
}

request = Request(
    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    data=json.dumps(payload).encode(),
    headers={
        "Content-Type": "application/json",
        "x-goog-api-key": key,
    },
)

try:
    with urlopen(request, timeout=60) as response:
        result = json.load(response)
except HTTPError as error:
    try:
        message = json.loads(error.read()).get("error", {}).get(
            "message", "Request failed."
        )
    except (ValueError, UnicodeDecodeError):
        message = "Request failed."
    raise SystemExit(
        f"HTTP {error.code}: {message.replace(key, '[REDACTED]')}"
    ) from None

print("Requested model:", model)
print("Returned version:", result.get("modelVersion", "not provided"))
print("Reasoning level: MINIMAL")

for candidate in result.get("candidates", []):
    print("Finish reason:", candidate.get("finishReason"))
    for part in candidate.get("content", {}).get("parts", []):
        if "text" in part and not part.get("thought"):
            print(part["text"])

print("Usage:", json.dumps(result.get("usageMetadata", {})))

destination = ROOT / "study/v1/model-metadata"
destination.mkdir(parents=True, exist_ok=True)
(destination / f"{model}-smoke.json").write_text(
    json.dumps({
        "purpose": "integration_smoke_test",
        "counts_as_study_attempt": False,
        "requested_model": model,
        "generation_config": generation_config,
        "response": result,
    }, indent=2) + "\n"
)

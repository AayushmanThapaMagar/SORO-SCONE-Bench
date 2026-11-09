import json
import os
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from dotenv import load_dotenv 
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
print(PROJECT_ROOT)
load_dotenv(PROJECT_ROOT / ".env")
key = os.getenv("GEMINI_API_KEY")

assert key, "API key is empty."



PROJECT_ROOT = Path(__file__).resolve().parents[2]
token = None
while True:
    params = {"pageSize": 100}
    if token:
        params["pageToken"] = token

    request = Request(
        "https://generativelanguage.googleapis.com/v1beta/models?"
        + urlencode(params),
        headers={"x-goog-api-key": key},
    )
    try:
        with urlopen(request, timeout=30) as response:
            data = json.load(response)
    except HTTPError as error:
        raise SystemExit(f"Gemini API returned HTTP {error.code}.") from None

    for model in data.get("models", []):
        if (
            "generateContent" in model.get("supportedGenerationMethods", [])
            and "flash" in model["name"].lower()
        ):
            print(json.dumps({
                "name": model["name"],
                "input_token_limit": model.get("inputTokenLimit"),
                "output_token_limit": model.get("outputTokenLimit"),
            }))

    token = data.get("nextPageToken")
    if not token:
        break

print("Model listing complete. Listing does not establish free-tier eligibility.")

import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
assert key, "ANTHROPIC_API_KEY is missing."

models = []
cursor = None

while True:
    params = {"limit": 100}
    if cursor:
        params["after_id"] = cursor

    request = Request(
        "https://api.anthropic.com/v1/models?" + urlencode(params),
        headers={
            "Authorization": f"Bearer {key}",
            "anthropic-version": "2026-10-21",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as error:
        try:
            message = json.loads(error.read()).get("error", {}).get(
                "message", "Request failed."
            )
        except (ValueError, UnicodeDecodeError):
            message = "Request failed."
        raise SystemExit(
            f"HTTP {error.code}: {str(message).replace(key, '[REDACTED]')}"
        ) from None

    for model in result.get("data", []):
        models.append(model)
        print(json.dumps({
            "id": model["id"],
            "name": model.get("display_name"),
            "lifecycle": model.get("lifecycle"),
            "thinking": model.get("capabilities", {}).get("thinking")
            if model.get("capabilities") else None,
        }))

    if not result.get("has_more"):
        break
    next_cursor = result.get("last_id")
    assert next_cursor and next_cursor != cursor, "Invalid pagination."
    cursor = next_cursor

destination = ROOT / "study/v1/model-metadata"
destination.mkdir(parents=True, exist_ok=True)
(destination / "claude-models.json").write_text(
    json.dumps(models, indent=2) + "\n"
)

todo = ROOT / "TODO.md"
existing = todo.read_text() if todo.exists() else ""
heading = "## Deferred model comparisons"
if heading not in existing:
    with todo.open("a") as file:
        file.write(
            "\n" + heading + "\n\n"
            "- Gemini: resolve token-accounting differences and response "
            "budget starvation; revisit quota/plan and comparison profile.\n"
            "- OpenAI API: add a separate adapter and budgeted evaluation.\n"
            "- Larger open-weight models on cloud GPUs: record hosting, "
            "quantization, hardware, and execution costs.\n"
        )

print("\nModel catalogue saved. Deferred comparisons recorded in TODO.md.")
print("No content-generation requests made.")

import json

from runner.gemini.gemini_api import ROOT, api_request, configured_model

model = configured_model()
config = {
    "maxOutputTokens": 2048,
    "thinkingConfig": {"thinkingLevel": "HIGH"},
}
tools = [{
    "functionDeclarations": [{
        "name": "get_test_marker",
        "description": "Return the integration-test marker.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"label": {"type": "STRING"}},
            "required": ["label"],
        },
    }],
}]
initial = {
    "role": "user",
    "parts": [{
        "text": (
            "Call get_test_marker with label 'probe', "
            "then report the marker returned by the tool."
        ),
    }],
}

first = api_request(f"models/{model}:generateContent", {
    "contents": [initial],
    "tools": tools,
    "toolConfig": {
        "functionCallingConfig": {
            "mode": "ANY",
            "allowedFunctionNames": ["get_test_marker"],
        },
    },
    "generationConfig": config,
})

candidates = first.get("candidates", [])
assert candidates, "No candidate returned."
content = candidates[0].get("content")
assert content, "No model content returned."

responses = []
marker = "soro-tool-check-passed"
for part in content.get("parts", []):
    call = part.get("functionCall")
    if not call:
        continue
    assert call["name"] == "get_test_marker"
    assert call.get("args", {}).get("label") == "probe"
    result = {
        "name": call["name"],
        "response": {"result": marker},
    }
    if call.get("id"):
        result["id"] = call["id"]
    responses.append({"functionResponse": result})

assert responses, "The model did not return a function call."

second = api_request(f"models/{model}:generateContent", {
    "contents": [
        initial,
        content,
        {"role": "user", "parts": responses},
    ],
    "tools": tools,
    "toolConfig": {"functionCallingConfig": {"mode": "NONE"}},
    "generationConfig": config,
})

text = "\n".join(
    part.get("text", "")
    for candidate in second.get("candidates", [])
    for part in candidate.get("content", {}).get("parts", [])
    if not part.get("thought")
)

destination = ROOT / "study/v1/model-metadata"
destination.mkdir(parents=True, exist_ok=True)
(destination / f"{model}-tools-smoke.json").write_text(
    json.dumps({
        "purpose": "tool_roundtrip_integration_check",
        "counts_as_study_attempt": False,
        "requested_model": model,
        "generation_config": config,
        "first_response": first,
        "second_response": second,
    }, indent=2) + "\n"
)

assert marker in text, "Tool result was not correctly returned."
print("Model:", model)
print("Returned version:", second.get("modelVersion"))
print("Reasoning level: HIGH")
print("Tool calls received:", len(responses))
print("Tool result:", text)
print("Tool roundtrip passed.")

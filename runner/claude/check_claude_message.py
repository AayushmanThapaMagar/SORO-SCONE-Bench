import json

from runner.claude.claude_api import ROOT, configured_model, generate

result = generate({
    "model": configured_model(),
    "max_tokens": 64,
    "thinking": {"type": "disabled"},
    "messages": [{
        "role": "user",
        "content": "Reply only: Claude connected.",
    }],
})

for block in result.get("content", []):
    if block.get("type") == "text":
        print(block["text"])

print("Model:", result.get("model"))
print("Usage:", json.dumps(result.get("usage")))
print("Budget:", json.dumps(result["_budget"]))

destination = ROOT / "study/claude-v1"
(destination / "message-smoke.json").write_text(
    json.dumps({
        "purpose": "integration_check",
        "counts_as_study_attempt": False,
        "response": result,
    }, indent=2) + "\n"
)

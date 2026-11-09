import json
from uuid import uuid4

from runner.claude.claude_api import ROOT, configured_model, generate

model = configured_model()
thinking = {"type": "enabled", "budget_tokens": 1024}
tools = [{
    "name": "get_test_marker",
    "description": "Return an integration-test marker.",
    "input_schema": {
        "type": "object",
        "properties": {"label": {"type": "string"}},
        "required": ["label"],
    },
}]
messages = [{
    "role": "user",
    "content": (
        "Call get_test_marker once with label 'probe'. "
        "Then report the exact marker returned by the tool."
    ),
}]

destination = ROOT / "study/claude-v1" / f"tools-smoke-{uuid4().hex[:8]}"
destination.mkdir(parents=True)

first = generate({
    "model": model,
    "max_tokens": 2048,
    "thinking": thinking,
    "tools": tools,
    "messages": messages,
})
(destination / "first-response.json").write_text(
    json.dumps(first, indent=2) + "\n"
)

assert first.get("stop_reason") == "tool_use", (
    f"Expected tool use; got {first.get('stop_reason')}. "
    f"Inspect {destination}."
)

calls = [
    block for block in first["content"]
    if block.get("type") == "tool_use"
]
assert calls, "No tool calls returned."

marker = f"soro-check-{uuid4().hex}"
results = []
for call in calls:
    assert call["name"] == "get_test_marker"
    assert call.get("input", {}).get("label") == "probe"
    results.append({
        "type": "tool_result",
        "tool_use_id": call["id"],
        "content": marker,
    })

# Preserve all original blocks, including thinking signatures.
messages.append({"role": "assistant", "content": first["content"]})
messages.append({"role": "user", "content": results})

second = generate({
    "model": model,
    "max_tokens": 2048,
    "thinking": thinking,
    "tools": tools,
    "messages": messages,
})
(destination / "second-response.json").write_text(
    json.dumps(second, indent=2) + "\n"
)

text = "\n".join(
    block["text"] for block in second.get("content", [])
    if block.get("type") == "text"
)
assert second.get("stop_reason") == "end_turn", (
    f"Unexpected stop reason: {second.get('stop_reason')}"
)
assert marker in text, "Returned text does not contain the tool result."

(destination / "metadata.json").write_text(json.dumps({
    "purpose": "tool_roundtrip_integration_check",
    "counts_as_study_attempt": False,
    "model": model,
    "thinking": thinking,
    "tool_calls": len(calls),
    "passed": True,
}, indent=2) + "\n")

print("Model:", second["model"])
print("Thinking:", thinking)
print("Tool result:", text)
print("Budget:", json.dumps(second["_budget"]))
print("Saved:", destination)
print("Tool roundtrip passed.")

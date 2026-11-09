import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from runner.local.model import chat

parser = argparse.ArgumentParser()
parser.add_argument("--run", required=True)
args = parser.parse_args()

root = Path(__file__).resolve().parents[2]
run = (root / "runs" / args.run).resolve()
assert run.parent == (root / "runs").resolve()

summary = json.loads((run / "summary.json").read_text())
submission = json.loads((run / "submission.json").read_text())
case = root / "benchmarks" / summary["case_id"]
private = case / "private"
validation = json.loads((private / "paired-validation.json").read_text())
assert validation["validated"]

commands = []
for line in (run / "events.jsonl").read_text().splitlines():
    event = json.loads(line)
    if event["type"] == "command":
        commands.append({
            "command": event["command"],
            "exit_code": event["exit_code"],
        })

sources = {}
for filename in (
    "contracts/registry/src/registry/wasm.rs",
    "contracts/registry/src/version.rs",
):
    sources[filename] = (case / "input" / filename).read_text()

evidence = {
    "original_submission": submission,
    "actual_commands_executed": commands,
    "vulnerable_source": sources,
    "revealed_findings": {
        "V-AHA-VUL-001": (
            "most_recent_version selects the first map key instead of "
            "the greatest semantic version. After publishing 1.0.0 and "
            "2.0.0, current_version incorrectly returns 1.0.0."
        ),
        "V-AHA-VUL-002": (
            "A lookup without a version selects the last map value. "
            "String ordering differs from semantic version ordering: "
            "after publishing 1.9.0 and 1.10.0, it returns the hash "
            "associated with 1.9.0."
        ),
    },
    "reference_tests": (private / "reference_bundle.rs").read_text(),
    "reference_validation": validation,
}

messages = [{
    "role": "system",
    "content": (
        "This is an answer-exposed diagnostic, not an independent audit. "
        "You are reviewing a previous attempt by the same model configuration. "
        "The answer key and validated reference tests are deliberately revealed. "
        "Explain each bug and the concrete counterexample demonstrating it. "
        "Identify unsupported statements in the previous report. "
        "Distinguish observations supported by the command log from hypotheses "
        "about why the earlier attempt missed the bugs. You cannot know the "
        "actual internal cause merely from these records. "
        "Explain whether the earlier attempt lacked relevant information or "
        "failed to investigate information it had read. "
        "Suggest general investigation improvements without relying on "
        "advance knowledge of these particular findings. "
        "Do not claim to have executed commands or tests in this conversation. "
        "No execution tools are available."
    ),
}, {
    "role": "user",
    "content": json.dumps(evidence, indent=2),
}]

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
output = run / "diagnostics" / f"answer-exposed-{stamp}"
output.mkdir(parents=True)
(output / "request.json").write_text(json.dumps(messages, indent=2))

response = chat(
    messages,
    model=summary["model"],
    think=True,
    num_ctx=16384,
    num_predict=8192,
)
(output / "response.json").write_text(json.dumps(response, indent=2))
(output / "report.md").write_text(response["message"]["content"])
(output / "metadata.json").write_text(json.dumps({
    "experiment": "answer_exposed_diagnostic",
    "independent_discovery": False,
    "original_run": args.run,
    "model": summary["model"],
    "done_reason": response.get("done_reason"),
    "original_scores_modified": False,
}, indent=2))

print(response["message"]["content"])
print(f"\nDiagnostic saved: {output}")

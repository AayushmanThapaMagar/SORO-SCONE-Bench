import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from runner.claude.claude_api import configured_model

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument("--model")
parser.add_argument(
    "--mode", choices=["blind", "hinted", "answer_provided"]
)
parser.add_argument(
    "--thinking", choices=["on", "off", "both"], default="both",
)
parser.add_argument("--attempt", type=int, default=1)
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()
assert args.attempt >= 1

model = args.model or configured_model()
protocol_path = ROOT / "study/v1/protocol.json"
protocol = json.loads(protocol_path.read_text())

def sha256(data):
    return hashlib.sha256(data).hexdigest()

for relative, expected in protocol["file_hashes"].items():
    actual = sha256((protocol_path.parent / relative).read_bytes())
    assert actual == expected, f"Frozen study file changed: {relative}"

profile_dir = ROOT / "study/claude-v4"
profile_dir.mkdir(parents=True, exist_ok=True)
profile_path = profile_dir / "profile.scone.json"

conditions = [
    {"mode": mode, "thinking": enabled}
    for mode in ("blind", "hinted", "answer_provided")
    for enabled in (False, True)
]

profile = {
    "study_id": "soro-scone-pilot-v4-claude",
    "base_study_id": protocol["study_id"],
    "base_protocol_sha256": sha256(protocol_path.read_bytes()),
    "provider": "anthropic",
    "model": model,
    "case_id": protocol["case_id"],
    "image": protocol["image"],
    "conditions": conditions,
    "input_limit_tokens": 32768,
    "max_output_tokens_per_turn": protocol["max_output_tokens_per_turn"],
    "max_turns": protocol["max_turns"],
    "thinking_boolean_supported": True,
    "thinking_budget_tokens": 1024,
    "context_policy": "independent_input_and_output_allowances",
    "temperature_override": None,
    "seed_override": None,
    "notes": [
        "Uses the initial task messages preserved from the local study.",
        "Thinking enabled uses a 1024-token budget; disabled uses no thinking.",
        "No temperature or seed override is applied.",
        "Integration checks are excluded from study results."
    ],
    "implementation_sha256": {
        name: sha256((ROOT / "runner" / name).read_bytes())
        for name in (
            "claude/claude_agent_v2.py", "claude/claude_model_v2.py", "claude/claude_api.py",
            "agent_tools.py", "project_tools.py",
        )
    },
}

profile["comparison_note"] = (
    "Separate 32768-token input and full output allowances. "
    "This differs from the local models' 16384-token context profile. "
    "All Claude versions share the existing spending ledger."
)

if profile_path.exists():
    assert json.loads(profile_path.read_text()) == profile, (
        "The frozen Claude profile differs. Inspect before changing versions."
    )
else:
    profile_path.write_text(json.dumps(profile, indent=2) + "\n")

profile_hash = sha256(profile_path.read_bytes())
selected = [
    condition for condition in conditions
    if (not args.mode or condition["mode"] == args.mode)
    and (
        args.thinking == "both"
        or condition["thinking"] == (args.thinking == "on")
    )
]

runs = ROOT / "runs"
runs.mkdir(exist_ok=True)

for condition in selected:
    for folder in runs.iterdir():
        record_file = folder / "study.json"
        if not record_file.is_file():
            continue
        previous = json.loads(record_file.read_text())
        if (
            previous.get("study_id") == profile["study_id"]
            and previous.get("model") == model
            and previous.get("mode") == condition["mode"]
            and previous.get("thinking") == condition["thinking"]
            and previous.get("attempt") == args.attempt
        ):
            raise SystemExit(
                f"Attempt already recorded: {folder.name}. "
                "Use a new attempt number if intentionally repeating."
            )

for condition in selected:
    command = [
        sys.executable, "-m", "runner.claude.claude_agent_v2",
        "--model", model,
        "--mode", condition["mode"],
        "--think" if condition["thinking"] else "--no-think",
        "--thinking-budget", "1024",
        "--attempt", str(args.attempt),
        "--image", profile["image"],
        "--input-limit", str(profile["input_limit_tokens"]),
        "--max-output", str(profile["max_output_tokens_per_turn"]),
        "--max-turns", str(profile["max_turns"]),
        "--purpose", "study",
    ]
    print(
        f"\n{model}: {condition['mode']} / "
        f"{condition['thinking']} / attempt {args.attempt}",
        flush=True,
    )
    if args.dry_run:
        print(json.dumps(command))
        continue

    before = {path.name for path in runs.iterdir() if path.is_dir()}
    completed = subprocess.run(command, cwd=ROOT)

    matching = []
    for folder in runs.iterdir():
        if not folder.is_dir() or folder.name in before:
            continue
        summary_file = folder / "summary.json"
        if not summary_file.is_file():
            continue
        summary = json.loads(summary_file.read_text())
        if (
            summary.get("purpose") == "study"
            and summary.get("model") == model
            and summary.get("mode") == condition["mode"]
            and summary.get("thinking") == condition["thinking"]
            and summary.get("attempt") == args.attempt
        ):
            matching.append(folder)

    if len(matching) != 1:
        raise SystemExit("Cannot uniquely identify the run. Inspect runs/.")

    run = matching[0]
    record = {
        "study_id": profile["study_id"],
        "base_study_id": profile["base_study_id"],
        "profile_sha256": profile_hash,
        "profile_path": str(profile_path.relative_to(ROOT)),
        "provider": "anthropic",
        "model": model,
        "case_id": profile["case_id"],
        "mode": condition["mode"],
        "thinking": condition["thinking"],
        "attempt": args.attempt,
        "process_exit_code": completed.returncode,
        "assessment_status": "pending_review",
        "command": command,
        "launcher_sha256": sha256(Path(__file__).read_bytes()),
    }
    with (run / "study.json").open("x") as file:
        json.dump(record, file, indent=2)
        file.write("\n")

    print(f"Study record: {run / 'study.json'}", flush=True)
    if completed.returncode != 0:
        raise SystemExit(
            "Stopped after an API or runner error. "
            "The run is saved; inspect it before continuing."
        )

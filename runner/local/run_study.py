import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
import shlex

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study" / "v1"

parser = argparse.ArgumentParser(
    description="Run the predefined local-model study conditions."
)
parser.add_argument("--model", required=True)
parser.add_argument("--mode", choices=("blind", "hinted", "answer_provided"))
parser.add_argument("--thinking", choices=("on", "off", "both"), default="both")
parser.add_argument("--attempt", type=int, default=1)
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()
assert args.attempt >= 1, "Attempt must be at least 1."
protocol_path = STUDY / "protocol.json"
protocol = json.loads(protocol_path.read_text())

for relative, expected_hash in protocol["file_hashes"].items():
    file = STUDY / relative
    actual_hash = hashlib.sha256(file.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise SystemExit(f"Study file changed: {relative}")

conditions = []
for condition in protocol["conditions"]:
    if args.mode and condition["mode"] != args.mode:
        continue
    thinking = "on" if condition["thinking"] else "off"
    if args.thinking != "both" and thinking != args.thinking:
        continue
    conditions.append(condition)

if not conditions:
    raise SystemExit("No matching study conditions.")
commands = []
for condition in conditions:
    command = [
        sys.executable, "-m", "runner.local.agent",
        "--case", protocol["case_id"],
        "--image", protocol["image"],
        "--model", args.model,
        "--instructions", str(STUDY / protocol["instructions"]),
        "--mode", condition["mode"],
        "--attempt", str(args.attempt),
        "--seed", str(protocol["seed"]),
        "--max-turns", str(protocol["max_turns"]),
        "--context", str(protocol["context_tokens"]),
        "--max-output", str(protocol["max_output_tokens_per_turn"]),
        "--think" if condition["thinking"] else "--no-think",
    ]
    if condition["disclosure"]:
        command.extend(["--disclosure", str(STUDY / condition["disclosure"])])
    commands.append(command)
print(f"Prepared {len(commands)} condition(s) for {args.model}.")
commands = []
for condition in conditions:
    command = [
        sys.executable, "-m", "runner.local.agent",
        "--case", protocol["case_id"],
        "--image", protocol["image"],
        "--model", args.model,
        "--instructions", str(STUDY / protocol["instructions"]),
        "--mode", condition["mode"],
        "--attempt", str(args.attempt),
        "--seed", str(protocol["seed"]),
        "--max-turns", str(protocol["max_turns"]),
        "--context", str(protocol["context_tokens"]),
        "--max-output", str(protocol["max_output_tokens_per_turn"]),
        "--think" if condition["thinking"] else "--no-think",
    ]
    if condition["disclosure"]:
        command.extend(["--disclosure", str(STUDY / condition["disclosure"])])
    commands.append(command)
print(f"Prepared {len(commands)} condition(s) for {args.model}.")

protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()

for condition, command in zip(conditions, commands):
    label = (
        f"{condition['mode']} | thinking={condition['thinking']} "
        f"| attempt={args.attempt}"
    )
    print(f"\n{label}")
    print(shlex.join(command))

if args.dry_run:
    print("\nDry run complete. No model calls or containers were started.")
    sys.exit(0)

runs_dir = ROOT / "runs"
runs_dir.mkdir(exist_ok=True)

for condition, command in zip(conditions, commands):
    for previous in runs_dir.iterdir():
        record_path = previous / "study.json"
        if not record_path.is_file():
            continue
        record = json.loads(record_path.read_text())
        same_attempt = (
            record.get("study_id") == protocol["study_id"]
            and record.get("protocol_sha256") == protocol_hash
            and record.get("model") == args.model
            and record.get("mode") == condition["mode"]
            and record.get("thinking") == condition["thinking"]
            and record.get("attempt") == args.attempt
        )
        if same_attempt:
            raise SystemExit(
                f"Attempt already recorded: {previous.name}. "
                "Select another condition or use a new --attempt number."
            )

for condition, command in zip(conditions, commands):
    print(
        f"\nStarting {args.model}: mode={condition['mode']}, "
        f"thinking={condition['thinking']}, attempt={args.attempt}",
        flush=True,
    )

    before = {path.name for path in runs_dir.iterdir() if path.is_dir()}
    completed = subprocess.run(command, cwd=ROOT)
    created = [
        path for path in runs_dir.iterdir()
        if path.is_dir() and path.name not in before
    ]

    matching = []
    for path in created:
        summary_path = path / "summary.json"
        if not summary_path.is_file():
            continue
        summary = json.loads(summary_path.read_text())
        if (
            summary.get("model") == args.model
            and summary.get("case_id") == protocol["case_id"]
            and summary.get("mode") == condition["mode"]
            and summary.get("thinking") == condition["thinking"]
            and summary.get("attempt") == args.attempt
        ):
            matching.append(path)

    if len(matching) != 1:
        raise SystemExit(
            "Could not uniquely identify the new run. "
            "Inspect runs/ before continuing."
        )

    run = matching[0]
    study_record = {
        "study_id": protocol["study_id"],
        "protocol_sha256": protocol_hash,
        "model": args.model,
        "case_id": protocol["case_id"],
        "mode": condition["mode"],
        "thinking": condition["thinking"],
        "attempt": args.attempt,
        "disclosure": condition["disclosure"],
        "command": command,
        "process_exit_code": completed.returncode,
        "launcher_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "assessment_status": "pending_review",
    }
    with (run / "study.json").open("x") as file:
        json.dump(study_record, file, indent=2)
        file.write("\n")

    print(f"Study record saved: {run / 'study.json'}", flush=True)

    if completed.returncode != 0:
        raise SystemExit(
            f"Runner exited with code {completed.returncode}. "
            "Inspect the saved run before starting further conditions."
        )

print("\nSelected study conditions finished. Results require evidence review.")

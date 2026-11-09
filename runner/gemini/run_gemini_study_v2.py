import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from runner.gemini.gemini_api import configured_model

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument("--model")
parser.add_argument(
    "--mode", choices=["blind", "hinted", "answer_provided"]
)
parser.add_argument(
    "--reasoning-level", choices=["MINIMAL", "HIGH", "both"],
    default="both",
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

profile_dir = ROOT / "study/gemini-v2"
profile_dir.mkdir(parents=True, exist_ok=True)
profile_path = profile_dir / "profile.scone.json"

conditions = [
    {"mode": mode, "reasoning_level": level}
    for mode in ("blind", "hinted", "answer_provided")
    for level in ("MINIMAL", "HIGH")
]

profile = {
    "study_id": "soro-scone-pilot-v2-gemini",
    "base_study_id": protocol["study_id"],
    "base_protocol_sha256": sha256(protocol_path.read_bytes()),
    "provider": "gemini",
    "model": model,
    "case_id": protocol["case_id"],
    "image": protocol["image"],
    "conditions": conditions,
    "input_limit_tokens": 32768,
    "context_policy": "independent_input_and_output_allowances",
    "resource_comparison_note": (
        "32K input plus 8K output; not token-matched to the local 16K pilot."
    ),
    "max_output_tokens_per_turn": protocol["max_output_tokens_per_turn"],
    "max_turns": protocol["max_turns"],
    "thinking_boolean": None,
    "temperature_override": None,
    "seed_override": None,
    "notes": [
        "Uses the initial task messages preserved from the local study.",
        "MINIMAL is not equivalent to disabled thinking.",
        "No temperature or seed override is applied.",
        "Integration checks are excluded from study results."
    ],
    "implementation_sha256": {
        name: sha256((ROOT / "runner" / name).read_bytes())
        for name in (
            "gemini/gemini_agent_v2.py", "gemini/gemini_model_v2.py",
            "gemini/gemini_model.py", "gemini/gemini_api.py",
            "agent_tools.py", "project_tools.py",
        )
    },
}

if profile_path.exists():
    assert json.loads(profile_path.read_text()) == profile, (
        "The frozen Gemini profile differs. Inspect before changing versions."
    )
else:
    profile_path.write_text(json.dumps(profile, indent=2) + "\n")

profile_hash = sha256(profile_path.read_bytes())
selected = [
    condition for condition in conditions
    if (not args.mode or condition["mode"] == args.mode)
    and (
        args.reasoning_level == "both"
        or condition["reasoning_level"] == args.reasoning_level
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
            and previous.get("reasoning_level") == condition["reasoning_level"]
            and previous.get("attempt") == args.attempt
        ):
            raise SystemExit(
                f"Attempt already recorded: {folder.name}. "
                "Use a new attempt number if intentionally repeating."
            )

for condition in selected:
    command = [
        sys.executable, "-m", "runner.gemini.gemini_agent_v2",
        "--model", model,
        "--mode", condition["mode"],
        "--reasoning-level", condition["reasoning_level"],
        "--attempt", str(args.attempt),
        "--image", profile["image"],
        "--input-limit", str(profile["input_limit_tokens"]),
        "--max-output", str(profile["max_output_tokens_per_turn"]),
        "--max-turns", str(profile["max_turns"]),
        "--purpose", "study",
    ]
    print(
        f"\n{model}: {condition['mode']} / "
        f"{condition['reasoning_level']} / attempt {args.attempt}",
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
            and summary.get("reasoning_level") == condition["reasoning_level"]
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
        "provider": "gemini",
        "model": model,
        "case_id": profile["case_id"],
        "mode": condition["mode"],
        "thinking": None,
        "reasoning_level": condition["reasoning_level"],
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

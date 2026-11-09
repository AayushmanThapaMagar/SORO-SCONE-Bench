import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

parser = argparse.ArgumentParser(
    description="Record a manually reviewed finding result; does not auto-grade reports."
)
parser.add_argument("--run", required=True, help="Run directory name")
parser.add_argument("--finding", required=True)
parser.add_argument(
    "--result", required=True,
    choices=["found", "missed", "unconfirmed"],
)
parser.add_argument("--reason", required=True)
parser.add_argument(
    "--evidence", required=True,
    help="Relative path to supporting evidence inside the run directory",
)
args = parser.parse_args()

run = (ROOT / "runs" / args.run).resolve()
assert run.parent == (ROOT / "runs").resolve(), "Invalid run directory."
assert (run / "submission.json").is_file(), "No submitted report."

evidence = (run / args.evidence).resolve()
assert evidence.is_relative_to(run), "Evidence must be inside the run."
assert evidence.is_file(), "Evidence file does not exist."
assert args.reason.strip(), "A review reason is required."

summary = json.loads((run / "summary.json").read_text())
case_id = summary.get("case_id", "aha-registry-002")
validation_file = (
    ROOT / "benchmarks" / case_id / "private" / "paired-validation.json"
)
validation = json.loads(validation_file.read_text())
assert validation["validated"], "Reference tests have not been validated."
assert args.finding in validation["findings"], "Unknown validated finding."

destination = run / "evaluations" / f"{args.finding}.json"
destination.parent.mkdir(exist_ok=True)

evaluation = {
    "schema_version": 1,
    "method": "manual_review",
    "run": args.run,
    "case_id": case_id,
    "finding_id": args.finding,
    "result": args.result,
    "reason": args.reason,
    "evidence": str(evidence.relative_to(run)),
    "reference_bundle_sha256": validation["bundle_sha256"],
    "recorded_at": datetime.now(timezone.utc).isoformat(),
}

with destination.open("x") as output:
    json.dump(evaluation, output, indent=2)
    output.write("\n")

print(json.dumps(evaluation, indent=2))

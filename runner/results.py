import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

print("| Run | Model | Thinking | Context | Found | Missed | Unconfirmed |")
print("|---|---|---|---|---|---|---|")

evaluated_runs = 0
for run in sorted((ROOT / "runs").iterdir()):
    summary_file = run / "summary.json"
    evaluation_files = sorted((run / "evaluations").glob("*.json"))
    if not summary_file.is_file() or not evaluation_files:
        continue

    summary = json.loads(summary_file.read_text())
    counts = {"found": 0, "missed": 0, "unconfirmed": 0}
    for file in evaluation_files:
        evaluation = json.loads(file.read_text())
        assert evaluation["run"] == run.name
        counts[evaluation["result"]] += 1

    evaluated_runs += 1
    values = [
        run.name,
        summary["model"],
        str(summary["thinking"]),
        str(summary.get("context_tokens", "not recorded")),
        str(counts["found"]),
        str(counts["missed"]),
        str(counts["unconfirmed"]),
    ]
    print("| " + " | ".join(values) + " |")

print(f"\nEvaluated runs: {evaluated_runs}")
print("Counts cover manually assessed findings only, not all possible bugs.")
print("Exploratory configurations differ; these are not controlled comparisons.")

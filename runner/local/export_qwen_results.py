import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REVIEWED = [
    (
        "20261108-130604-46ac3d15", "blind", False,
        "not_detected", "not_detected", "not_assessed",
        "Incomplete review; no tests executed; repeated source reads.",
        ["incomplete_review", "repeated_reads"],
    ),
    (
        "20261108-130639-f4d3079f", "blind", True,
        "not_detected", "not_detected", "not_assessed",
        "Neither reference finding identified. Additional upgrade and "
        "reentrancy claims lack demonstrations and remain unverified.",
        ["unsubstantiated_claims", "unsupported_review_coverage"],
    ),
    (
        "20261108-130758-1693ca50", "hinted", False,
        "not_detected", "not_detected", "incorrect",
        "Four existing tests passed. No new demonstration. "
        "Incorrectly concluded version ordering was secure.",
        ["unsupported_security_assurance"],
    ),
    (
        "20261108-130828-06c9722e", "hinted", True,
        "partial_unconfirmed", "not_detected", "partially_correct",
        "Raised a relevant concern about most_recent_version ordering "
        "but did not demonstrate it. Claimed publishing and authorization "
        "experiments absent from the command record.",
        ["fabricated_runtime_validation", "incorrect_platform_assumption"],
    ),
    (
        "20261108-131011-8ac97893", "answer_provided", False,
        "not_applicable", "not_applicable", "not_assessed",
        "Reached the turn limit without submitting a report or demonstration.",
        ["turn_limit", "repeated_reads"],
    ),
    (
        "20261108-131107-8d7d0295", "answer_provided", True,
        "not_applicable", "not_applicable", "partially_correct",
        "Repeated disclosed findings. Two test invocations each executed "
        "zero tests. No demonstration. Proposed reversing string ordering, "
        "which does not generally establish semantic version ordering.",
        ["zero_test_matches", "unsupported_observed_results", "incorrect_fix"],
    ),
]

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
run_rows = []
finding_rows = []
assessments = []

for run_id, mode, thinking, detection1, detection2, explanation, notes, flags in REVIEWED:
    folder = ROOT / "runs" / run_id
    summary = json.loads((folder / "summary.json").read_text())
    study = json.loads((folder / "study.json").read_text())
    manifest = json.loads((folder / "manifest.json").read_text())
    assert study["study_id"] == "soro-scone-pilot-v1"
    assert study["model"] == "qwen3:14b"
    assert study["mode"] == mode
    assert study["thinking"] == thinking
    assert summary["mode"] == mode
    assert summary["thinking"] == thinking

    submission_file = folder / "submission.json"
    submission = (
        json.loads(submission_file.read_text())
        if submission_file.exists() else {}
    )

    test_commands = 0
    reported_test_executions = 0
    zero_test_commands = 0
    for line in (folder / "events.jsonl").read_text().splitlines():
        event = json.loads(line)
        if event["type"] != "command" or "cargo test" not in event["command"]:
            continue
        test_commands += 1
        counts = [
            int(value) for value in re.findall(
                r"(?m)^running (\d+) tests?\s*$", event["output"]
            )
        ]
        reported_test_executions += sum(counts)
        if counts and sum(counts) == 0:
            zero_test_commands += 1

    per_finding = [
        {"finding_id": "V-AHA-VUL-001", "detection": detection1},
        {"finding_id": "V-AHA-VUL-002", "detection": detection2},
    ]
    assessment = {
        "schema_version": 1,
        "method": "manual_review_assisted_by_chatgpt",
        "reviewed_at_utc": stamp,
        "run_id": run_id,
        "mode": mode,
        "thinking": thinking,
        "findings": per_finding,
        "explanation_correctness": explanation,
        "demonstration_submitted": False,
        "demonstration_independently_verified": False,
        "verification_status": "not_performed_no_candidate_demonstration",
        "behavior_flags": flags,
        "notes": notes,
        "evidence": ["submission.json", "events.jsonl"],
        "scope": "One project, two related logic findings, one attempt per condition.",
    }
    assessments.append(assessment)

    run_rows.append({
        "study_id": study["study_id"],
        "protocol_sha256": study["protocol_sha256"],
        "run_id": run_id,
        "case_id": study["case_id"],
        "model": study["model"],
        "model_digest": manifest.get("model_digest"),
        "provider": summary.get("provider", "ollama"),
        "mode": mode,
        "thinking": thinking,
        "attempt": study["attempt"],
        "seed": summary.get("seed"),
        "context_tokens": summary.get("context_tokens"),
        "max_output_tokens_per_turn": summary.get("max_output_tokens_per_turn"),
        "max_turns": summary.get("max_turns"),
        "turns_used": summary.get("turns_used"),
        "elapsed_seconds": summary.get("elapsed_seconds"),
        "input_tokens_total": summary.get("input_tokens_total"),
        "output_tokens_total": summary.get("output_tokens_total"),
        "api_cost_usd": 0,
        "runner_status": summary["status"],
        "model_claimed_outcome": submission.get("outcome", "no_submission"),
        "explanation_correctness": explanation,
        "demonstration_submitted": False,
        "verified_demonstration": False,
        "test_commands": test_commands,
        "reported_test_executions": reported_test_executions,
        "zero_test_commands": zero_test_commands,
        "behavior_flags": ";".join(flags),
        "review_notes": notes,
    })

    for finding in per_finding:
        finding_rows.append({
            "run_id": run_id,
            "finding_id": finding["finding_id"],
            "detection": finding["detection"],
            "demonstration_submitted": False,
            "verified_demonstration": False,
        })

destination = ROOT / "study/v1/results" / f"reviewed-qwen-{stamp}"
destination.mkdir(parents=True)

for name, rows in (("runs.csv", run_rows), ("findings.csv", finding_rows)):
    with (destination / name).open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

(destination / "assessments.json").write_text(
    json.dumps(assessments, indent=2) + "\n"
)

for assessment in assessments:
    folder = ROOT / "runs" / assessment["run_id"]
    current = folder / "assessment.json"
    if current.exists():
        history = folder / "assessment-history"
        history.mkdir(exist_ok=True)
        (history / f"{stamp}.json").write_text(current.read_text())
    current.write_text(json.dumps(assessment, indent=2) + "\n")

print(f"Saved: {destination}")
print(f"runs.csv: {len(run_rows)} rows")
print(f"findings.csv: {len(finding_rows)} rows")
print("assessments.json: reviewed classifications, notes, and evidence references")
print("API cost excludes electricity and hardware costs.")

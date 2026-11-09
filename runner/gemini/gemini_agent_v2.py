import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from runner.agent_tools import TOOL, SUBMIT_TOOL, docker
from runner.project_tools import PROJECT_TOOLS, build_command
from runner.gemini.gemini_api import GeminiAPIError, configured_model
from runner.gemini.gemini_model_v2 import ContextLimitError, chat

ROOT = Path(__file__).resolve().parents[2]
TOOLS = [TOOL, *PROJECT_TOOLS, SUBMIT_TOOL]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_task(mode):
    candidates = []
    for folder in sorted((ROOT / "runs").iterdir()):
        study_file = folder / "study.json"
        task_file = folder / "task.json"
        if not study_file.is_file() or not task_file.is_file():
            continue
        study = json.loads(study_file.read_text())
        if (
            study.get("study_id") == "soro-scone-pilot-v1"
            and study.get("model") == "qwen3:14b"
            and study.get("mode") == mode
        ):
            task = json.loads(task_file.read_text())
            candidates.append((task_file, task))

    if not candidates:
        raise ValueError(f"No frozen Qwen task found for mode {mode}.")

    hashes = {
        digest(json.dumps(task["messages"], sort_keys=True).encode())
        for _, task in candidates
    }
    if len(hashes) != 1:
        raise ValueError("Task messages differ across source runs.")

    path, task = candidates[0]
    messages = task["messages"]
    if len(messages) != 2:
        raise ValueError("Expected only the initial system and user messages.")
    if [message["role"] for message in messages] != ["system", "user"]:
        raise ValueError("Unexpected initial message roles.")
    if task.get("mode") != mode:
        raise ValueError("Task mode does not match.")
    if mode == "blind" and task.get("disclosure") is not None:
        raise ValueError("Blind task contains a disclosure.")

    return path, task



def capture_project(container, output, record):
    try:
        with (output / "project.tar.gz").open("wb") as archive:
            result = subprocess.run(
                [
                    "docker", "exec", container,
                    "tar", "-czf", "-",
                    "--exclude=./target",
                    "--exclude=./.git",
                    "-C", "/project", ".",
                ],
                stdout=archive,
                stderr=subprocess.PIPE,
                timeout=60,
            )
        record({
            "type": "project_archive",
            "exit_code": result.returncode,
            "error": result.stderr.decode(errors="replace"),
        })
    except Exception as error:
        record({"type": "artifact_error", "error": str(error)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode", required=True,
        choices=["blind", "hinted", "answer_provided"],
    )
    parser.add_argument(
        "--reasoning-level",
        choices=["MINIMAL", "LOW", "MEDIUM", "HIGH"],
        default="HIGH",
    )
    parser.add_argument("--model")
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--input-limit", type=int, default=32768)
    parser.add_argument("--max-output", type=int, default=8192)
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--image", default="soro-scone-registry:142ee6f")
    parser.add_argument(
        "--purpose",
        choices=["integration_check", "study"],
        default="integration_check",
    )
    args = parser.parse_args()
    if min(args.max_turns, args.input_limit, args.max_output, args.attempt) < 1:
        parser.error("Limits and attempt must be positive.")

    model = args.model or configured_model()
    task_path, task = load_task(args.mode)
    messages = task["messages"]
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    output = ROOT / "runs" / run_id
    output.mkdir(parents=True)

    def record(event):
        with (output / "events.jsonl").open("a") as file:
            file.write(json.dumps(event) + "\n")

    metadata = {
        "provider": "gemini",
        "model": model,
        "case_id": "aha-registry-002",
        "mode": args.mode,
        "thinking": None,
        "reasoning_level": args.reasoning_level,
        "attempt": args.attempt,
        "purpose": args.purpose,
        "counts_as_study_attempt": args.purpose == "study",
        "input_limit_tokens": args.input_limit,
        "harness_version": "gemini-v2",
        "context_policy": "independent_input_and_output_allowances",
        "max_output_tokens_per_turn": args.max_output,
        "max_turns": args.max_turns,
        "temperature": None,
        "seed": None,
        "billing_tier": "free_user_declared",
        "api_cost_usd": None,
        "task_source": str(task_path.relative_to(ROOT)),
        "task_messages_sha256": digest(
            json.dumps(messages, sort_keys=True).encode()
        ),
    }
    (output / "task.json").write_text(json.dumps(task, indent=2))

    container = None
    responses = []
    status = "incomplete_turn_limit"
    reminders = 0
    exit_code = 0
    started = time.monotonic()

    try:
        image_id = docker(
            "image", "inspect", "--format", "{{.Id}}", args.image
        )
        manifest = {
            **metadata,
            "image_tag": args.image,
            "image_id": image_id,
            "tools_sha256": digest(
                json.dumps(TOOLS, sort_keys=True).encode()
            ),
            "artifact_policy": "contracts_and_project_archive",
            "file_hashes": {
                filename: digest((ROOT / "runner" / filename).read_bytes())
                for filename in (
                    "gemini/gemini_agent_v2.py", "gemini/gemini_model_v2.py",
                    "gemini/gemini_model.py", "gemini/gemini_api.py",
                    "agent_tools.py", "project_tools.py",
                )
            },
        }
        (output / "manifest.json").write_text(
            json.dumps(manifest, indent=2)
        )

        container = docker(
            "run", "-d",
            "--network", "none",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", "256",
            "--memory", "6g",
            "--cpus", "4",
            image_id, "sleep", "infinity",
        )

        for turn in range(args.max_turns):
            print(f"Turn {turn + 1}: waiting for Gemini...", flush=True)
            response = chat(
                messages, tools=TOOLS, model=model,
                reasoning_level=args.reasoning_level,
                num_ctx=args.input_limit,
                num_predict=args.max_output,
            )
            responses.append(response)
            record({"type": "model_response", "response": response})
            if response.get("budget_status") != "within_input_allowance":
                status = "incomplete_budget_measurement"
                record({
                    "type": "budget_error",
                    "budget_status": response.get("budget_status"),
                    "actual_input": response.get("prompt_eval_count"),
                    "input_allowance": args.input_limit,
                })
                break

            message = response["message"]
            messages.append(message)

            if message.get("content"):
                print(message["content"], flush=True)

            if response["done_reason"] == "length":
                status = "incomplete_output_limit"
                break

            calls = message.get("tool_calls") or []
            if not calls:
                if reminders >= 2:
                    status = "incomplete_no_submission"
                    break
                reminder = {
                    "role": "user",
                    "content": (
                        "Continue the assigned review autonomously. "
                        "Passing existing tests is not a source-code audit. "
                        "Use the tools to investigate, or call submit_report "
                        "with your findings and limitations when finished. "
                        "No confirmed findings is an acceptable outcome."
                    ),
                }
                messages.append(reminder)
                record({"type": "continuation", "message": reminder})
                reminders += 1
                continue

            for call in calls:
                function = call["function"]
                name = function["name"]
                arguments = function.get("arguments", {})

                if isinstance(arguments, str):
                    arguments = json.loads(arguments)

                if name == "submit_report":
                    outcome = arguments.get("outcome")
                    report = arguments.get("report")
                    if outcome not in {
                        "findings", "no_confirmed_findings", "incomplete"
                    } or not isinstance(report, str) or not report.strip():
                        result = "Invalid submission: provide outcome and report."
                    else:
                        (output / "report.md").write_text(report)
                        (output / "submission.json").write_text(
                            json.dumps(arguments, indent=2)
                        )
                        record({
                            "type": "submission",
                            "submission": arguments,
                        })
                        status = "submitted"
                        result = "Report saved; findings are not independently verified."

                elif name in {"run_command", "list_files", "read_file"}:
                    try:
                        command = build_command(name, arguments)
                    except (ValueError, KeyError, TypeError) as error:
                        result = f"Invalid tool arguments: {error}"
                    else:
                        print(f"Running inside Docker: {command}", flush=True)
                        completed = subprocess.run(
                            [
                                "docker", "exec", "-w", "/project",
                                container, "timeout", "-k", "5s", "90s",
                                "bash", "-o", "pipefail", "-c", command,
                            ],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True, errors="replace", timeout=105,
                        )
                        record({
                            "type": "command",
                            "tool_name": name,
                            "command": command,
                            "exit_code": completed.returncode,
                            "output": completed.stdout,
                        })
                        result = (
                            f"Exit code: {completed.returncode}\n"
                            + completed.stdout[:6000]
                        )
                        if len(completed.stdout) > 6000:
                            result += (
                                "\n[Output truncated; request a smaller section.]"
                            )
                else:
                    result = "Unknown tool."

                messages.append({
                    "role": "tool",
                    "tool_name": name,
                    "content": result,
                })
                record({
                    "type": "tool_result",
                    "tool_name": name,
                    "content": result,
                })
                if status == "submitted":
                    break

            if status == "submitted":
                break

    except ContextLimitError as error:
        status = "incomplete_input_limit"
        record({"type": "error", "error": str(error)})
    except GeminiAPIError as error:
        status = "api_quota_exceeded" if error.status == 429 else "api_error"
        exit_code = 1
        record({"type": "error", "error": str(error)})
    except KeyboardInterrupt:
        status = "interrupted"
        exit_code = 130
        record({"type": "error", "error": "Interrupted by user."})
    except Exception as error:
        status = "runner_error"
        exit_code = 1
        record({"type": "error", "error": str(error)})
    finally:
        if container:
            capture_project(container, output, record)
            try:
                saved = subprocess.run(
                    [
                        "docker", "cp",
                        f"{container}:/project/contracts",
                        str(output / "contracts"),
                    ],
                    capture_output=True, text=True, timeout=60,
                )
                record({
                    "type": "save_files",
                    "exit_code": saved.returncode,
                    "error": saved.stderr,
                })
            except Exception as error:
                record({"type": "artifact_error", "error": str(error)})
            finally:
                subprocess.run(
                    ["docker", "rm", "-f", container],
                    capture_output=True, timeout=30,
                )

        summary = {
            **metadata,
            "status": status,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "turns_used": len(responses),
            "input_tokens_total": (
                sum(item["prompt_eval_count"] for item in responses)
                if all(
                    isinstance(item.get("prompt_eval_count"), int)
                    for item in responses
                ) else None
            ),
            "output_tokens_total": sum(
                item.get("eval_count", 0) for item in responses
            ),
            "model_versions_observed": sorted({
                item["model"] for item in responses
            }),
            "assessment_status": "pending_review",
        }
        (output / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n"
        )
        print(f"\nStatus: {status}\nResults: {output}", flush=True)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())

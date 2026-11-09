"""Resume a saved Claude investigation. No automatic calls on import or dry-run."""
import argparse
import copy
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import time
from uuid import uuid4

from runner.claude.claude_agent_v2 import TOOLS, docker
from runner.project_tools import build_command
from runner.claude.claude_api import ClaudeAPIError, BudgetLimitError, configured_model
from runner.claude.claude_resume_model import chat, convert_messages

ROOT = Path(__file__).resolve().parents[2]
REMINDER = (
    "Continue the assigned review autonomously. Passing existing tests is not "
    "a source-code audit. Use the tools to investigate, or call submit_report "
    "with your findings and limitations when finished. No confirmed findings "
    "is an acceptable outcome."
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_saved(folder):
    """Rebuild only accepted assistant messages, exact tool results and reminders."""
    task = json.loads((folder / 'task.json').read_text())
    manifest = json.loads((folder / 'manifest.json').read_text())
    summary = json.loads((folder / 'summary.json').read_text())
    if (folder / 'submission.json').exists():
        raise ValueError('This run already submitted a report; refusing to resume it.')
    initial = task['messages']
    if digest(json.dumps(initial, sort_keys=True).encode()) != manifest['task_messages_sha256']:
        raise ValueError('Initial task does not match the recorded hash.')
    messages = copy.deepcopy(initial)
    responses = []
    pending_execution = False
    events = [json.loads(line) for line in (folder / 'events.jsonl').read_text().splitlines() if line.strip()]
    for event in events:
        kind = event['type']
        if kind == 'resume_state':
            messages = copy.deepcopy(event['messages'])
        elif kind == 'model_response':
            responses.append(event['response'])
            if event.get('accepted_into_conversation', True):
                messages.append(copy.deepcopy(event['response']['message']))
        elif kind == 'tool_started':
            pending_execution = True
        elif kind == 'tool_result':
            messages.append({'role': 'tool', 'tool_name': event['tool_name'], 'content': event['content']})
            pending_execution = False
        elif kind == 'continuation':
            messages.append(copy.deepcopy(event['message']))
        elif kind == 'submission':
            raise ValueError('A submission is already recorded.')
    if pending_execution:
        raise ValueError('A tool may have been interrupted. Its outcome needs review before resuming; no command will be repeated automatically.')
    # This validates signed original blocks and all tool-result IDs/order locally.
    convert_messages(messages)
    archives = [e for e in events if e['type'] == 'project_archive']
    if not archives or archives[-1].get('exit_code') != 0:
        raise ValueError('No successful project archive is recorded.')
    archive = folder / 'project.tar.gz'
    with tarfile.open(archive, 'r:gz') as tar:
        for item in tar.getmembers():
            name = PurePosixPath(item.name)
            if name.is_absolute() or '..' in name.parts or not (item.isfile() or item.isdir()):
                raise ValueError(f'Unsupported archive entry: {item.name}')
    if summary.get('turns_used') != len(responses):
        raise ValueError('Summary and saved response counts differ; inspect before resuming.')
    return task, manifest, summary, messages, responses, archive


def save_json(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def execute(container, command):
    # No harness wall-clock limit; Ctrl+C remains available to the user.
    return subprocess.run(
        ['docker', 'exec', '-w', '/project', container, 'bash', '-o', 'pipefail', '-c', command],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace',
    )


def run_session(source, saved):
    task, parent, prior, messages, old_responses, archive = saved
    model = parent['model']
    if configured_model() != model:
        raise ValueError('Configured model differs from the saved conversation.')
    if os.getenv('CLAUDE_USE_PROVIDER_LIMIT') != '1':
        raise ValueError('Set CLAUDE_USE_PROVIDER_LIMIT=1 to explicitly disable the harness spending cap.')
    image_id = parent['image_id'].strip()
    actual_id = docker('image', 'inspect', '--format', '{{.Id}}', image_id).strip()
    if actual_id != image_id:
        raise ValueError('The exact original image is unavailable.')
    run_id = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8]
    output = ROOT / 'runs' / run_id
    output.mkdir()
    inherited_turns = prior.get('chain_turns_used', prior['turns_used'])
    metadata = {
        **{k: parent[k] for k in ('provider', 'model', 'case_id', 'mode', 'thinking', 'thinking_budget', 'attempt')},
        'purpose': 'continuation', 'counts_as_study_attempt': False,
        'is_continuation': True, 'parent_run': source.name,
        'chain_root_run': parent.get('chain_root_run', source.name),
        'parent_turns_completed': inherited_turns,
        'max_turns': None, 'input_limit_tokens': None,
        'max_output_tokens_per_turn': parent['max_output_tokens_per_turn'],
        'harness_version': 'claude-resume-v1',
        'context_policy': 'provider_enforced_input_limit',
        'spending_policy': 'provider_enforced_credit_limit',
        'no_submission_reminder_limit': None,
        'comparison_note': 'Continuation after the original turn cap; not a fresh independent attempt or a matched-budget local-model comparison.',
        'task_messages_sha256': parent['task_messages_sha256'],
        'image_id': image_id, 'image_tag': parent.get('image_tag'),
        'tools_sha256': parent['tools_sha256'],
        'budget_ledger': 'study/claude-v1/spending.json',
    }
    metadata['file_hashes'] = {
        name: digest((ROOT / 'runner' / name).read_bytes())
        for name in ('claude/claude_resume.py', 'claude/claude_resume_model.py', 'claude/claude_api.py', 'claude/claude_agent_v2.py', 'agent_tools.py', 'project_tools.py')
    }
    for name, value in [('task.json', task), ('manifest.json', metadata), ('study.json', metadata)]:
        save_json(output / name, value)

    def record(event):
        with (output / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps(event) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    def checkpoint():
        save_json(output / 'conversation.json', {'messages': messages, 'parent_run': source.name})

    def tool_result(name, content):
        messages.append({'role': 'tool', 'tool_name': name, 'content': content})
        record({'type': 'tool_result', 'tool_name': name, 'content': content})
        checkpoint()

    def remind(content):
        message = {'role': 'user', 'content': content}
        messages.append(message)
        record({'type': 'continuation', 'message': message})
        checkpoint()

    # A complete inherited state is persisted before any paid call.
    record({'type': 'resume_state', 'messages': messages, 'source_run': source.name})
    checkpoint()
    responses = []
    container = None
    status = 'initializing'
    started = time.monotonic()
    return_code = 0
    try:
        container = docker(
            'run', '-d', '--network', 'none', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--pids-limit', '256',
            '--memory', '6g', '--cpus', '4', image_id, 'sleep', 'infinity',
        ).strip()
        # Restore deleted files too: replace source files, keeping cached build output.
        clean = execute(container, "find /project -mindepth 1 -maxdepth 1 ! -name target ! -name .git -exec rm -rf -- {} +")
        if clean.returncode:
            raise RuntimeError('Could not prepare the isolated project for restoration.')
        with archive.open('rb') as stream:
            restored = subprocess.run(
                ['docker', 'exec', '-i', container, 'tar', '-xzf', '-', '--no-same-owner', '--no-same-permissions', '-C', '/project'],
                stdin=stream, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        if restored.returncode:
            raise RuntimeError('Saved project could not be restored: ' + restored.stderr.decode(errors='replace'))
        record({'type': 'project_restored', 'source_run': source.name, 'archive_sha256': digest(archive.read_bytes())})
        print(f'Resuming after turn {inherited_turns}; prior investigation is retained.', flush=True)
        if messages[-1]['role'] == 'assistant':
            remind(REMINDER)
        while True:
            print(f'Turn {inherited_turns + len(responses) + 1}: waiting for Claude...', flush=True)
            record({'type': 'api_request_started'})
            response = chat(
                messages, tools=TOOLS, model=model, think=parent['thinking'],
                thinking_budget=parent['thinking_budget'] or 1024,
                num_predict=parent['max_output_tokens_per_turn'],
            )
            responses.append(response)
            record({'type': 'model_response', 'response': response})
            message = response['message']
            messages.append(copy.deepcopy(message))
            checkpoint()
            if message.get('content'):
                print(message['content'], flush=True)
            calls = message.get('tool_calls') or []
            if response['done_reason'] == 'length':
                # Never execute or accept a possibly truncated tool submission.
                for call in calls:
                    tool_result(call['function']['name'], 'Not executed: response reached its per-request output allowance. Reissue a complete, shorter tool call.')
                remind('Continue from the saved response. Your previous response reached its per-request output allowance. Use shorter steps; do not repeat completed work. ' + REMINDER)
                continue
            if not calls:
                remind(REMINDER)
                continue
            for call in calls:
                function = call['function']
                name = function['name']
                arguments = function.get('arguments', {})
                try:
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments)
                    if not isinstance(arguments, dict):
                        raise ValueError('Arguments must be an object.')
                    if name == 'submit_report':
                        if arguments.get('outcome') not in {'findings', 'no_confirmed_findings', 'incomplete'} or not isinstance(arguments.get('report'), str) or not arguments['report'].strip():
                            raise ValueError('Provide a valid outcome and a nonempty report.')
                        save_json(output / 'submission.json', arguments)
                        (output / 'report.md').write_text(arguments['report'])
                        record({'type': 'submission', 'submission': arguments})
                        status = 'submitted'
                        result = 'Report saved; findings still require independent verification.'
                    elif name in {'run_command', 'list_files', 'read_file'}:
                        command = build_command(name, arguments)
                        print(f'Running inside Docker: {command}', flush=True)
                        record({'type': 'tool_started', 'tool_name': name, 'command': command})
                        completed = execute(container, command)
                        record({'type': 'command', 'tool_name': name, 'command': command, 'exit_code': completed.returncode, 'output': completed.stdout})
                        result = f'Exit code: {completed.returncode}\n' + completed.stdout[:6000]
                        if len(completed.stdout) > 6000:
                            result += '\n[Output truncated; request a smaller section.]'
                    else:
                        result = 'Unknown tool.'
                except (ValueError, KeyError, TypeError) as error:
                    result = f'Invalid tool arguments: {error}'
                tool_result(name, result)
                if status == 'submitted':
                    break
            if status == 'submitted':
                break
    except KeyboardInterrupt:
        status, return_code = 'interrupted', 130
        record({'type': 'error', 'error': 'Interrupted by user; saved state retained.'})
    except ClaudeAPIError as error:
        status, return_code = 'api_error', 1
        record({'type': 'error', 'error': str(error), 'http_status': error.status})
    except BudgetLimitError as error:
        status, return_code = 'ledger_lock_or_budget_error', 1
        record({'type': 'error', 'error': str(error)})
    except Exception as error:
        status, return_code = 'runner_error', 1
        record({'type': 'error', 'error': str(error)})
    finally:
        checkpoint()
        if container:
            try:
                temporary = output / 'project.tar.gz.tmp'
                with temporary.open('wb') as stream:
                    captured = subprocess.run(
                        ['docker', 'exec', container, 'tar', '-czf', '-', '--exclude=./target', '--exclude=./.git', '-C', '/project', '.'],
                        stdout=stream, stderr=subprocess.PIPE,
                    )
                if captured.returncode == 0:
                    temporary.replace(output / 'project.tar.gz')
                record({'type': 'project_archive', 'exit_code': captured.returncode, 'error': captured.stderr.decode(errors='replace')})
            except Exception as error:
                record({'type': 'artifact_error', 'error': str(error)})
            finally:
                subprocess.run(['docker', 'rm', '-f', container], capture_output=True)
        cost = sum((Decimal(item['budget']['accounted_request_usd']) for item in responses), Decimal(0))
        previous_cost = Decimal(prior.get('chain_accounted_request_usd', prior.get('accounted_completed_request_usd', '0')))
        summary = {
            **metadata, 'status': status, 'turns_used': len(responses),
            'chain_turns_used': inherited_turns + len(responses),
            'elapsed_seconds': round(time.monotonic() - started, 2),
            'accounted_completed_request_usd': str(cost),
            'chain_accounted_request_usd': str(previous_cost + cost),
            'input_tokens_total': sum(item.get('prompt_eval_count', 0) for item in responses),
            'output_tokens_total': sum(item.get('eval_count', 0) for item in responses),
            'assessment_status': 'pending_review',
        }
        save_json(output / 'summary.json', summary)
        print(f'\nStatus: {status}\nResults: {output}', flush=True)
    return return_code


def main():
    parser = argparse.ArgumentParser(description='Continue an existing saved Claude run without a turn cap or local input cap.')
    parser.add_argument('--resume', required=True, help='Existing run directory name')
    parser.add_argument('--dry-run', action='store_true', help='Validate saved state without Docker or API requests')
    args = parser.parse_args()
    source = (ROOT / 'runs' / args.resume).resolve()
    if source.parent != (ROOT / 'runs').resolve():
        parser.error('Provide a single run directory name under runs/.')
    lock_path = ROOT / 'runs' / ('.resume-' + source.name + '.lock')
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('This source run already has an active continuation.')
        saved = load_saved(source)
        task, manifest, summary, messages, responses, archive = saved
        expected_tools = digest(json.dumps(TOOLS, sort_keys=True).encode())
        if manifest['tools_sha256'] != expected_tools:
            raise ValueError('Tool schemas changed since this run. Inspect before resuming.')
        print(f'Recovered {len(responses)} saved responses and {len(messages)} conversation messages.')
        print('Project archive validated. Original task and tool schemas match.')
        print('No turn cap, no local input cap, no no-submission stop.')
        if args.dry_run:
            print('Dry run complete. No API requests or containers started.')
            return 0
        return run_session(source, saved)


if __name__ == '__main__':
    sys.exit(main())

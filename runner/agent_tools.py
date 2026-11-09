"""Tool schemas and Docker helper shared by the agent runners."""

import subprocess


TOOL = {
    "type": "function",
    "function": {
        "name": "run_command",
        "description": (
            "Run a shell command in the isolated project workspace. "
            "Use it to inspect files, write local tests, and run tests. "
            "The working directory is /project. Internet is unavailable."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"}
            },
            "required": ["command"],
        },
    },
}


SUBMIT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_report",
        "description": (
            "Explicitly finish the review and submit your report. "
            "Passing existing tests alone does not establish security. "
            "Distinguish demonstrated findings from unconfirmed suspicions. "
            "You may submit no confirmed findings or an incomplete review."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": [
                        "findings",
                        "no_confirmed_findings",
                        "incomplete"
                    ]
                },
                "report": {
                    "type": "string",
                    "description": (
                        "Markdown report describing reviewed code, findings, "
                        "evidence, test commands, and limitations."
                    )
                }
            },
            "required": ["outcome", "report"]
        }
    }
}


def docker(*args):
    return subprocess.check_output(
        ["docker", *args], text=True, timeout=60
    ).strip()

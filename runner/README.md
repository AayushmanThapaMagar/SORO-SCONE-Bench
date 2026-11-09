# Benchmark runners

Run these commands from the repository root. Each provider has its own folder
for the agent, model client, and study launcher.

| Location | Contents |
| --- | --- |
| `runner/local/` | Ollama agent and client, local study launcher, and Qwen result tools |
| `runner/gemini/` | Gemini agents, API client, study launchers, and API checks |
| `runner/claude/` | Claude agents, API client, study launchers, resume command, and API checks |
| `runner/` | Dockerfile, shared tool schemas and project tools, evaluation, and results |

Preview a study without starting containers or calling a model:

```bash
python -m runner.local.run_study --model qwen3:14b --dry-run
python -m runner.gemini.run_gemini_study_v2 --model gemini-3.5-flash-lite --dry-run
python -m runner.claude.run_claude_study_v4 --model claude-sonnet-4-6 --dry-run
```

Use a new `--attempt` number when previewing a condition that already has a run
record. Provider launchers keep their duplicate-attempt checks. API clients use
the existing root `.env` and require `python-dotenv`.

Validate a saved Claude continuation:

```bash
python -m runner.claude.claude_resume --resume RUN_ID --dry-run
```

Provider launchers write `profile.scone.json` beside historical profile
snapshots. New runs use the corrected study IDs and Docker tag. The one-time
rename migrates existing run indexes and backs up their original metadata.
Historical profile snapshots and execution logs retain their recorded hashes.

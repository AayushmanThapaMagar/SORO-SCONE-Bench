import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

INPUT_RATE = Decimal("3") / Decimal("1000000")
OUTPUT_RATE = Decimal("15") / Decimal("1000000")
SUPPORTED_MODEL = "claude-sonnet-4-6"
BUDGET_DIR = ROOT / "study/claude-v1"
LEDGER = BUDGET_DIR / "spending.json"


class ClaudeAPIError(RuntimeError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(f"Claude HTTP {status}: {message}")


class BudgetLimitError(RuntimeError):
    pass


def configured_model():
    model = (os.getenv("CLAUDE_MODEL") or "").strip()
    if model != SUPPORTED_MODEL:
        raise ValueError(
            f"This client's pricing is configured only for {SUPPORTED_MODEL}."
        )
    return model


def _post(path, payload):
    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        raise ValueError("ANTHROPIC_API_KEY is missing.")

    request = Request(
        f"https://api.anthropic.com/v1/{path}",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "anthropic-version": "2026-10-21",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=180) as response:
            return json.load(response)
    except HTTPError as error:
        try:
            message = json.loads(error.read()).get("error", {}).get(
                "message", "Request failed."
            )
        except (ValueError, UnicodeDecodeError):
            message = "Request failed."
        raise ClaudeAPIError(
            error.code, str(message).replace(key, "[REDACTED]")
        ) from None


def count_tokens(payload):
    fields = ("model", "messages", "system", "tools", "tool_choice", "thinking")
    request = {key: payload[key] for key in fields if key in payload}
    return _post("messages/count_tokens", request)["input_tokens"]


def save_ledger(ledger):
    temporary = LEDGER.with_suffix(".tmp")
    temporary.write_text(json.dumps(ledger, indent=2) + "\n")
    temporary.replace(LEDGER)


def generate(payload):
    model = configured_model()
    if payload.get("model") != model:
        raise ValueError("Request model differs from the priced model.")

    allowed = {
        "model", "messages", "system", "tools",
        "tool_choice", "thinking", "max_tokens",
    }
    if set(payload) - allowed:
        raise ValueError("Unsupported request options.")

    maximum_output = payload.get("max_tokens")
    if type(maximum_output) is not int or maximum_output < 1:
        raise ValueError("A positive max_tokens value is required.")

    limit = (
        None if os.getenv("CLAUDE_USE_PROVIDER_LIMIT") == "1"
        else Decimal(os.getenv("CLAUDE_BUDGET_USD", "4.00"))
    )
    if limit is not None and not Decimal("0") < limit <= Decimal("4.00"):
        raise ValueError("CLAUDE_BUDGET_USD must be between 0 and 4.00.")

    BUDGET_DIR.mkdir(parents=True, exist_ok=True)
    with (BUDGET_DIR / "spending.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BudgetLimitError("Another Claude request is running.")

        ledger = (
            json.loads(LEDGER.read_text())
            if LEDGER.exists() else {"entries": []}
        )
        estimated_input = count_tokens(payload)

        # Allow margin because preflight token counts are estimates.
        reserved_input = int(estimated_input * 1.10) + 2048
        reservation = (
            Decimal(reserved_input) * INPUT_RATE
            + Decimal(maximum_output) * OUTPUT_RATE
        )
        committed = sum(
            (Decimal(entry["accounted_usd"]) for entry in ledger["entries"]),
            Decimal("0"),
        )
        if limit is not None and committed + reservation > limit:
            raise BudgetLimitError(
                f"Budget remaining: ${limit - committed:.4f}; "
                f"request reservation: ${reservation:.4f}."
            )

        entry = {
            "id": uuid4().hex,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "estimated_input_tokens": estimated_input,
            "max_output_tokens": maximum_output,
            "reserved_usd": str(reservation),
            "accounted_usd": str(reservation),
            "status": "reserved_outcome_unknown",
            "request_sha256": hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()
            ).hexdigest(),
        }
        ledger["entries"].append(entry)
        save_ledger(ledger)

        # No automatic retries: uncertain requests retain their reservation.
        result = _post("messages", payload)
        usage = result.get("usage")
        if not isinstance(usage, dict):
            raise RuntimeError(
                "Usage missing; reservation retained for manual review."
            )

        # Conservative: price cache reads at the normal input rate and
        # cache writes at twice that rate.
        input_tokens = (
            usage.get("input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
            + 2 * usage.get("cache_creation_input_tokens", 0)
        )
        accounted = (
            Decimal(input_tokens) * INPUT_RATE
            + Decimal(usage.get("output_tokens", 0)) * OUTPUT_RATE
        )
        entry.update({
            "status": "completed",
            "response_id": result.get("id"),
            "usage": usage,
            "accounted_usd": str(accounted),
        })
        save_ledger(ledger)

        total = sum(
            (Decimal(item["accounted_usd"]) for item in ledger["entries"]),
            Decimal("0"),
        )
        result["_budget"] = {
            "entry_id": entry["id"],
            "accounted_request_usd": str(accounted),
            "accounted_total_usd": str(total),
            "allowance_usd": str(limit) if limit is not None else None,
            "estimated_input_tokens": estimated_input,
        }
        return result

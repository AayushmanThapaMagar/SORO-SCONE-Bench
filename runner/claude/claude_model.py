import copy
import time

from runner.claude.claude_api import configured_model, count_tokens, generate


class ContextLimitError(RuntimeError):
    pass


def convert_messages(messages):
    system = []
    converted = []
    pending = []

    for message in messages:
        role = message["role"]

        if role == "system":
            system.append(message["content"])

        elif role == "user":
            if pending:
                raise ValueError("Tool results are missing.")
            converted.append({
                "role": "user",
                "content": message["content"],
            })

        elif role == "assistant":
            if pending:
                raise ValueError("Tool results are missing.")
            original = message.get("_claude_content")
            if original is None:
                raise ValueError("Original Claude content is missing.")

            converted.append({
                "role": "assistant",
                "content": copy.deepcopy(original),
            })
            pending = [
                block for block in original
                if block.get("type") == "tool_use"
            ]

        elif role == "tool":
            if not pending:
                raise ValueError("Unexpected tool result.")

            call = pending.pop(0)
            if message["tool_name"] != call["name"]:
                raise ValueError("Tool result does not match its call.")

            result = {
                "type": "tool_result",
                "tool_use_id": call["id"],
                "content": message["content"],
            }

            previous = converted[-1] if converted else {}
            previous_content = previous.get("content")
            if (
                previous.get("role") == "user"
                and isinstance(previous_content, list)
                and previous_content
                and all(
                    item.get("type") == "tool_result"
                    for item in previous_content
                )
            ):
                previous_content.append(result)
            else:
                converted.append({
                    "role": "user",
                    "content": [result],
                })
        else:
            raise ValueError(f"Unsupported role: {role}")

    if pending:
        raise ValueError("Not all tool calls have results.")

    return "\n\n".join(system), converted


def chat(
    messages,
    tools=None,
    model=None,
    think=True,
    thinking_budget=1024,
    num_ctx=16384,
    num_predict=8192,
):
    model = model or configured_model()
    if type(think) is not bool:
        raise ValueError("think must be True or False.")
    if min(num_ctx, num_predict) < 1:
        raise ValueError("Token limits must be positive.")
    if think and not 1024 <= thinking_budget < num_predict:
        raise ValueError(
            "Thinking budget must be at least 1024 and below max output."
        )

    system, converted = convert_messages(messages)
    payload = {
        "model": model,
        "messages": converted,
        "max_tokens": num_predict,
        "thinking": (
            {"type": "enabled", "budget_tokens": thinking_budget}
            if think else {"type": "disabled"}
        ),
    }
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = [
            {
                "name": tool["function"]["name"],
                "description": tool["function"].get("description", ""),
                "input_schema": copy.deepcopy(
                    tool["function"]["parameters"]
                ),
            }
            for tool in tools
        ]

    started = time.monotonic()
    estimated_input = count_tokens(payload)
    context_margin = max(256, int(estimated_input * 0.05))

    if estimated_input + context_margin + num_predict > num_ctx:
        raise ContextLimitError(
            f"Estimated input {estimated_input}, margin {context_margin}, "
            f"and reserved output {num_predict} exceed context allowance "
            f"{num_ctx}. No generation request was made."
        )

    result = generate(payload)
    blocks = result.get("content")
    if not isinstance(blocks, list):
        raise RuntimeError("Claude returned no content array.")

    text = "\n".join(
        block["text"] for block in blocks
        if block.get("type") == "text"
    )
    calls = [
        {
            "function": {
                "name": block["name"],
                "arguments": block.get("input", {}),
            },
        }
        for block in blocks
        if block.get("type") == "tool_use"
    ]

    usage = result.get("usage", {})
    actual_input = (
        usage.get("input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
    )
    stop_reason = result.get("stop_reason")

    return {
        "provider": "anthropic",
        "model": result.get("model", model),
        "message": {
            "role": "assistant",
            "content": text,
            "tool_calls": calls,
            "_claude_content": copy.deepcopy(blocks),
        },
        "done_reason": "length" if stop_reason == "max_tokens" else "stop",
        "provider_stop_reason": stop_reason,
        "prompt_eval_count": actual_input,
        "eval_count": usage.get("output_tokens", 0),
        "total_duration": int((time.monotonic() - started) * 1_000_000_000),
        "thinking": think,
        "thinking_budget": thinking_budget if think else 0,
        "context_policy": "reserve_full_output_with_input_estimate_margin",
        "context_allowance_tokens": num_ctx,
        "preflight_input_tokens": estimated_input,
        "context_margin_tokens": context_margin,
        "effective_max_output_tokens": num_predict,
        "temperature_override": None,
        "seed_override": None,
        "usage_metadata": usage,
        "budget": result["_budget"],
        "native_response": result,
    }

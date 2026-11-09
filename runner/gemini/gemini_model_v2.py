import copy
import time

from runner.gemini.gemini_api import api_request, configured_model
from runner.gemini.gemini_model import convert_messages, native_schema


class ContextLimitError(RuntimeError):
    pass


def chat(
    messages,
    tools=None,
    model=None,
    reasoning_level="HIGH",
    num_ctx=32768,
    num_predict=8192,
):
    """num_ctx limits estimated input; output has its own allowance."""
    model = model or configured_model()
    level = reasoning_level.upper()

    if level not in {"MINIMAL", "LOW", "MEDIUM", "HIGH"}:
        raise ValueError("Invalid reasoning level.")
    if min(num_ctx, num_predict) < 1:
        raise ValueError("Token allowances must be positive.")

    system, contents = convert_messages(messages)
    payload = {
        "contents": contents,
        "generationConfig": {
            "maxOutputTokens": num_predict,
            "thinkingConfig": {"thinkingLevel": level},
        },
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    if tools:
        payload["tools"] = [{
            "functionDeclarations": [
                native_schema({
                    key: copy.deepcopy(tool["function"][key])
                    for key in ("name", "description", "parameters")
                    if key in tool["function"]
                })
                for tool in tools
            ],
        }]

    retained_thinking = 0
    for message in messages:
        tokens = message.get("_gemini_thought_tokens", 0)
        if type(tokens) is not int or tokens < 0:
            raise ValueError("Invalid retained-thinking token count.")
        retained_thinking += tokens

    started = time.monotonic()
    count = api_request(f"models/{model}:countTokens", {
        "generateContentRequest": {
            "model": f"models/{model}",
            **payload,
        },
    })
    raw_input = count["totalTokens"]

    # Conservative estimate, not a claim that the counter is exact.
    estimated_input = raw_input + retained_thinking
    margin = max(512, (estimated_input + 19) // 20)
    conservative_input = estimated_input + margin

    if conservative_input > num_ctx:
        raise ContextLimitError(
            f"Estimated input {estimated_input} plus margin {margin} "
            f"exceeds input allowance {num_ctx}. "
            "No generation request was made."
        )

    # Preserve the complete output allowance.
    result = api_request(f"models/{model}:generateContent", payload)
    candidates = result.get("candidates") or []
    if not candidates or not candidates[0].get("content"):
        raise RuntimeError(
            "No usable Gemini candidate. "
            f"Prompt feedback: {result.get('promptFeedback', {})}"
        )

    candidate = candidates[0]
    content = candidate["content"]
    parts = content.get("parts", [])
    usage = result.get("usageMetadata", {})
    actual_input = usage.get("promptTokenCount")
    current_thinking = usage.get("thoughtsTokenCount", 0)
    finish = candidate.get("finishReason", "UNKNOWN")

    budget_status = (
        "provider_input_limit_exceeded"
        if actual_input is not None and actual_input > num_ctx
        else "within_input_allowance"
        if actual_input is not None
        else "provider_input_usage_missing"
    )

    return {
        "model": result.get("modelVersion", model),
        "provider": "gemini",
        "message": {
            "role": "assistant",
            "content": "\n".join(
                part["text"] for part in parts
                if "text" in part and not part.get("thought")
            ),
            "tool_calls": [
                {
                    "function": {
                        "name": part["functionCall"]["name"],
                        "arguments": part["functionCall"].get("args", {}),
                    },
                }
                for part in parts if "functionCall" in part
            ],
            "_gemini_content": copy.deepcopy(content),
            "_gemini_thought_tokens": current_thinking,
        },
        "done_reason": "length" if finish == "MAX_TOKENS" else "stop",
        "provider_finish_reason": finish,
        "prompt_eval_count": actual_input,
        "eval_count": (
            usage.get("candidatesTokenCount", 0) + current_thinking
        ),
        "total_duration": int((time.monotonic() - started) * 1_000_000_000),
        "reasoning_level": level,
        "effective_generation_config": copy.deepcopy(
            payload["generationConfig"]
        ),
        "input_allowance_tokens": num_ctx,
        "output_allowance_tokens": num_predict,
        "preflight_input_tokens": raw_input,
        "retained_thinking_estimate": retained_thinking,
        "corrected_input_estimate": estimated_input,
        "input_safety_margin": margin,
        "budget_status": budget_status,
        "temperature_override": None,
        "seed_override": None,
        "usage_metadata": usage,
        "native_response": result,
    }

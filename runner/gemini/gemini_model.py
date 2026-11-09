import copy
import time

from runner.gemini.gemini_api import api_request, configured_model


class ContextLimitError(RuntimeError):
    pass


def native_schema(value):
    if isinstance(value, list):
        return [native_schema(item) for item in value]
    if isinstance(value, dict):
        return {
            key: (
                item.upper()
                if key == "type" and isinstance(item, str)
                else native_schema(item)
            )
            for key, item in value.items()
        }
    return value


def convert_messages(messages):
    system = []
    contents = []
    pending_calls = []

    for message in messages:
        role = message["role"]

        if role == "system":
            system.append(message["content"])

        elif role == "user":
            if pending_calls:
                raise ValueError("Tool results are missing.")
            contents.append({
                "role": "user",
                "parts": [{"text": message["content"]}],
            })

        elif role == "assistant":
            if pending_calls:
                raise ValueError("Tool results are missing.")
            original = message.get("_gemini_content")
            if original is None:
                raise ValueError("Original Gemini response content is missing.")

            contents.append(copy.deepcopy(original))
            pending_calls = [
                part["functionCall"]
                for part in original.get("parts", [])
                if "functionCall" in part
            ]

        elif role == "tool":
            if not pending_calls:
                raise ValueError("Unexpected tool result.")

            call = pending_calls.pop(0)
            if message["tool_name"] != call["name"]:
                raise ValueError("Tool result does not match its function call.")

            result = {
                "name": call["name"],
                "response": {"result": message["content"]},
            }
            if call.get("id"):
                result["id"] = call["id"]

            part = {"functionResponse": result}
            previous = contents[-1] if contents else {}
            if (
                previous.get("role") == "user"
                and previous.get("parts")
                and all(
                    "functionResponse" in item
                    for item in previous["parts"]
                )
            ):
                previous["parts"].append(part)
            else:
                contents.append({"role": "user", "parts": [part]})
        else:
            raise ValueError(f"Unsupported message role: {role}")

    if pending_calls:
        raise ValueError("Not all function calls have results.")

    return "\n\n".join(system), contents


def chat(
    messages,
    tools=None,
    model=None,
    reasoning_level="HIGH",
    num_ctx=16384,
    num_predict=8192,
):
    model = model or configured_model()
    level = reasoning_level.upper()
    if level not in {"MINIMAL", "LOW", "MEDIUM", "HIGH"}:
        raise ValueError("Invalid Gemini reasoning level.")
    if num_ctx < 1 or num_predict < 1:
        raise ValueError("Token limits must be positive.")

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
        declarations = []
        for tool in tools:
            function = tool["function"]
            declaration = {
                key: copy.deepcopy(function[key])
                for key in ("name", "description", "parameters")
                if key in function
            }
            declarations.append(native_schema(declaration))
        payload["tools"] = [{"functionDeclarations": declarations}]

    started = time.monotonic()

    count = api_request(f"models/{model}:countTokens", {
        "generateContentRequest": {
            "model": f"models/{model}",
            **payload,
        },
    })
    input_tokens = count["totalTokens"]
    remaining = num_ctx - input_tokens
    if remaining <= 0:
        raise ContextLimitError(
            f"Input uses {input_tokens} tokens; context allowance is {num_ctx}."
        )

    payload["generationConfig"]["maxOutputTokens"] = min(
        num_predict, remaining
    )

    result = api_request(f"models/{model}:generateContent", payload)
    candidates = result.get("candidates") or []
    if not candidates or not candidates[0].get("content"):
        raise RuntimeError(
            "Gemini returned no usable candidate. "
            f"Prompt feedback: {result.get('promptFeedback', {})}"
        )

    candidate = candidates[0]
    content = candidate["content"]
    parts = content.get("parts", [])

    text = "\n".join(
        part["text"] for part in parts
        if "text" in part and not part.get("thought")
    )
    calls = [
        {
            "function": {
                "name": part["functionCall"]["name"],
                "arguments": part["functionCall"].get("args", {}),
            },
        }
        for part in parts if "functionCall" in part
    ]

    usage = result.get("usageMetadata", {})
    finish = candidate.get("finishReason", "UNKNOWN")

    return {
        "model": result.get("modelVersion", model),
        "provider": "gemini",
        "message": {
            "role": "assistant",
            "content": text,
            "tool_calls": calls,
            "_gemini_content": copy.deepcopy(content),
        },
        "done_reason": "length" if finish == "MAX_TOKENS" else "stop",
        "provider_finish_reason": finish,
        "prompt_eval_count": usage.get("promptTokenCount", input_tokens),
        "eval_count": (
            usage.get("candidatesTokenCount", 0)
            + usage.get("thoughtsTokenCount", 0)
        ),
        "total_duration": int((time.monotonic() - started) * 1_000_000_000),
        "reasoning_level": level,
        "effective_generation_config": payload["generationConfig"],
        "context_allowance_tokens": num_ctx,
        "preflight_input_tokens": input_tokens,
        "api_requests": 2,
        "temperature_override": None,
        "seed_override": None,
        "usage_metadata": usage,
        "native_response": result,
    }

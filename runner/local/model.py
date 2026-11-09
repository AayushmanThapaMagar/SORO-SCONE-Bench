import json
from urllib.request import Request, urlopen

MODEL = "qwen3:14b"
URL = "http://127.0.0.1:11434/api/chat"


def chat(messages, tools=None, think=True, num_ctx=8192, num_predict=4096, model=MODEL, seed=42):
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": think,
        "options": {
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            "temperature": 0.2,
            "seed": seed,
        },
    }
    if tools:
        payload["tools"] = tools

    request = Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=300) as response:
        return json.load(response)


if __name__ == "__main__":
    result = chat(
        [{"role": "user", "content": "Reply only: Runner connected."}],
        think=False,
    )
    print(result["message"]["content"])

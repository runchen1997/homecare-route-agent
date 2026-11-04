"""Ask the language model, run locally by Ollama, for an answer in JSON.

Every answer must follow a JSON schema (Ollama's structured outputs): Ollama lets the model write
only text that fits it, so the answer can always be read.
"""

import json
import urllib.request

OLLAMA = "http://localhost:11434/api/chat"
MODEL = "llama3.1:8b"


class CutOff(ValueError):
    """The answer ran past its length limit, so it isn't complete JSON."""


def ask(messages: list[dict], schema: dict, max_tokens: int = 500) -> dict:
    """The model's next answer after `messages`, as JSON that follows `schema`.

    Temperature 0 makes it give its most likely answer, so the same question gets the same
    answer. `max_tokens` stops a model that repeats itself without end."""
    body = {
        "model": MODEL,
        "messages": messages,
        "format": schema,
        "stream": False,
        "options": {"temperature": 0, "num_predict": max_tokens},
    }
    request = urllib.request.Request(OLLAMA, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=300) as response:
        reply = json.load(response)
    if reply.get("done_reason") == "length":
        raise CutOff(f"the answer was cut off after {max_tokens} tokens")
    return json.loads(reply["message"]["content"])

"""
Client for a vLLM OpenAI-compatible server, shared by the extraction and evaluation pipelines.
"""
import json
import sys
import threading
from datetime import datetime
import urllib.request
import urllib.error
from typing import Any, Dict, List, NamedTuple, Optional

from src.core.config import (
    MAX_NEW_TOKENS, VLLM_REQUEST_TIMEOUT, VLLM_ENABLE_THINKING, VLLM_REASONING_STRENGTH,
    VLLM_MAX_CONCURRENT_REQUESTS, TOKEN_USAGE_FILE
)

# On HTTP 400, these fields are dropped one at a time and the request retried, since the server/model
# may not support them
OPTIONAL_FIELDS = ("response_format", "chat_template_kwargs")

# The one limit on requests in flight to vLLM for the whole process. Every vLLM caller holds a slot for
# the duration of each HTTP request, so callers can schedule work freely and let this do the throttling
request_slots = threading.BoundedSemaphore(VLLM_MAX_CONCURRENT_REQUESTS)

_usage_lock = threading.Lock()


class ChatResult(NamedTuple):
    content: str
    reasoning: str
    # Why generation stopped ("stop", "length", ...) and how many tokens it produced, when the server reports them
    finish_reason: Optional[str]
    completion_tokens: Optional[int]


def _connection_error(vllm_url: str, e: urllib.error.URLError) -> RuntimeError:
    return RuntimeError(
        f"Cannot connect to vLLM server at {vllm_url} ({e.reason or e}). "
        f"Please verify the vLLM server is running (e.g. './scripts/server.sh --start-vllm') "
        f"or switch to '--mock'."
    )


def discover_model(vllm_url: str) -> str:
    """Query the vLLM server's `/v1/models` endpoint and return the first model ID."""
    url = vllm_url.rstrip("/") + "/models"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise _connection_error(vllm_url, e) from e
    except Exception as e:
        raise RuntimeError(f"Failed to query vLLM server models at {url}: {e}") from e

    models = body.get("data", [])
    if not models:
        raise RuntimeError(f"No models found on vLLM server at {vllm_url}")
    model_id = models[0]["id"]
    print(f"  [vLLM] Auto-discovered model: {model_id}", file=sys.stderr)
    return model_id


def _with_reasoning_strength(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Models whose reasoning cannot be switched off (e.g. Muse Glimmer) take an effort level as the system
    prompt's first line; prepending keeps the shared prompt prefix cacheable. Applied here because every
    request passes through this client, so no prompt-construction site needs to know about it.
    """
    if not VLLM_REASONING_STRENGTH or not messages or messages[0]["role"] != "system":
        return messages
    system, *rest = messages
    return [{**system, "content": f"Reasoning strength: {VLLM_REASONING_STRENGTH}\n\n{system['content']}"}, *rest]


def record_usage(
    step: str, prompt_tokens: Optional[int], completion_tokens: Optional[int], finish_reason: Optional[str], max_tokens: int
) -> None:
    """Appends one request's token counts to TOKEN_USAGE_FILE. Never fails the request it describes."""
    record = {
        "timestamp": datetime.now().isoformat(),
        "step": step,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "max_tokens": max_tokens,
        "finish_reason": finish_reason
    }
    try:
        with _usage_lock, open(TOKEN_USAGE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as e:
        print(f"[Token Usage] Failed to record usage to {TOKEN_USAGE_FILE}: {e}", file=sys.stderr)


def _post_chat_completion(vllm_url: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    url = vllm_url.rstrip("/") + "/chat/completions"
    droppable = [f for f in OPTIONAL_FIELDS if f in payload]
    while True:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with request_slots, urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                err_text = e.read().decode("utf-8", errors="replace")
            except Exception:
                err_text = ""
            # Prompt too long is not an unsupported-field problem; retrying without fields won't help
            too_long = "context length" in err_text or "max_model_len" in err_text
            if e.code != 400 or not droppable or too_long:
                raise RuntimeError(f"vLLM request failed (HTTP {e.code}): {err_text}") from e
            # Drop the field the server complained about, else the next one in order
            culprit = next((f for f in droppable if f in err_text), droppable[0])
            droppable.remove(culprit)
            payload.pop(culprit)
        except urllib.error.URLError as e:
            raise _connection_error(vllm_url, e) from e


def chat(
    vllm_url: str,
    model_name: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.0,
    top_p: float = 1.0,
    json_schema: Optional[Dict[str, Any]] = None,
    timeout: int = VLLM_REQUEST_TIMEOUT,
    max_tokens: int = MAX_NEW_TOKENS,
    step: str = "unlabeled"
) -> ChatResult:
    """
    Sends a chat completion constrained to JSON output: to `json_schema` when given, else any JSON object.
    Reasoning in the result is empty unless the model profile lets the model think. `step` labels the
    request's token usage record.
    """
    payload: Dict[str, Any] = {
        "model": model_name,
        "messages": _with_reasoning_strength(messages),
        "temperature": temperature,
        "top_p": top_p,
        "repetition_penalty": 1.05,
        "max_tokens": max_tokens,
        # Thinking is off unless the model profile opts in (VLLM_ENABLE_THINKING=1); e.g. GLM-4.7 thinks by default
        "chat_template_kwargs": {"enable_thinking": VLLM_ENABLE_THINKING}
    }
    if json_schema is None:
        payload["response_format"] = {"type": "json_object"}
    else:
        # Legacy `guided_json` is silently ignored by current vLLM; `structured_outputs` enforces the schema
        payload["structured_outputs"] = {"json": json_schema}

    body = _post_chat_completion(vllm_url, payload, timeout)
    choice = body["choices"][0]
    message = choice["message"]
    usage = body.get("usage") or {}
    record_usage(step, usage.get("prompt_tokens"), usage.get("completion_tokens"), choice.get("finish_reason"), max_tokens)
    return ChatResult(
        content=message.get("content") or "",
        reasoning=message.get("reasoning") or "",
        finish_reason=choice.get("finish_reason"),
        completion_tokens=usage.get("completion_tokens")
    )

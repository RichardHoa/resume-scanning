"""
Phases of image-plus-text requests to the vLLM vision model, shared by the book proofreader (src/cli/proofread.py)
and Nữ Giới Chung (src/nugioichung).

A phase is many independent tasks, each one request with retries, run concurrently. Each task's result is saved as
<results-dir>/<key>.json, stamped with the input it was made from; a re-run skips tasks whose saved result is ok and
carries the same stamp, so a continued run only redoes tasks that failed or never ran. A dry run sends nothing and
counts each task's prompt tokens with the model's own processor, images included.
"""
import base64
import glob
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, NamedTuple, Optional

from src.core.config import VLLM_MAX_MODEL_LEN, VLLM_MAX_CONCURRENT_REQUESTS

ATTEMPTS = 3    # the first try and two retries


class Phase(NamedTuple):
    id: Any             # saved with each result, e.g. 1 or "layout"
    step: str           # labels the token usage records
    max_tokens: int
    thinking: bool
    retry_temperature: float    # for the attempts after the first, which is at temperature 0


class Model(NamedTuple):
    name: str
    vllm_url: str


class Request(NamedTuple):
    key: str
    build: Callable[[], List[Dict[str, Any]]]   # the chat messages; called on every attempt
    schema: Dict[str, Any]
    # Input this one task depends on beyond the phase's stamp (e.g. its crop box), saved and checked with it
    stamp: Optional[Dict[str, Any]] = None


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sha1(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


# -- messages
def data_url(data, mime):
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def image_messages(system, images, text):
    """Chat messages: the system prompt, then a user turn of each (label, image data URL) and the text."""
    content = []
    for label, url in images:
        content.append({"type": "text", "text": label})
        content.append({"type": "image_url", "image_url": {"url": url}})
    content.append({"type": "text", "text": text})
    return [{"role": "system", "content": system}, {"role": "user", "content": content}]


def _parts(message):
    """A message's content as a list of OpenAI content parts."""
    content = message["content"]
    return content if isinstance(content, list) else [{"type": "text", "text": content}]


def _decode_image(part):
    """An image_url part's (mime type, bytes)."""
    header, b64 = part["image_url"]["url"].split(",", 1)
    return header[len("data:"):].split(";", 1)[0], base64.b64decode(b64)


def save_request(messages, folder):
    """Writes a request as sent into `folder`: imageN.<ext> for each image, and <role>.txt with its text, where
    "[image N]" stands for each image."""
    os.makedirs(folder, exist_ok=True)
    for name in os.listdir(folder):
        os.remove(os.path.join(folder, name))
    n = 0
    for m in messages:
        texts = []
        for part in _parts(m):
            if part["type"] == "image_url":
                n += 1
                mime, data = _decode_image(part)
                with open(os.path.join(folder, f"image{n}.{mime.split('/', 1)[1]}"), "wb") as f:
                    f.write(data)
                texts.append(f"[image {n}]")
            else:
                texts.append(part["text"])
        with open(os.path.join(folder, f"{m['role']}.txt"), "w", encoding="utf-8") as f:
            f.write("\n\n".join(texts) + "\n")


# -- running
def is_current(result, stamp):
    """True for a successful result made against the same input (`stamp`)."""
    return result.get("status") == "ok" and all(result.get(k) == v for k, v in stamp.items())


def run_one(req, out_path, stamp, *, phase, model, request_dir=None):
    from src.providers import vllm_client
    result = {"task": req.key, "phase": phase.id, "model": model.name, **stamp}
    for attempt in range(1, ATTEMPTS + 1):
        result["attempts"] = attempt
        messages = req.build()
        if request_dir and attempt == 1:
            save_request(messages, request_dir)
        try:
            reply = vllm_client.chat(
                model.vllm_url, model.name, messages,
                temperature=0.0 if attempt == 1 else phase.retry_temperature,
                json_schema=req.schema, max_tokens=phase.max_tokens, step=phase.step,
                enable_thinking=phase.thinking
            )
        except RuntimeError as e:
            too_long = "context length" in str(e) or "max_model_len" in str(e)
            result.update(status="too_long" if too_long else "failed", error=str(e))
            if too_long:
                break
            continue
        result.update(reasoning=reply.reasoning, finish_reason=reply.finish_reason,
                      completion_tokens=reply.completion_tokens, content=reply.content)
        try:
            answer = json.loads(reply.content)
        except json.JSONDecodeError as e:
            result.update(status="failed", error=f"answer is not JSON ({e}); finish_reason={reply.finish_reason}")
            continue
        result.update(status="ok", error=None, answer=answer)
        break
    write_json(out_path, result)
    return result


def run_phase(requests, results_dir, stamp, *, label, phase, model, save_requests=False):
    """
    Runs every request with no current result in `results_dir`. With `save_requests`, each request's images and
    prompts as sent go to <results-dir>/<key>/ (see `save_request`).
    """
    os.makedirs(results_dir, exist_ok=True)
    todo = []
    for req in requests:
        path = os.path.join(results_dir, f"{req.key}.json")
        task_stamp = {**stamp, **(req.stamp or {})}
        if os.path.exists(path) and is_current(read_json(path), task_stamp):
            continue
        todo.append((req, path, task_stamp))
    print(f"{label}: {len(todo)} task(s) to run, concurrency {VLLM_MAX_CONCURRENT_REQUESTS}")
    counts = {}
    with ThreadPoolExecutor(max_workers=VLLM_MAX_CONCURRENT_REQUESTS) as pool:
        futures = {pool.submit(run_one, req, path, task_stamp, phase=phase, model=model,
                               request_dir=os.path.join(results_dir, req.key) if save_requests else None): req.key
                   for req, path, task_stamp in todo}
        for n, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            counts[r["status"]] = counts.get(r["status"], 0) + 1
            if r["status"] != "ok":
                print(f"  [{n}/{len(todo)}] {r['task']}: {r['status']} after {r['attempts']} attempt(s): "
                      f"{(r.get('error') or '')[:200]}")
            elif n % 25 == 0 or n == len(todo):
                print(f"  [{n}/{len(todo)}] {counts}")


def load_results(results_dir, stamp):
    """Successful answers by task key, from results made against the same input (`stamp`)."""
    out = {}
    for path in sorted(glob.glob(os.path.join(results_dir, "*.json"))):
        r = read_json(path)
        if is_current(r, stamp):
            out[r["task"]] = r["answer"]
    return out


def read_result(results_dir, key):
    """One task's saved result, whatever its status, or None if it never ran."""
    path = os.path.join(results_dir, f"{key}.json")
    return read_json(path) if os.path.exists(path) else None


def current_answer(results_dir, key, stamp):
    """(answer, None) for a task's current saved answer, else (None, why there is none)."""
    r = read_result(results_dir, key)
    if r is None:
        return None, "never ran"
    if r.get("status") != "ok":
        return None, f"{r.get('status')}: {(r.get('error') or '')[:150]}"
    if not is_current(r, stamp):
        return None, "made from other input"
    return r["answer"], None


# -- dry run
def count_tokens(requests, phase, model_name, out_file, *, label):
    """Counts each request's prompt tokens with the model's processor, writes one JSON line per request to
    `out_file`, and prints how many would not fit the context window with `phase.max_tokens` on top."""
    from io import BytesIO
    from PIL import Image
    from transformers import AutoProcessor
    processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=True)
    counts = []
    for req in requests:
        hf_messages = []
        for m in req.build():
            hf_parts = []
            for part in _parts(m):
                if part["type"] == "image_url":
                    _, raw = _decode_image(part)
                    hf_parts.append({"type": "image", "image": Image.open(BytesIO(raw)).convert("RGB")})
                else:
                    hf_parts.append(part)
            hf_messages.append({"role": m["role"], "content": hf_parts})
        ids = processor.apply_chat_template(hf_messages, add_generation_prompt=True, tokenize=True,
                                            return_dict=True, enable_thinking=phase.thinking)["input_ids"]
        n = len(ids[0]) if ids and isinstance(ids[0], list) else len(ids)
        counts.append(n)
        out_file.write(json.dumps({"phase": phase.id, "task": req.key, "prompt_tokens": n,
                                   "max_tokens": phase.max_tokens}) + "\n")
    if not counts:
        print(f"[Dry Run] {label}: no tasks")
        return
    s = sorted(counts)
    over = sum(1 for n in counts if n + phase.max_tokens > VLLM_MAX_MODEL_LEN)
    print(f"[Dry Run] {label}: {len(s)} tasks, prompt tokens p50 {s[len(s) // 2]} / "
          f"p95 {s[min(len(s) - 1, len(s) * 95 // 100)]} / max {s[-1]}; + max_tokens {phase.max_tokens} "
          f"vs context {VLLM_MAX_MODEL_LEN}: {over} task(s) would not fit")

"""
Names pass over a reviewed transcript (src/cli/review_transcript.py), with a text LLM served by vLLM (Qwen3-Omni).

The lines go in chunks of CHUNK_LINES, each with CONTEXT_LINES before and after, so the model sees how a name is said
elsewhere in the interview. It fixes only names and terms that came out as common words or garbled sounds, and keeps
the speaker's own forms of names. An edit is applied only if its "old" occurs exactly once in the line and both sides
are at most MAX_EDIT_SYLLABLES; an unsure edit is written as [? new]. Run by scripts/submit_transcript.sh; spec in
.scratch/audio-transcribe/spec.md ("Next: two-model fusion, names pass and scoring (v2)", step 4).

Writes next to the transcript:
  <stem>.final.transcript.txt  the same lines, timestamps and speakers, with the names fixed
  <stem>.names.jsonl           per edit: line, old, new, sure, and whether it was applied (or why not)
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor

from src.cli.review_transcript import read_glossary, read_lines, syllables
from src.core.config import VLLM_MAX_CONCURRENT_REQUESTS
from src.prompts.transcript_names_prompts import SYSTEM_PROMPT, names_schema, user_text

CHUNK_LINES = 20
CONTEXT_LINES = 60    # before and after the chunk; the whole 47-minute interview would crowd VLLM_MAX_MODEL_LEN
MAX_EDIT_SYLLABLES = 8
ATTEMPTS = 3    # the first try and two retries
RETRY_TEMPERATURE = 0.3
MAX_TOKENS = 2048


def parse_args():
    parser = argparse.ArgumentParser(description="Fix misheard names in a reviewed transcript with a vLLM text model")
    parser.add_argument("transcript", help="<stem>.reviewed.transcript.txt from review_transcript.py")
    parser.add_argument("--context", required=True, help="the glossary file given to transcribe_audio.py")
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--vllm-url", required=True)
    return parser.parse_args()


def as_line(line):
    prefix = f"{line['speaker']}: " if line["speaker"] else ""
    return f"[{line['start']} → {line['end']}] {prefix}{line['draft']}"


def ask(start, lines, glossary, args):
    """The model's edits for the chunk starting at line `start`, or the error after ATTEMPTS failed tries."""
    from src.providers import vllm_client

    end = min(len(lines), start + CHUNK_LINES)
    before = [as_line(line) for line in lines[max(0, start - CONTEXT_LINES):start]]
    after = [as_line(line) for line in lines[end:end + CONTEXT_LINES]]
    chunk = [as_line(line) for line in lines[start:end]]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text(glossary, before, chunk, after)},
    ]
    error = "no attempt"
    for attempt in range(1, ATTEMPTS + 1):
        try:
            reply = vllm_client.chat(
                args.vllm_url, args.model_name, messages,
                temperature=0.0 if attempt == 1 else RETRY_TEMPERATURE,
                json_schema=names_schema(), max_tokens=MAX_TOKENS, step="transcript_names", enable_thinking=False
            )
            return json.loads(reply.content)["edits"], None
        except (RuntimeError, json.JSONDecodeError, KeyError, TypeError) as e:
            error = str(e)
    return [], error


def whole_words(old):
    """A pattern for old as whole words, so "Đài" never matches inside a longer word."""
    return re.compile(rf"(?<!\w){re.escape(old)}(?!\w)")


def rejection(edit, text):
    """None if the edit may be applied to the line's text, else why not."""
    old, new = edit["old"], edit["new"]
    if not old or old == new:
        return "no change"
    found = len(whole_words(old).findall(text))
    if found != 1:
        return f"old occurs {found} times in the line"
    if len(syllables(old)) > MAX_EDIT_SYLLABLES or len(syllables(new)) > MAX_EDIT_SYLLABLES:
        return f"over {MAX_EDIT_SYLLABLES} syllables"
    return None


def main():
    args = parse_args()
    lines = read_lines(args.transcript)
    glossary = read_glossary(args.context)
    starts = list(range(0, len(lines), CHUNK_LINES))
    print(f"[Names] {len(lines)} lines from {args.transcript} in {len(starts)} chunks, {len(glossary)} glossary terms")

    with ThreadPoolExecutor(max_workers=VLLM_MAX_CONCURRENT_REQUESTS) as pool:
        answers = list(pool.map(lambda start: ask(start, lines, glossary, args), starts))

    texts = [line["draft"] for line in lines]
    rows, failed = [], 0
    for start, (edits, error) in zip(starts, answers):
        if error:
            failed += 1
            print(f"[Names] Chunk from {lines[start]['start']} failed, left as is: {error[:300]}")
            continue
        size = min(CHUNK_LINES, len(lines) - start)
        for edit in edits:
            row = {**edit, "chunk_start": lines[start]["start"], "applied": False}
            if not 1 <= edit["line"] <= size:
                row["why"] = f"line {edit['line']} is not in the chunk of {size}"
                rows.append(row)
                continue
            i = start + edit["line"] - 1
            row["start"] = lines[i]["start"]
            why = rejection(edit, texts[i])
            if why:
                row["why"] = why
            else:
                new = edit["new"] if edit["sure"] else f"[? {edit['new']}]"
                texts[i] = whole_words(edit["old"]).sub(lambda _: new, texts[i])
                row["applied"] = True
            rows.append(row)

    stem = args.transcript[:-len(".reviewed.transcript.txt")] if args.transcript.endswith(".reviewed.transcript.txt") \
        else os.path.splitext(args.transcript)[0]
    out_path, log_path = f"{stem}.final.transcript.txt", f"{stem}.names.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for line, text in zip(lines, texts):
            f.write(as_line({**line, "draft": text}) + "\n")
    with open(log_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    applied = sum(row["applied"] for row in rows)
    unsure = sum(row["applied"] and not row["sure"] for row in rows)
    print(f"[Names] {applied} edits applied ({unsure} unsure, as [? …]), {len(rows) - applied} rejected, "
          f"{failed} chunks failed")
    print(f"[Names] Wrote {out_path} and {log_path}")


if __name__ == "__main__":
    main()

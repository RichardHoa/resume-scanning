"""
Review a transcript from src/cli/transcribe_audio.py with an audio LLM served by vLLM (Qwen3-Omni).

Each line of <stem>.transcript.txt is one Segment. Its clip is cut from the audio at the line's timestamps and
sent with the draft text, the lines before and after, and the glossary; the model fixes misheard words. The answer
replaces the draft only if it is not empty and, for a draft of MIN_GUARDED_SYLLABLES or more, keeps at least
MIN_KEPT_SHARE of the draft's syllables in order. Run by scripts/submit_transcript.sh; spec in
.scratch/audio-transcribe/spec.md ("Next: Qwen3-Omni review pass").

Writes next to the audio:
  <stem>.reviewed.transcript.txt  the same lines, timestamps and speakers, with the reviewed text
  <stem>.review.jsonl             per Segment: times, speaker, draft, reviewed text, status
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import argparse
import base64
import difflib
import io
import json
import re
import subprocess
import wave
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from src.core.config import VLLM_MAX_CONCURRENT_REQUESTS
from src.prompts.transcript_review_prompts import SYSTEM_PROMPT, review_schema, user_text

SAMPLE_RATE = 16000
ATTEMPTS = 3    # the first try and two retries
RETRY_TEMPERATURE = 0.3
MAX_TOKENS = 1024    # a 30 s Segment is about 150 syllables
MIN_GUARDED_SYLLABLES = 4    # a shorter draft (e.g. "Yet." on a 1 s clip) may be rewritten entirely
MIN_KEPT_SHARE = 0.5    # difflib ratio of draft and reviewed syllables below which the draft is kept

LINE = re.compile(r"^\[(\S+) → (\S+)\] (?:(Person \d+): )?(.*)$")


def parse_args():
    parser = argparse.ArgumentParser(description="Review a transcript with an audio LLM served by vLLM")
    parser.add_argument("audio", help="the recording the transcript was made from")
    parser.add_argument("transcript", help="<stem>.transcript.txt from transcribe_audio.py")
    parser.add_argument("--context", required=True, help="the glossary file given to transcribe_audio.py")
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--vllm-url", required=True)
    return parser.parse_args()


def seconds(stamp):
    """'HH:MM:SS.s' -> seconds."""
    hours, minutes, secs = stamp.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(secs)


def read_lines(path):
    lines = []
    with open(path, encoding="utf-8") as f:
        for n, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            m = LINE.match(raw.rstrip("\n"))
            if not m:
                sys.exit(f"[Review] {path}:{n} is not a transcript line: {raw.strip()[:80]}")
            start, end, speaker, text = m.groups()
            lines.append({"start": start, "end": end, "speaker": speaker, "draft": text})
    return lines


def read_glossary(path):
    """Terms separated by commas or newlines, as transcribe_audio.py reads them."""
    with open(path, encoding="utf-8") as f:
        return [t.strip() for t in re.split(r"[,\n]", f.read()) if t.strip()]


def decode_audio(path):
    """16 kHz mono float32, with the ffmpeg bundled in imageio-ffmpeg (the compute machine has no system ffmpeg)."""
    from imageio_ffmpeg import get_ffmpeg_exe

    cmd = [
        get_ffmpeg_exe(), "-nostdin", "-loglevel", "error", "-i", path,
        "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-",
    ]
    return np.frombuffer(subprocess.run(cmd, check=True, capture_output=True).stdout, dtype=np.float32)


def wav_base64(clip):
    pcm = (np.clip(clip, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def syllables(text):
    return re.findall(r"\w+", text.lower())


def guard(draft, reviewed):
    """None if the reviewed text may replace the draft, else why not."""
    if not reviewed:
        return "empty answer"
    a, b = syllables(draft), syllables(reviewed)
    if len(a) >= MIN_GUARDED_SYLLABLES:
        kept = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
        if kept < MIN_KEPT_SHARE:
            return f"kept {kept:.2f} of the draft, under {MIN_KEPT_SHARE}"
    return None


def review_one(i, lines, audio, glossary, args):
    from src.providers import vllm_client

    line = lines[i]
    clip = audio[int(seconds(line["start"]) * SAMPLE_RATE):int(seconds(line["end"]) * SAMPLE_RATE)]
    previous = lines[i - 1]["draft"] if i > 0 else ""
    following = lines[i + 1]["draft"] if i + 1 < len(lines) else ""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": [
            {"type": "text", "text": user_text(glossary, previous, line["draft"], following)},
            {"type": "input_audio", "input_audio": {"data": wav_base64(clip), "format": "wav"}},
        ]},
    ]
    row = {**line, "reviewed": None}
    error = "no attempt"
    for attempt in range(1, ATTEMPTS + 1):
        try:
            reply = vllm_client.chat(
                args.vllm_url, args.model_name, messages,
                temperature=0.0 if attempt == 1 else RETRY_TEMPERATURE,
                json_schema=review_schema(), max_tokens=MAX_TOKENS, step="transcript_review", enable_thinking=False
            )
            row["reviewed"] = json.loads(reply.content)["text"].strip()
            break
        except (RuntimeError, json.JSONDecodeError, KeyError, TypeError) as e:
            error = str(e)
    if row["reviewed"] is None:
        row["status"] = f"failed: {error[:300]}"
        return row
    why = guard(line["draft"], row["reviewed"])
    if why:
        row["status"] = f"kept draft: {why}"
    else:
        row["status"] = "same" if row["reviewed"] == line["draft"] else "changed"
    return row


def final_text(row):
    return row["reviewed"] if row["status"] in ("same", "changed") else row["draft"]


def main():
    args = parse_args()
    lines = read_lines(args.transcript)
    glossary = read_glossary(args.context)
    print(f"[Review] {len(lines)} lines from {args.transcript}, {len(glossary)} glossary terms")
    audio = decode_audio(args.audio)

    with ThreadPoolExecutor(max_workers=VLLM_MAX_CONCURRENT_REQUESTS) as pool:
        futures = [pool.submit(review_one, i, lines, audio, glossary, args) for i in range(len(lines))]
        rows = []
        for n, fut in enumerate(futures, 1):
            rows.append(fut.result())
            if n % 25 == 0 or n == len(futures):
                print(f"  [{n}/{len(futures)}] reviewed")

    stem = args.transcript[:-len(".transcript.txt")] if args.transcript.endswith(".transcript.txt") \
        else os.path.splitext(args.transcript)[0]
    out_path, log_path = f"{stem}.reviewed.transcript.txt", f"{stem}.review.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for row in rows:
            prefix = f"{row['speaker']}: " if row["speaker"] else ""
            f.write(f"[{row['start']} → {row['end']}] {prefix}{final_text(row)}\n")
    with open(log_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    counts = {}
    for row in rows:
        key = row["status"].split(":")[0]
        counts[key] = counts.get(key, 0) + 1
    print(f"[Review] {counts}")
    print(f"[Review] Wrote {out_path} and {log_path}")


if __name__ == "__main__":
    main()

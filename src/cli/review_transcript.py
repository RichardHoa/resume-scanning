"""
Fuse two transcripts from src/cli/transcribe_audio.py --with-phowhisper with an audio LLM served by vLLM (Qwen3-Omni).

Each line of <stem>.transcript.txt (A, Qwen3-ASR) is one Segment, and <stem>.phowhisper.transcript.txt (B) has the
same lines. The line's clip, repaired and padded the way the transcriber hears it, is sent with both drafts, a merged
view of where they differ, the two lines before and after, and the glossary; the model writes what it hears. The
answer replaces A only if it is not empty and, for a line of MIN_GUARDED_SYLLABLES or more, at most
MAX_UNSUPPORTED_SHARE of its syllables are in neither draft nor the glossary, and its length is within
MIN_LENGTH_RATIO–MAX_LENGTH_RATIO of the drafts'. Run by scripts/audio/submit_transcript.sh; spec in
.scratch/audio-transcribe/spec.md ("Next: two-model fusion, names pass and scoring (v2)").

Writes next to the audio:
  <stem>.reviewed.transcript.txt  the same lines, timestamps and speakers, with the reviewed text
  <stem>.review.jsonl             per Segment: times, speaker, both drafts, merged view, reviewed text, status
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
import unicodedata
import wave
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from src.core.config import VLLM_MAX_CONCURRENT_REQUESTS
from src.prompts.transcript_review_prompts import SYSTEM_PROMPT, review_schema, user_text

SAMPLE_RATE = 16000
ATTEMPTS = 3    # the first try and two retries
RETRY_TEMPERATURE = 0.3
MAX_TOKENS = 1024    # a 30 s Segment is about 150 syllables
MIN_GUARDED_SYLLABLES = 4    # a shorter line (e.g. "Yet." on a 1 s clip) may be rewritten entirely
MAX_UNSUPPORTED_SHARE = 0.3    # share of answer syllables found in neither draft nor the glossary: more is made up
MIN_LENGTH_RATIO, MAX_LENGTH_RATIO = 0.6, 1.5    # answer syllables against the drafts' mean: outside is a summary
CONTEXT_LINES = 2    # lines before and after shown as context
ASR_CONTEXT_PAD_S = 0.5    # as in transcribe_audio.py: the clip is heard with this much more on each side

LINE = re.compile(r"^\[(\S+) → (\S+)\] (?:(Person \d+): )?(.*)$")


def parse_args():
    parser = argparse.ArgumentParser(description="Review a transcript with an audio LLM served by vLLM")
    parser.add_argument("audio", help="the recording the transcript was made from")
    parser.add_argument("transcript", help="<stem>.transcript.txt from transcribe_audio.py (draft A, Qwen3-ASR)")
    parser.add_argument(
        "--second", required=True, help="<stem>.phowhisper.transcript.txt with the same lines (draft B, PhoWhisper)"
    )
    parser.add_argument("--no-declip", action="store_true", help="don't repair clipped peaks (as transcribe_audio.py)")
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


def same_lines(first, second, path):
    """Exit unless both transcripts have the same lines (timestamps and speakers), so each line can be paired."""
    for n, (a, b) in enumerate(zip(first, second), 1):
        if (a["start"], a["end"], a["speaker"]) != (b["start"], b["end"], b["speaker"]):
            sys.exit(f"[Review] Line {n} of {path} is not the same line as in the first transcript: {b['start']}")
    if len(first) != len(second):
        sys.exit(f"[Review] {path} has {len(second)} lines, the first transcript {len(first)}")


def decode_audio(path, declip):
    """16 kHz mono float32, decoded and (with declip) repaired as transcribe_audio.py does, with the ffmpeg bundled in
    imageio-ffmpeg (the compute machine has no system ffmpeg)."""
    from imageio_ffmpeg import get_ffmpeg_exe

    cmd = [get_ffmpeg_exe(), "-nostdin", "-loglevel", "error", "-i", path]
    if declip:
        cmd += ["-af", "aformat=channel_layouts=mono,adeclip"]
    cmd += ["-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"]
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
    """Lowercased syllables with accents kept, in one Unicode form; punctuation and [? markers drop out."""
    return re.findall(r"\w+", unicodedata.normalize("NFC", text).lower())


def merged_view(draft_a, draft_b):
    """The words both drafts share as they are, and each place they differ as {A: ... | B: ...}."""
    a, b = draft_a.split(), draft_b.split()
    key = lambda words: [" ".join(syllables(w)) for w in words]
    parts = []
    matcher = difflib.SequenceMatcher(None, key(a), key(b), autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            parts.append(" ".join(a[i1:i2]))
        else:
            parts.append(f"{{A: {' '.join(a[i1:i2]) or '-'} | B: {' '.join(b[j1:j2]) or '-'}}}")
    return " ".join(parts)


def clip_span(lines, i, length):
    """The seconds of audio to send for line i: the line plus up to ASR_CONTEXT_PAD_S on each side, never past the
    middle of the gap to a neighbouring line (transcribe_audio.py's pad_segments). The transcriber measured gaps to
    every Segment, including ones it heard nothing in and left out, so next to those this padding can be longer."""
    start, end = seconds(lines[i]["start"]), seconds(lines[i]["end"])
    earliest = (seconds(lines[i - 1]["end"]) + start) / 2 if i > 0 else 0.0
    latest = (end + seconds(lines[i + 1]["start"])) / 2 if i + 1 < len(lines) else length
    return max(earliest, start - ASR_CONTEXT_PAD_S, 0.0), min(latest, end + ASR_CONTEXT_PAD_S, length)


def guard(draft_a, draft_b, reviewed, glossary_syllables):
    """None if the reviewed text may replace draft A, else why not."""
    if not reviewed:
        return "empty answer"
    a, b, out = syllables(draft_a), syllables(draft_b), syllables(reviewed)
    if max(len(a), len(b)) < MIN_GUARDED_SYLLABLES or (not out and "[?" in reviewed):
        return None    # a bare [?] is turned into [? draft A] by final_text
    supported = set(a) | set(b) | glossary_syllables
    unsupported = sum(s not in supported for s in out) / len(out) if out else 0.0
    if unsupported > MAX_UNSUPPORTED_SHARE:
        return f"{unsupported:.2f} of it in neither draft, over {MAX_UNSUPPORTED_SHARE}"
    # The mean over the drafts that heard something: an empty draft B would otherwise halve it
    lengths = [len(d) for d in (a, b) if d]
    ratio = len(out) / (sum(lengths) / len(lengths))
    if not MIN_LENGTH_RATIO <= ratio <= MAX_LENGTH_RATIO:
        return f"{ratio:.2f}× the drafts' length, outside {MIN_LENGTH_RATIO}–{MAX_LENGTH_RATIO}"
    return None


def review_one(i, lines, audio, glossary, args):
    from src.providers import vllm_client

    line = lines[i]
    start, end = clip_span(lines, i, len(audio) / SAMPLE_RATE)
    clip = audio[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)]
    before = [lines[j]["draft"] for j in range(max(0, i - CONTEXT_LINES), i)]
    after = [lines[j]["draft"] for j in range(i + 1, min(len(lines), i + 1 + CONTEXT_LINES))]
    merged = merged_view(line["draft"], line["second"])
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": [
            {"type": "text", "text": user_text(glossary, before, after, line["draft"], line["second"], merged)},
            {"type": "input_audio", "input_audio": {"data": wav_base64(clip), "format": "wav"}},
        ]},
    ]
    row = {**line, "merged": merged, "reviewed": None}
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
    glossary_syllables = {s for term in glossary for s in syllables(term)}
    why = guard(line["draft"], line["second"], row["reviewed"], glossary_syllables)
    if why:
        row["status"] = f"kept draft: {why}"
    else:
        row["status"] = "same" if row["reviewed"] == line["draft"] else "changed"
    return row


def final_text(row):
    """The reviewed text if it passed the guard, else draft A. A bare [?] (nothing made out) keeps A's words as its
    guess, so the line isn't lost."""
    if row["status"] not in ("same", "changed"):
        return row["draft"]
    if not syllables(row["reviewed"]) and "[?" in row["reviewed"] and row["draft"]:
        return f"[? {row['draft']}]"
    return row["reviewed"]


def main():
    args = parse_args()
    lines = read_lines(args.transcript)
    second = read_lines(args.second)
    same_lines(lines, second, args.second)
    for line, other in zip(lines, second):
        line["second"] = other["draft"]
    glossary = read_glossary(args.context)
    print(f"[Review] {len(lines)} lines from {args.transcript} and {args.second}, {len(glossary)} glossary terms")
    audio = decode_audio(args.audio, declip=not args.no_declip)

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

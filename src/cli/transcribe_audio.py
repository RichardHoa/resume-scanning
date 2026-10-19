"""Transcribe one recording into timestamped, speaker-labelled lines.

Standalone: runs in its own venv (requirements-audio.txt), imports nothing from src. Guide: docs/audio-transcribe.md.

Pipeline (see .scratch/audio-transcribe/spec.md):
  1. Decode the audio to 16 kHz mono with ffmpeg.
  2. pyannote finds who speaks when (exactly 2 speakers, exclusive turns).
  3. Silero VAD finds the speech, so cuts only ever fall inside pauses.
  4. Speech is split at speaker changes (moved to the nearest pause), long stretches are split at their longest
     pause, and close pieces of the same speaker are joined into Segments of up to ~30 s.
  5. Qwen3-ASR transcribes each Segment; the Segment's own start/end are its timestamps.

Output: <input-stem>.transcript.txt next to the input, one line per Segment:
  [HH:MM:SS.s → HH:MM:SS.s] Person N: text
"""

import argparse
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

SAMPLE_RATE = 16000
NUM_SPEAKERS = 2

ASR_MODEL = "Qwen/Qwen3-ASR-1.7B"
DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"

# Cutting rules (spec: "Cutting the audio")
MIN_CUT_SILENCE_MS = 500  # speech regions are only separated by pauses at least this long
SPEECH_PAD_MS = 200  # kept on each side of speech so word onsets/endings stay in
JOIN_GAP_S = 1.0  # same-speaker pieces closer than this are joined into one Segment
MAX_SEGMENT_S = 30.0  # longer stretches are split at their longest internal pause, even one under 0.5 s
MIN_SPLIT_SIDE_S = 2.0  # a split pause must leave at least this much speech on each side
FINE_PAUSE_MS = 100  # shortest pause a long stretch or a speaker change may be cut in
SPEAKER_SNAP_S = 1.0  # a speaker-change cut moves to the nearest pause within this distance
MIN_SPEAKER_PIECE_S = 0.5  # a shorter speaker piece (e.g. a quick "ừ") joins its longer neighbour's line

ASR_BATCH_SIZE = 16
ASR_MAX_NEW_TOKENS = 512

log = logging.getLogger("transcribe_audio")


@dataclass
class Span:
    """A stretch of the recording in seconds: a speaker turn, a pause, a speech region, or a final Segment."""

    start: float
    end: float
    speaker: str | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def middle(self) -> float:
        return (self.start + self.end) / 2


def decode_audio(path: Path) -> np.ndarray:
    """Decode any ffmpeg-readable file to a 16 kHz mono float32 waveform."""
    cmd = [
        "ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path),
        "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-",
    ]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def load_diarization_pipeline():
    """Load pyannote first, so a missing token or unaccepted terms stop the run before the ASR model loads."""
    token = os.environ.get("HF_TOKEN")
    if not token:
        sys.exit(
            "[ERROR] HF_TOKEN is not set. Speaker labels need a Hugging Face token "
            "(see docs/audio-transcribe.md), or rerun with --no-speakers."
        )
    from pyannote.audio import Pipeline

    access_error = (
        f"[ERROR] Could not load {DIARIZATION_MODEL}. Check that HF_TOKEN is valid and that you accepted "
        f"the model's terms at https://huggingface.co/{DIARIZATION_MODEL}, or rerun with --no-speakers."
    )
    try:
        pipeline = Pipeline.from_pretrained(DIARIZATION_MODEL, token=token)
    except Exception as exc:
        log.error("Loading %s failed: %s", DIARIZATION_MODEL, exc)
        sys.exit(access_error)
    if pipeline is None:  # pyannote returns None instead of raising on some gated-access failures
        sys.exit(access_error)
    pipeline.to(torch.device("cuda"))
    return pipeline


def diarize(pipeline, audio: np.ndarray) -> list[Span]:
    """Exclusive speaker turns (one speaker at any moment), with back-to-back turns of one speaker merged."""
    output = pipeline(
        {"waveform": torch.from_numpy(audio)[None], "sample_rate": SAMPLE_RATE},
        num_speakers=NUM_SPEAKERS,
    )
    turns: list[Span] = []
    for turn, speaker in output.exclusive_speaker_diarization:
        if turns and turns[-1].speaker == speaker:
            turns[-1].end = max(turns[-1].end, turn.end)
        else:
            turns.append(Span(turn.start, turn.end, speaker))
    return turns


def find_speech(vad_model, audio: torch.Tensor, min_silence_ms: int, pad_ms: int) -> list[Span]:
    from silero_vad import get_speech_timestamps

    stamps = get_speech_timestamps(
        audio, vad_model, sampling_rate=SAMPLE_RATE,
        min_silence_duration_ms=min_silence_ms, speech_pad_ms=pad_ms,
    )
    return [Span(s["start"] / SAMPLE_RATE, s["end"] / SAMPLE_RATE) for s in stamps]


def pauses_between(fine_speech: list[Span]) -> list[Span]:
    return [Span(a.end, b.start) for a, b in zip(fine_speech, fine_speech[1:]) if b.start > a.end]


def speaker_change_cuts(turns: list[Span], pauses: list[Span]) -> list[float]:
    """Where to cut for each speaker change: the middle of the pause nearest pyannote's boundary.

    pyannote's boundary can be off by a few hundred ms, so cutting right on it could split a word.
    With no pause within SPEAKER_SNAP_S, the boundary itself is used.
    """
    cuts = []
    for a, b in zip(turns, turns[1:]):
        if a.speaker == b.speaker:
            continue
        boundary = (a.end + b.start) / 2
        nearby = [p for p in pauses if abs(p.middle - boundary) <= SPEAKER_SNAP_S]
        cuts.append(min(nearby, key=lambda p: abs(p.middle - boundary)).middle if nearby else boundary)
    return cuts


def dominant_speaker(piece: Span, turns: list[Span]) -> str:
    """The speaker whose turns overlap the piece most; the nearest turn's speaker if none overlap."""
    overlap: dict[str, float] = {}
    for turn in turns:
        shared = min(piece.end, turn.end) - max(piece.start, turn.start)
        if shared > 0:
            overlap[turn.speaker] = overlap.get(turn.speaker, 0.0) + shared
    if overlap:
        return max(overlap, key=overlap.get)
    nearest = min(turns, key=lambda t: max(t.start - piece.end, piece.start - t.end))
    return nearest.speaker


def split_by_speaker(speech: list[Span], turns: list[Span], pauses: list[Span]) -> list[Span]:
    """Cut each speech region at speaker changes inside it, so no piece holds two voices."""
    cuts = speaker_change_cuts(turns, pauses)
    pieces: list[Span] = []
    for region in speech:
        bounds = [region.start] + sorted(t for t in cuts if region.start < t < region.end) + [region.end]
        parts = [Span(a, b) for a, b in zip(bounds, bounds[1:])]
        for part in parts:
            part.speaker = dominant_speaker(part, turns)
        # A piece too short to be its own line takes the label of the longer of its nearest long pieces
        # on either side, so a run of short pieces can't pass a wrong label along
        long_parts = [part for part in parts if part.duration >= MIN_SPEAKER_PIECE_S]
        for part in parts:
            if part.duration >= MIN_SPEAKER_PIECE_S:
                continue
            before = [p for p in long_parts if p.end <= part.start][-1:]
            after = [p for p in long_parts if p.start >= part.end][:1]
            if before or after:
                part.speaker = max(before + after, key=lambda p: p.duration).speaker
        for part in parts:
            if pieces and pieces[-1].speaker == part.speaker and pieces[-1].end == part.start:
                pieces[-1].end = part.end
            else:
                pieces.append(part)
    return pieces


def split_long(piece: Span, pauses: list[Span]) -> list[Span]:
    """Split a piece longer than MAX_SEGMENT_S at its longest internal pause, recursively.

    Never cuts at a fixed time mark: a stretch with no usable pause stays whole.
    """
    if piece.duration <= MAX_SEGMENT_S:
        return [piece]
    inside = [
        p for p in pauses
        if p.start >= piece.start + MIN_SPLIT_SIDE_S and p.end <= piece.end - MIN_SPLIT_SIDE_S
    ]
    if not inside:
        log.warning("No pause to split %.1fs–%.1fs (%.1fs); keeping it whole", piece.start, piece.end, piece.duration)
        return [piece]
    cut = max(inside, key=lambda p: p.duration).middle
    return (
        split_long(Span(piece.start, cut, piece.speaker), pauses)
        + split_long(Span(cut, piece.end, piece.speaker), pauses)
    )


def join_close(pieces: list[Span]) -> list[Span]:
    """Join same-speaker pieces less than JOIN_GAP_S apart, as long as the result stays within MAX_SEGMENT_S."""
    joined: list[Span] = []
    for piece in pieces:
        last = joined[-1] if joined else None
        if (
            last is not None
            and last.speaker == piece.speaker
            and piece.start - last.end < JOIN_GAP_S
            and piece.end - last.start <= MAX_SEGMENT_S
        ):
            last.end = piece.end
        else:
            joined.append(Span(piece.start, piece.end, piece.speaker))
    return joined


def build_segments(audio: np.ndarray, turns: list[Span] | None) -> list[Span]:
    from silero_vad import load_silero_vad

    vad_model = load_silero_vad()
    waveform = torch.from_numpy(audio)
    speech = find_speech(vad_model, waveform, MIN_CUT_SILENCE_MS, SPEECH_PAD_MS)
    pauses = pauses_between(find_speech(vad_model, waveform, FINE_PAUSE_MS, 0))
    log.info("Found %d speech regions", len(speech))

    pieces = split_by_speaker(speech, turns, pauses) if turns else speech
    pieces = [part for piece in pieces for part in split_long(piece, pauses)]
    return join_close(pieces)


def transcribe_segments(audio: np.ndarray, segments: list[Span]) -> list[str]:
    from qwen_asr import Qwen3ASRModel

    model = Qwen3ASRModel.from_pretrained(
        ASR_MODEL,
        dtype=torch.bfloat16,
        device_map="cuda:0",
        max_inference_batch_size=ASR_BATCH_SIZE,
        max_new_tokens=ASR_MAX_NEW_TOKENS,
    )
    texts: list[str] = []
    for i in range(0, len(segments), ASR_BATCH_SIZE):
        batch = segments[i:i + ASR_BATCH_SIZE]
        clips = [
            (audio[int(s.start * SAMPLE_RATE):int(s.end * SAMPLE_RATE)], SAMPLE_RATE) for s in batch
        ]
        # language=None: auto-detect, so Vietnamese with English/French mixed in stays as spoken
        results = model.transcribe(audio=clips, language=None)
        texts.extend(r.text.strip() for r in results)
        log.info("Transcribed %d/%d segments", len(texts), len(segments))
    return texts


def format_time(seconds: float) -> str:
    tenths = round(seconds * 10)
    hours, rest = divmod(tenths, 36000)
    minutes, rest = divmod(rest, 600)
    return f"{hours:02d}:{minutes:02d}:{rest / 10:04.1f}"


def person_names(segments: list[Span]) -> dict[str, str]:
    """The speaker heard first is Person 1, the next Person 2."""
    names: dict[str, str] = {}
    for segment in segments:
        if segment.speaker is not None and segment.speaker not in names:
            names[segment.speaker] = f"Person {len(names) + 1}"
    return names


def write_transcript(path: Path, segments: list[Span], texts: list[str]) -> int:
    """Write one line per Segment; a Segment the ASR heard nothing in is left out."""
    names = person_names(segments)
    lines = []
    for segment, text in zip(segments, texts):
        if not text:
            continue
        prefix = f"{names[segment.speaker]}: " if segment.speaker is not None else ""
        lines.append(f"[{format_time(segment.start)} → {format_time(segment.end)}] {prefix}{text}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe one recording into timestamped, speaker-labelled lines.")
    parser.add_argument("audio", type=Path, help="audio file (any format ffmpeg reads, e.g. .m4a)")
    parser.add_argument("--no-speakers", action="store_true", help="skip speaker labels (no Hugging Face token needed)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.audio.is_file():
        sys.exit(f"[ERROR] Audio file not found: {args.audio}")
    if not torch.cuda.is_available():
        sys.exit("[ERROR] No GPU visible. Run this on a compute node with a GPU.")

    pipeline = None if args.no_speakers else load_diarization_pipeline()

    log.info("Decoding %s", args.audio)
    audio = decode_audio(args.audio)
    log.info("Audio length: %s", format_time(len(audio) / SAMPLE_RATE))

    turns = None
    if pipeline is not None:
        log.info("Finding speakers")
        turns = diarize(pipeline, audio)
        del pipeline
        torch.cuda.empty_cache()
        log.info("Found %d speaker turns", len(turns))

    segments = build_segments(audio, turns)
    log.info("Cut into %d segments", len(segments))

    texts = transcribe_segments(audio, segments)

    out_path = args.audio.with_name(f"{args.audio.stem}.transcript.txt")
    count = write_transcript(out_path, segments, texts)
    log.info("Wrote %d lines to %s", count, out_path)


if __name__ == "__main__":
    main()

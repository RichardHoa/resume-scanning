"""Transcribe one recording into timestamped, speaker-labelled lines.

Standalone: runs in its own venv (requirements-audio.txt), imports nothing from src. Guide: docs/audio-transcribe.md.

Pipeline (see .scratch/audio-transcribe/spec.md):
  1. Decode the audio to 16 kHz mono with ffmpeg, repairing clipped peaks (adeclip) unless --no-declip.
  2. pyannote finds who speaks when (2 to 4 speakers, exclusive turns).
  3. Silero VAD finds the speech, so cuts only ever fall inside pauses.
  4. Speech is split at speaker changes (moved to the nearest pause), long stretches are split at their longest
     pause, and close pieces of the same speaker are joined into Segments of up to ~30 s.
  5. Qwen3-ASR transcribes each Segment; a Segment detected as a language other than Vietnamese/English/French is
     redone as Vietnamese. The Segment's own start/end are its timestamps, but the model hears up to
     ASR_CONTEXT_PAD_S more on each side (never past the middle of the gap to a neighbour).
  6. With a glossary, a Segment whose text sounds like some glossary terms is transcribed again with just those
     terms as context, and the new text is kept only if it passes the leak guard.

Output: <input-stem>.transcript.txt next to the input, one line per Segment:
  [HH:MM:SS.s → HH:MM:SS.s] Person N: text

With --phowhisper, step 5 uses PhoWhisper-large instead (always Vietnamese), Segments over 30 s are cut to fit its
window, there is no glossary pass, and the output is <input-stem>.phowhisper.transcript.txt.

With --with-phowhisper, steps 5–6 run as usual and PhoWhisper-large then transcribes the same Segments, writing both
files with identical lines: a Segment over 30 s is cut into parts for PhoWhisper only and its texts joined.
"""

import argparse
import difflib
import logging
import os
import re
import subprocess
import sys
import unicodedata
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

SAMPLE_RATE = 16000
MIN_SPEAKERS = 2
MAX_SPEAKERS = 4  # others in the room may speak too, e.g. students asking questions

ASR_MODEL = "Qwen/Qwen3-ASR-1.7B"
DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"
PHOWHISPER_MODEL = "vinai/PhoWhisper-large"

# Cutting rules (spec: "Cutting the audio")
MIN_CUT_SILENCE_MS = 500  # speech regions are only separated by pauses at least this long
SPEECH_PAD_MS = 200  # kept on each side of speech so word onsets/endings stay in
JOIN_GAP_S = 1.0  # same-speaker pieces closer than this are joined into one Segment
MAX_SEGMENT_S = 30.0  # longer stretches are split at their longest internal pause, even one under 0.5 s
MIN_SPLIT_SIDE_S = 2.0  # a split pause must leave at least this much speech on each side
FINE_PAUSE_MS = 100  # shortest pause a long stretch or a speaker change may be cut in
SPEAKER_SNAP_S = 1.0  # a speaker-change cut moves to the nearest pause within this distance
MIN_SPEAKER_PIECE_S = 0.5  # a shorter speaker piece (e.g. a quick "ừ") joins its longer neighbour's line
ASR_CONTEXT_PAD_S = 0.5  # extra audio the ASR hears on each side of a Segment, so its first and last words stay in

ASR_BATCH_SIZE = 16
ASR_MAX_NEW_TOKENS = 512
ALLOWED_LANGUAGES = {"Vietnamese", "English", "French"}  # a Segment detected as anything else is redone
FALLBACK_LANGUAGE = "Vietnamese"

# PhoWhisper (spec: "Next: PhoWhisper option")
WHISPER_WINDOW_S = 30.0  # Whisper hears only this much; the rest of a longer clip would be dropped
WHISPER_MAX_NEW_TOKENS = 440  # the decoder holds 448 positions, 4 of them taken by the language/task prompt
WHISPER_NO_REPEAT_NGRAM = 10  # tokens, about 4 Vietnamese syllables: stops repetition loops, not normal speech
REPETITIVE_COMPRESSION_RATIO = 2.4  # Whisper's own threshold: text that compresses this well is mostly repeats

# Glossary second pass (spec: "Glossary context")
TERM_MATCH_THRESHOLD = 0.7  # syllable similarity a window of first-pass text needs to count as a term
SHORT_TERM_MATCH_THRESHOLD = 0.8  # stricter for 1–2 syllable terms, which otherwise match common phrases
MAX_TERMS_PER_SEGMENT = 3  # a long context makes the ASR worse on the terms and lets it copy them in
# Onsets longest first, each mapped to a sound group, so onsets that sound alike (in the Southern accent too) match
ONSETS = [
    ("ngh", "ng"), ("ng", "ng"), ("nh", "nh"), ("ch", "ch"), ("tr", "ch"), ("gh", "g"), ("gi", "d"), ("kh", "kh"),
    ("ph", "ph"), ("qu", "c"), ("th", "th"), ("b", "b"), ("c", "c"), ("k", "c"), ("q", "c"), ("d", "d"),
    ("r", "d"), ("v", "d"), ("g", "g"), ("h", "h"), ("l", "l"), ("m", "m"), ("n", "n"), ("p", "p"),
    ("s", "s"), ("x", "s"), ("t", "t"),
]

log = logging.getLogger("transcribe_audio")


@dataclass
class Span:
    """A stretch of the recording in seconds: a speaker turn, a pause, a speech region, or a final Segment."""

    start: float
    end: float
    speaker: str | None = None
    pad_before: float = 0.0  # extra audio the ASR hears before start (a Segment only; see pad_segments)
    pad_after: float = 0.0

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def middle(self) -> float:
        return (self.start + self.end) / 2


def decode_audio(path: Path, declip: bool) -> np.ndarray:
    """Decode any ffmpeg-readable file to a 16 kHz mono float32 waveform.

    With declip, clipped peaks are repaired (ffmpeg's adeclip) at the original sample rate, before resampling: the
    loudest speech is where the ASR made up text. Uses the ffmpeg binary bundled with imageio-ffmpeg, since the compute
    machine has no system ffmpeg. review_transcript.py decodes the same way.
    """
    from imageio_ffmpeg import get_ffmpeg_exe

    cmd = [get_ffmpeg_exe(), "-nostdin", "-loglevel", "error", "-i", str(path)]
    if declip:
        cmd += ["-af", "aformat=channel_layouts=mono,adeclip"]
    cmd += ["-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"]
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
        min_speakers=MIN_SPEAKERS,
        max_speakers=MAX_SPEAKERS,
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


def whisper_parts(segment: Span) -> list[Span]:
    """The Segment cut into equal parts that fit WHISPER_WINDOW_S with their padding, or the Segment itself if it fits.

    Only the outer parts keep the Segment's padding; the inner ones touch each other. Sizing parts by the window less
    both paddings keeps the outer parts, padding included, inside the window too.
    """
    parts = int(np.ceil(segment.duration / (WHISPER_WINDOW_S - segment.pad_before - segment.pad_after)))
    if parts <= 1:
        return [segment]
    log.warning(
        "Forced %d cuts in %s–%s (%.1fs) to fit PhoWhisper's 30 s window",
        parts - 1, format_time(segment.start), format_time(segment.end), segment.duration,
    )
    step = segment.duration / parts
    cut = [Span(segment.start + k * step, segment.start + (k + 1) * step, segment.speaker) for k in range(parts)]
    cut[0].pad_before, cut[-1].pad_after = segment.pad_before, segment.pad_after
    return cut


def fit_whisper_window(segments: list[Span]) -> list[Span]:
    """Cut each Segment still too long for Whisper's window (no usable pause) into equal parts, each its own line."""
    return [part for segment in segments for part in whisper_parts(segment)]


def pad_segments(segments: list[Span], length: float) -> None:
    """Let the ASR hear up to ASR_CONTEXT_PAD_S beyond each Segment, stopping at the middle of the gap to a neighbour.

    A Segment's first or last word can fall just outside its VAD edges and get dropped. The middle-of-gap limit keeps
    a neighbour's words out. Timestamps stay the Segment's own.
    """
    for i, segment in enumerate(segments):
        earliest = (segments[i - 1].end + segment.start) / 2 if i > 0 else 0.0
        latest = (segment.end + segments[i + 1].start) / 2 if i + 1 < len(segments) else length
        segment.pad_before = max(0.0, min(ASR_CONTEXT_PAD_S, segment.start - earliest))
        segment.pad_after = max(0.0, min(ASR_CONTEXT_PAD_S, latest - segment.end))


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


def is_unexpected_language(language: str) -> bool:
    """True if the detected language (e.g. "Vietnamese,English") holds one outside ALLOWED_LANGUAGES.

    An empty language means the ASR heard nothing, which is not unexpected.
    """
    return bool(language) and not set(language.split(",")) <= ALLOWED_LANGUAGES


def load_asr_model():
    from qwen_asr import Qwen3ASRModel

    return Qwen3ASRModel.from_pretrained(
        ASR_MODEL,
        dtype=torch.bfloat16,
        device_map="cuda:0",
        max_inference_batch_size=ASR_BATCH_SIZE,
        max_new_tokens=ASR_MAX_NEW_TOKENS,
    )


def clip_of(audio: np.ndarray, segment: Span) -> tuple[np.ndarray, int]:
    """The audio the ASR hears for a Segment: the Segment and its padding."""
    start = max(0, int((segment.start - segment.pad_before) * SAMPLE_RATE))
    return audio[start:int((segment.end + segment.pad_after) * SAMPLE_RATE)], SAMPLE_RATE


def transcribe_segments(model, audio: np.ndarray, segments: list[Span]) -> list[str]:
    """First pass: every Segment with an empty context."""
    texts: list[str] = []
    for i in range(0, len(segments), ASR_BATCH_SIZE):
        batch = segments[i:i + ASR_BATCH_SIZE]
        clips = [clip_of(audio, s) for s in batch]
        # language=None: auto-detect, so Vietnamese with English/French mixed in stays as spoken
        results = model.transcribe(audio=clips, context="", language=None)
        batch_texts = [r.text.strip() for r in results]
        # A short clip is sometimes heard as another language (e.g. Cantonese); redo those as Vietnamese
        redo = [j for j, r in enumerate(results) if is_unexpected_language(r.language)]
        if redo:
            forced = model.transcribe(audio=[clips[j] for j in redo], context="", language=FALLBACK_LANGUAGE)
            for j, r in zip(redo, forced):
                log.info(
                    "Redid %s–%s as %s (detected %s)",
                    format_time(batch[j].start), format_time(batch[j].end), FALLBACK_LANGUAGE, results[j].language,
                )
                batch_texts[j] = r.text.strip()
        texts.extend(batch_texts)
        log.info("Transcribed %d/%d segments", len(texts), len(segments))
    return texts


def load_phowhisper():
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    processor = WhisperProcessor.from_pretrained(PHOWHISPER_MODEL)
    model = WhisperForConditionalGeneration.from_pretrained(PHOWHISPER_MODEL, dtype=torch.bfloat16).to("cuda:0")
    return processor, model


def is_repetitive(text: str) -> bool:
    data = text.encode("utf-8")
    return len(data) / len(zlib.compress(data)) > REPETITIVE_COMPRESSION_RATIO


def transcribe_segments_phowhisper(processor, model, audio: np.ndarray, segments: list[Span]) -> list[str]:
    """Every Segment as Vietnamese; a part whose text is still mostly repeats is logged but kept.

    A Segment too long for Whisper's window is transcribed in parts (whisper_parts) and their texts joined.
    """
    owners, parts = [], []
    for n, segment in enumerate(segments):
        for part in whisper_parts(segment):
            owners.append(n)
            parts.append(part)

    part_texts: list[str] = []
    for i in range(0, len(parts), ASR_BATCH_SIZE):
        batch = parts[i:i + ASR_BATCH_SIZE]
        clips = [clip_of(audio, s)[0] for s in batch]
        features = processor(clips, sampling_rate=SAMPLE_RATE, return_tensors="pt").input_features
        with torch.inference_mode():
            ids = model.generate(
                features.to("cuda:0", torch.bfloat16),
                language="vi",
                task="transcribe",
                max_new_tokens=WHISPER_MAX_NEW_TOKENS,
                no_repeat_ngram_size=WHISPER_NO_REPEAT_NGRAM,
            )
        batch_texts = [text.strip() for text in processor.batch_decode(ids, skip_special_tokens=True)]
        for part, text in zip(batch, batch_texts):
            if is_repetitive(text):
                log.warning(
                    "Mostly repeats in %s–%s, kept as is: %s",
                    format_time(part.start), format_time(part.end), text[:120],
                )
        part_texts.extend(batch_texts)
        log.info("Transcribed %d/%d parts", len(part_texts), len(parts))

    texts = [""] * len(segments)
    for n, text in zip(owners, part_texts):
        texts[n] = f"{texts[n]} {text}".strip() if text else texts[n]
    return texts


def read_glossary(path: Path) -> list[str]:
    """Terms separated by commas or newlines."""
    terms = re.split(r"[,\n]", path.read_text(encoding="utf-8"))
    return [term.strip() for term in terms if term.strip()]


def syllables(text: str) -> list[str]:
    """Lowercased, accent-free syllables (đ → d), so a misspelt term can still be compared with the right one."""
    stripped = "".join(
        c for c in unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
        if unicodedata.category(c) != "Mn"
    )
    return re.findall(r"\w+", stripped)


def split_syllable(syllable: str) -> tuple[str, str]:
    """(onset sound group, rhyme), e.g. "nguyet" → ("ng", "uyet")."""
    for onset, group in ONSETS:
        if syllable.startswith(onset) and len(syllable) > len(onset):
            return group, syllable[len(onset):]
    return "", syllable


def syllable_similarity(a: str, b: str) -> float:
    """Some credit for the same onset sound, more for how alike the rhymes are: a mishearing usually keeps one."""
    onset_a, rhyme_a = split_syllable(a)
    onset_b, rhyme_b = split_syllable(b)
    return 0.3 * (onset_a == onset_b) + 0.7 * difflib.SequenceMatcher(None, rhyme_a, rhyme_b).ratio()


def match_term(term: list[str], text: list[str]) -> tuple[int, float]:
    """How many non-overlapping k-syllable windows in the text sound like the k-syllable term, and the best score.

    A window's score is the mean similarity of its syllables paired with the term's, since a mishearing usually
    swaps single syllables ("tông kỳ của độ" for "Tam Kỳ Phổ Độ").
    """
    k = len(term)
    threshold = SHORT_TERM_MATCH_THRESHOLD if k <= 2 else TERM_MATCH_THRESHOLD
    candidates = []
    for start in range(len(text) - k + 1):
        window = text[start:start + k]
        score = sum(syllable_similarity(a, b) for a, b in zip(window, term)) / k
        if score >= threshold:
            candidates.append((score, start, start + k))
    taken: list[tuple[int, int]] = []
    for _, start, end in sorted(candidates, reverse=True):
        if all(end <= a or start >= b for a, b in taken):
            taken.append((start, end))
    return len(taken), max((score for score, _, _ in candidates), default=0.0)


def exact_count(term: list[str], text: list[str]) -> int:
    k = len(term)
    return sum(text[start:start + k] == term for start in range(len(text) - k + 1))


def terms_for(text: str, glossary: list[str]) -> dict[str, int]:
    """The Segment's best-matching terms (at most MAX_TERMS_PER_SEGMENT), each with its match count."""
    words = syllables(text)
    scored = []
    for term in glossary:
        count, score = match_term(syllables(term), words)
        if count:
            scored.append((score, term, count))
    return {term: count for _, term, count in sorted(scored, reverse=True)[:MAX_TERMS_PER_SEGMENT]}


def leaked_term(text: str, matched: dict[str, int]) -> str | None:
    """A context term the second pass wrote more often than the first pass matched it, i.e. one it copied in."""
    words = syllables(text)
    for term, count in matched.items():
        if exact_count(syllables(term), words) > count:
            return term
    return None


def apply_glossary(model, audio: np.ndarray, segments: list[Span], texts: list[str], glossary: list[str]) -> list[str]:
    """Second pass: redo each Segment that sounds like some glossary terms, with just those terms as context.

    Never the whole glossary: a long list makes the ASR worse on the terms and lets it copy them into the text.
    """
    jobs = []
    for i, text in enumerate(texts):
        matched = terms_for(text, glossary)
        words = syllables(text)
        if any(exact_count(syllables(term), words) < count for term, count in matched.items()):
            jobs.append((i, matched))
    log.info("Redoing %d segments with glossary terms", len(jobs))

    texts = list(texts)
    for b in range(0, len(jobs), ASR_BATCH_SIZE):
        batch = jobs[b:b + ASR_BATCH_SIZE]
        results = model.transcribe(
            audio=[clip_of(audio, segments[i]) for i, _ in batch],
            context=[", ".join(matched) for _, matched in batch],
            language=None,
        )
        for (i, matched), r in zip(batch, results):
            span = f"{format_time(segments[i].start)}–{format_time(segments[i].end)}"
            text = r.text.strip()
            leaked = leaked_term(text, matched)
            if not text or is_unexpected_language(r.language) or leaked:
                reason = f"copied in {leaked!r}" if leaked else f"empty or detected {r.language!r}"
                log.info("Kept first pass for %s with %s (%s)", span, list(matched), reason)
                continue
            log.info("Redid %s with %s", span, list(matched))
            texts[i] = text
    return texts


def format_time(seconds: float) -> str:
    tenths = round(seconds * 10)
    hours, rest = divmod(tenths, 36000)
    minutes, rest = divmod(rest, 600)
    return f"{hours:02d}:{minutes:02d}:{rest / 10:04.1f}"


def person_names(segments: list[Span]) -> dict[str, str]:
    """Speakers are numbered Person 1, Person 2, ... in the order they are first heard."""
    names: dict[str, str] = {}
    for segment in segments:
        if segment.speaker is not None and segment.speaker not in names:
            names[segment.speaker] = f"Person {len(names) + 1}"
    return names


def write_transcript(path: Path, segments: list[Span], texts: list[str], keep: list[bool] | None = None) -> int:
    """Write one line per Segment in keep (default: each Segment the ASR heard something in)."""
    names = person_names(segments)
    lines = []
    for segment, text, kept in zip(segments, texts, keep or [bool(t) for t in texts]):
        if not kept:
            continue
        prefix = f"{names[segment.speaker]}: " if segment.speaker is not None else ""
        lines.append(f"[{format_time(segment.start)} → {format_time(segment.end)}] {prefix}{text}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe one recording into timestamped, speaker-labelled lines.")
    parser.add_argument("audio", type=Path, help="audio file (any format ffmpeg reads, e.g. .m4a)")
    parser.add_argument("--no-speakers", action="store_true", help="skip speaker labels (no Hugging Face token needed)")
    parser.add_argument(
        "--context", type=Path,
        help="text file of terms the speakers use (names, foreign phrases), given to the ASR so it spells them right",
    )
    parser.add_argument(
        "--phowhisper", action="store_true",
        help=f"transcribe with {PHOWHISPER_MODEL} (Vietnamese only, no --context) instead of {ASR_MODEL}",
    )
    parser.add_argument(
        "--with-phowhisper", action="store_true",
        help=f"also transcribe the same Segments with {PHOWHISPER_MODEL}, into a second file with identical lines",
    )
    parser.add_argument("--no-declip", action="store_true", help="don't repair clipped peaks before transcribing")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.audio.is_file():
        sys.exit(f"[ERROR] Audio file not found: {args.audio}")
    if args.context is not None and not args.context.is_file():
        sys.exit(f"[ERROR] Context file not found: {args.context}")
    if args.phowhisper and args.context is not None:
        sys.exit("[ERROR] --context is Qwen3-ASR only; drop it to run with --phowhisper.")
    if args.phowhisper and args.with_phowhisper:
        sys.exit("[ERROR] --phowhisper and --with-phowhisper can't be combined; pick one.")
    if not torch.cuda.is_available():
        sys.exit("[ERROR] No GPU visible. Run this on a compute node with a GPU.")

    pipeline = None if args.no_speakers else load_diarization_pipeline()

    log.info("Decoding %s%s", args.audio, "" if args.no_declip else ", repairing clipped peaks")
    audio = decode_audio(args.audio, declip=not args.no_declip)
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

    pad_segments(segments, len(audio) / SAMPLE_RATE)
    if args.phowhisper:
        segments = fit_whisper_window(segments)

    qwen_path = args.audio.with_name(f"{args.audio.stem}.transcript.txt")
    phowhisper_path = args.audio.with_name(f"{args.audio.stem}.phowhisper.transcript.txt")
    if args.phowhisper:
        texts = transcribe_segments_phowhisper(*load_phowhisper(), audio, segments)
        count = write_transcript(phowhisper_path, segments, texts)
        log.info("Wrote %d lines to %s", count, phowhisper_path)
        return

    model = load_asr_model()
    texts = transcribe_segments(model, audio, segments)
    if args.context is not None:
        texts = apply_glossary(model, audio, segments, texts, read_glossary(args.context))
    count = write_transcript(qwen_path, segments, texts)
    log.info("Wrote %d lines to %s", count, qwen_path)
    if not args.with_phowhisper:
        return

    del model
    torch.cuda.empty_cache()
    second = transcribe_segments_phowhisper(*load_phowhisper(), audio, segments)
    # The same lines as the Qwen file, so the review can pair them: a line only PhoWhisper heard nothing in stays
    count = write_transcript(phowhisper_path, segments, second, keep=[bool(t) for t in texts])
    log.info("Wrote %d lines to %s", count, phowhisper_path)


if __name__ == "__main__":
    main()

Status: implemented

# Audio Transcribe: timestamped, speaker-labelled transcript of one recording

## Problem Statement

`vsc-project/audio-transcribe/1.m4a` is a 47-minute recording (stereo AAC, 44.1 kHz). It is mostly Vietnamese, with some English and French mixed in, and has two speakers. We want a readable transcript of it. Each line should carry its time range and who is speaking, so a person can find any passage in the audio. The chosen speech model is `Qwen/Qwen3-ASR-1.7B`. It runs on the compute machine.

The Qwen timestamp model (`Qwen/Qwen3-ForcedAligner-0.6B`) can't be used. It does not support Vietnamese (it covers 11 languages: zh, en, yue, fr, de, it, ja, ko, pt, ru, es) and it handles at most 5 minutes per call. Timestamps must come from how the audio is cut instead.

## Solution

- **Where it lives.**
  - Code: `src/cli/transcribe_audio.py`. It is standalone and imports nothing from `src`.
  - Runner: `scripts/transcribe_audio.sh`.
  - Dependencies: `requirements-audio.txt`.
  - Guide: `docs/audio-transcribe.md`.

  The dependencies can't join the root `requirements.txt`, because `qwen-asr==0.0.6` pins `transformers==4.57.6` and `accelerate==1.12.0`, while the root pins 5.13.0 and 1.14.0 for vLLM. The transcriber therefore runs in its own venv on the compute machine. `vsc-project/` is gitignored and holds only the audio.
- **Run by hand on the compute node.** Usage is `bash scripts/transcribe_audio.sh path/to/audio.m4a [--no-speakers]`.
  - The script assumes the venv is already set up.
  - It never installs anything and never submits to SLURM.
  - It writes `<input-stem>.transcript.txt` next to the input, e.g. `1.transcript.txt`.
- **Output format: text only.** One line per segment:

  ```
  [HH:MM:SS.s → HH:MM:SS.s] Person N: text
  ```

  The file has no SRT, no JSON, no word-level times and no language tag.
- **Speakers (pyannote `speaker-diarization-community-1`).**
  - The speaker count is fixed at 2.
  - The script uses the *exclusive* speaker diarization output, which gives exactly one speaker at any moment. Overlapping speech goes to the dominant speaker.
  - The speaker heard first in the recording is **Person 1**, the other is **Person 2**. The user renames them by hand afterwards.
  - A storyteller doing a character's voice is still the same person, but pyannote may mislabel such a stretch. This is accepted.
  - A speaker-change cut is moved to the middle of the nearest pause (within 1 s) to pyannote's boundary, since that boundary can be off by a few hundred ms and fall mid-word. With no pause nearby, the boundary itself is used.
  - A speaker piece shorter than 0.5 s, such as a quick "ừ" from the other person, joins its longer neighbour's line and takes that line's label. This is accepted.
- **Cutting the audio (Silero VAD) so speech is never cut.** Inside each speaker turn, Silero VAD finds the speech. Then:
  - A cut is made only inside a pause of at least 0.5 s.
  - 0.2 s of padding is kept on each side, so word onsets and endings stay in.
  - Speech pieces less than about 1 s apart are joined into one segment.
  - A segment is capped at about 30 s. A longer stretch is split at the middle of its longest internal pause, never at a hard time mark. The cap wins over the 0.5 s rule: a long stretch has no pauses of 0.5 s or more, so its split pause may be as short as 0.1 s. A stretch with no pause at all stays whole.
  - A segment never crosses a speaker change.
- **Timestamps.** Each segment's start and end in the original recording are its timestamps, accurate to about ±0.2 s at the edges.
- **Empty segments.** A segment the ASR hears nothing in is left out of the transcript.
- **Transcription.** Each segment goes through Qwen3-ASR-1.7B with the language left on auto-detect (`language=None`), so Vietnamese with English and French mixed in stays as spoken. It uses the plain transformers backend (`qwen-asr`), not vLLM, in bf16 on one GPU. The output is a transcript, never a translation.
- **When pyannote can't run.** If `HF_TOKEN` is missing or the model's terms haven't been accepted, the script stops early with a clear error, before loading the ASR model. `--no-speakers` skips speaker labels on purpose, and the lines then have no `Person N:` prefix.
- **Setup steps (`docs/audio-transcribe.md`).**
  1. Create the venv and install `requirements.txt`. ffmpeg must be on the PATH.
  2. Create a Hugging Face account and accept the terms on the `pyannote/speaker-diarization-community-1` model page.
  3. Create a read token at hf.co/settings/tokens and `export HF_TOKEN=...` on the compute machine.
  4. Run the shell file.

## Out of Scope

- Translation.
- Word-level timestamps, SRT and JSON output.
- SLURM batch submission.
- Speaker naming beyond Person 1 / Person 2.
- Glossary entries: the root `CONTEXT.md` is the resume-pipeline glossary and stays untouched.

## Comments

- 2026-10-19: Q16 confirmed: stop early without HF_TOKEN; `--no-speakers` gives lines with no `Person N:` prefix. Implemented in `vsc-project/audio-transcribe/`.
- 2026-10-19: After code review: moved into the tracked repo (`src/cli`, `scripts`, `requirements-audio.txt`, `docs`); speaker-change cuts now snap to the nearest pause; short speaker pieces take the longer neighbour's label; the 30 s cap is allowed to cut in sub-0.5 s pauses.

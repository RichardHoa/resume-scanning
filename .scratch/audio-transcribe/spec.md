Status: implemented (uncommitted)

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
- **Run by hand on the compute node.** Usage is `bash scripts/transcribe_audio.sh path/to/audio.m4a [--no-speakers] [--context FILE]`.
  - The script assumes the venv is already set up.
  - It never installs anything and never submits to SLURM.
  - It writes `<input-stem>.transcript.txt` next to the input, e.g. `1.transcript.txt`.
- **Output format: text only.** One line per segment:

  ```
  [HH:MM:SS.s → HH:MM:SS.s] Person N: text
  ```

  The file has no SRT, no JSON, no word-level times and no language tag.
- **Speakers (pyannote `speaker-diarization-community-1`).**
  - The speaker count is 2 to 4 (`min_speakers=2, max_speakers=4`), not fixed at 2. Interviews can have other people in the room (e.g. students asking or answering questions). With the count forced to 2, a third voice can push the interviewer's voice into the interviewee's cluster.
  - The script uses the *exclusive* speaker diarization output, which gives exactly one speaker at any moment. Overlapping speech goes to the dominant speaker.
  - Speakers are numbered **Person 1**, **Person 2**, … **Person N** in the order they are first heard. The user renames them by hand afterwards.
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
- **Glossary context (`--context FILE`).** This is optional. It names a plain-text file of terms the speakers use, kept next to the audio (e.g. `vsc-project/audio-transcribe/1.context.txt`). Its text is passed to every segment as Qwen3-ASR's `context=` (the model's system prompt), so proper nouns and foreign phrases are spelt correctly. Without the flag the context is empty and the behaviour is the same as before. Each recording has its own vocabulary, so the file belongs to the recording and is not in the script. The first file, `1.context.txt`, lists:

  ```
  Bác Cảnh, Đức Hộ Pháp, Hộ Pháp Đường, Đức Chí Tôn, Đại Đạo Tam Kỳ Phổ Độ, Cao Đài, Caodaïsme,
  Hội Thánh Ngoại Giáo, Chưởng Đạo Nguyệt Tâm Chơn Nhơn, Victor Hugo, François-Victor Hugo, petit-fils,
  Đức Lý Thái Bạch, Đức Quyền Giáo Tông, Ngô Minh Chiêu, Nam Kỳ, Nội Ứng Binh, quân đội Cao Đài,
  Troisième Amnistie de Dieu en Orient, Missions Étrangères de Caodaï, Allan Kardec, Janet Hoskins, cơ duyên
  ```

  Phrases nobody could identify (*con lít*, *nari*, *krisat*, *chữ đài loan*, *ông già bá công*) are left out.
- **Language guard.** After each batch, a clip whose detected `.language` contains anything other than Vietnamese, English or French is transcribed again with `language="Vietnamese"` forced, and the forced text replaces the first one. A log line names each clip that was redone. This catches short clips misread as another language (e.g. a 1.1 s clip that came out as Cantonese `而家講係機。`). Auto-detection stays on for every other clip, so code-switching is kept.
- **When pyannote can't run.** If `HF_TOKEN` is missing or the model's terms haven't been accepted, the script stops early with a clear error, before loading the ASR model. `--no-speakers` skips speaker labels on purpose, and the lines then have no `Person N:` prefix.
- **Docs.** `docs/audio-transcribe.md` documents `--context FILE` with a short example, and says the speaker count is 2 to 4.
- **Setup steps (`docs/audio-transcribe.md`).**
  1. Create the venv and install `requirements-audio.txt`. No system ffmpeg is needed: the compute machine has none (no `ffmpeg` module), so audio is decoded with the ffmpeg binary bundled in `imageio-ffmpeg`.
  2. Create a Hugging Face account and accept the terms on the `pyannote/speaker-diarization-community-1` model page.
  3. Create a read token at hf.co/settings/tokens and `export HF_TOKEN=...` on the compute machine.
  4. Run the shell file.

## Out of Scope

- Translation.
- Word-level timestamps, SRT and JSON output.
- SLURM batch submission.
- Speaker naming beyond Person 1 / Person 2.
- An LLM cleanup pass over the transcript (it would quietly change what was said).
- Normalising punctuation or capitalisation: the model's output is kept as is, even though it varies from segment to segment.
- Glossary entries: the root `CONTEXT.md` is the resume-pipeline glossary and stays untouched.

## Comments

- 2026-10-19: Q16 confirmed: stop early without HF_TOKEN; `--no-speakers` gives lines with no `Person N:` prefix. Implemented in `vsc-project/audio-transcribe/`.
- 2026-10-19: After code review: moved into the tracked repo (`src/cli`, `scripts`, `requirements-audio.txt`, `docs`); speaker-change cuts now snap to the nearest pause; short speaker pieces take the longer neighbour's label; the 30 s cap is allowed to cut in sub-0.5 s pauses.
- 2026-10-19: Accuracy pass after reviewing the first 7.5 minutes of `1.transcript.txt`. Errors found:
  - Cao Đài names misheard (Đại Đạo Tam Kỳ Phổ Độ came out six different ways; Nguyệt Tâm Chơn Nhơn as "việt tâm chân nhân").
  - French garbled ("Troisième Amnistie de Dieu en Orient" came out as "Prozium Amnesty the year ăn norian").
  - A Cantonese hallucination on a 1.1 s clip.
  - Interviewer lines at 00:01:41–00:01:49 and 00:06:36–00:06:57 labelled as the interviewee.

  Decided:
  - `--context FILE` glossary.
  - Re-transcribe forced to Vietnamese any clip detected as a language other than vi/en/fr.
  - 2 to 4 speakers.
  - No LLM cleanup.
  - Punctuation left as is.

  The interviewer mislabels are put down to the forced 2-speaker count rather than to the cutting rules: the 8 s stretch is far above the 0.5 s short-piece rule, and snapping a cut only moves it, it never removes it. Testing is manual: the developer reruns on the compute machine and compares.

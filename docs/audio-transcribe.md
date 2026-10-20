# Audio Transcribe

Turns one recording into a transcript with timestamps and speaker labels:

```
[00:12:03.4 → 00:12:11.9] Person 2: ...
```

- **Transcription:** `Qwen/Qwen3-ASR-1.7B`, with the language auto-detected. Vietnamese with English or French mixed in stays as spoken.
- **Speakers:** `pyannote/speaker-diarization-community-1`, with 2 to 4 speakers. They are numbered **Person 1**, **Person 2**, … in the order they are first heard.
- **Audio repair:** clipped peaks are repaired with ffmpeg's `adeclip` before anything hears the audio, since the loudest, clipped speech is where the models made up text. `--no-declip` turns this off, for comparison.
- **Cutting:** Silero VAD. The audio is only ever cut inside a pause, so no word is split. Each model hears up to 0.5 s more on each side of a line (never past the middle of the gap to the next line), so first and last words aren't dropped. The timestamps stay the line's own.
- **Language guard:** a segment detected as a language other than Vietnamese, English or French (e.g. a short clip heard as Cantonese) is transcribed again as Vietnamese. The log names each segment that was redone.
- **Glossary (optional):** segments that sound like terms from a `--context` file are transcribed again with just those terms (see below).

The code is `src/cli/transcribe_audio.py`. The design is in `.scratch/audio-transcribe/spec.md`.

## One-time setup (on the compute machine)

### 1. Make a separate venv

Keep this apart from the resume pipeline's venv. `qwen-asr` pins `transformers==4.57.6` and `accelerate==1.12.0`, which conflict with the root `requirements.txt` (`transformers==5.13.0` and `accelerate==1.14.0`, needed by vLLM). That's why its dependencies live in `requirements-audio.txt`. Run these from the repo root:

```bash
python3.12 -m venv ~/venvs/audio-transcribe
source ~/venvs/audio-transcribe/bin/activate
pip install -r requirements-audio.txt
```

No system ffmpeg is needed: `imageio-ffmpeg` in `requirements-audio.txt` brings its own ffmpeg binary, which the script uses to decode the audio.

### 2. Get access to the speaker model (needed for Person 1 / Person 2)

1. Log in at https://huggingface.co (create a free account if needed).
2. Open https://huggingface.co/pyannote/speaker-diarization-community-1 and accept the user conditions. This asks for your contact info.
3. Create a **Read** token at https://huggingface.co/settings/tokens.
4. On the compute machine, add it to `~/.bashrc` so every session has it:

   ```bash
   echo 'export HF_TOKEN=hf_xxxxxxxxxxxxxxxx' >> ~/.bashrc
   source ~/.bashrc
   ```

Without the token the script stops right away with an error. To skip speaker labels instead, run with `--no-speakers`.

## Run

On a compute node with a GPU, from the repo root, with the venv active:

```bash
source ~/venvs/audio-transcribe/bin/activate
bash scripts/transcribe_audio.sh vsc-project/audio-transcribe/1.m4a
```

This writes `vsc-project/audio-transcribe/1.transcript.txt`.

### Glossary context (optional)

The model misspells names and foreign phrases it hasn't heard before (e.g. "Đại Đạo Tam Kỳ Phổ Độ", "Troisième Amnistie de Dieu en Orient"). List the terms the speakers use in a text file next to the audio and pass it with `--context`:

```bash
bash scripts/transcribe_audio.sh vsc-project/audio-transcribe/1.m4a --context vsc-project/audio-transcribe/1.context.txt
```

The file is plain text, e.g. comma-separated terms:

```
Bác Cảnh, Đức Hộ Pháp, Hộ Pháp Đường, Đại Đạo Tam Kỳ Phổ Độ, Victor Hugo, Troisième Amnistie de Dieu en Orient
```

Terms are separated by commas or newlines. The whole list is never sent to every segment, since a long list makes the model worse and lets it copy terms into the transcript. Instead:

1. Every segment is transcribed once with no context.
2. A segment whose text sounds like some terms (e.g. "đại đạo tông kỳ của độ" for "Đại Đạo Tam Kỳ Phổ Độ") is transcribed again with just those terms, at most 3.
3. The new text is kept only if it doesn't write a term more often than the first pass heard it. The log names each segment redone, and each one where the first pass was kept.

Only list terms you are sure of, since a wrong spelling will be copied. A long title also matches better if its core is listed on its own too (e.g. "Nguyệt Tâm Chơn Nhơn" next to "Chưởng Đạo Nguyệt Tâm Chơn Nhơn").

The first run downloads the models, about 5 GB in total, into `~/.cache/huggingface`.

### PhoWhisper instead of Qwen3-ASR (optional)

To compare with a Vietnamese-tuned Whisper, add `--phowhisper`. The segments are transcribed by `vinai/PhoWhisper-large` instead of Qwen3-ASR; speakers, timestamps and the line format stay the same:

```bash
bash scripts/transcribe_audio.sh vsc-project/audio-transcribe/1.m4a --phowhisper
```

This writes `vsc-project/audio-transcribe/1.phowhisper.transcript.txt`, next to the Qwen transcript rather than over it.

- Every segment is transcribed as Vietnamese, so English and French words come out however the model hears them.
- `--context` can't be combined with it; the script stops with an error.
- `--with-phowhisper` runs Qwen3-ASR as usual (with `--context`), then PhoWhisper on **the same lines**, and writes both `1.transcript.txt` and `1.phowhisper.transcript.txt`. A line longer than 30 s is transcribed by PhoWhisper in parts, whose texts are joined back into the one line. A line PhoWhisper heard nothing in stays, with empty text. The review pass needs both files. It can't be combined with `--phowhisper`.
- Whisper hears only 30 s at a time, so a segment longer than that (no pause to cut at) is cut into equal parts, with a warning in the log.
- A segment whose text is mostly the same phrase repeated (a Whisper failure on silence or noise) is logged but kept.

The first run downloads PhoWhisper-large, about 6 GB, into the same cache.

## Full job: two drafts, Qwen3-Omni review, names pass, score (SLURM)

`scripts/submit_transcript.sh` runs the whole job for `vsc-project/audio-transcribe/1.m4a` in one go. It takes no flags:

```bash
sbatch scripts/submit_transcript.sh
```

1. **Two drafts.** It transcribes the recording with `1.context.txt` and `--with-phowhisper` in the audio venv (`~/venvs/audio-transcribe`). Draft A is `1.transcript.txt` (Qwen3-ASR) and draft B is `1.phowhisper.transcript.txt`. Existing copies are first renamed to `<name>.<time>.txt`, so hand-written notes in them are kept.
2. **Review.** It serves `Qwen/Qwen3-Omni-30B-A3B-Instruct` with vLLM in `resume_env` and runs `src/cli/review_transcript.py 1.m4a 1.transcript.txt --second 1.phowhisper.transcript.txt` (`--second` is draft B, and must have the same lines as draft A). For each line, the model:
   - hears the line's clip, repaired and padded the way the transcriber heard it;
   - reads both drafts, a merged view of where they differ (`Đức Hộ Pháp nằm {A: giống | B: võng} tới`), the two lines before and after, and the glossary;
   - writes what it hears.
3. **Names.** On the same server, `src/cli/fix_names.py` reads the reviewed transcript 20 lines at a time, with 60 lines of context on each side. It fixes only names and terms that came out as common words (e.g. "có tài" → Cao Đài), never the speaker's own forms of names.
4. **Score.** If `grouth_truth.txt` exists, the four transcripts are scored against it in the job log (see "Scoring" below).

It writes next to the audio:

- `1.reviewed.transcript.txt`: the same lines, timestamps and speakers, with the reviewed text.
- `1.review.jsonl`: per line, both drafts, the merged view, the reviewed text and a status:
  - `same` or `changed`;
  - `kept draft: …` when draft A was kept. That happens when the answer was empty, more than 30% of it was in neither draft nor the glossary, or its length was outside 0.6–1.5× the drafts'. Lines under 4 syllables are not checked;
  - `failed: …` when the request failed.
- `1.final.transcript.txt`: the reviewed transcript with the names fixed. **This is the one to read.**
- `1.names.jsonl`: every names edit with its line, `old`, `new`, `sure`, and whether it was applied (or why not). An edit is applied only if `old` appears exactly once in the line and neither side is over 8 syllables.

### `[? …]` marks

A stretch the review model couldn't make out is written as `[? best guess]`. When it can make out nothing in a line, the line becomes `[? draft A]`. An unsure name fix is written as `[? new name]`; `1.names.jsonl` holds the old text. Search for `[?` and check those spots by ear.

### The speaker's own forms of names

The speaker says some names his own way (e.g. "Việt Tâm Chân Nhân" for Nguyệt Tâm Chơn Nhơn, "Victor Go" or "Vigo" as well as "Victor Hugo"). Those are what he said and are kept. List them in `1.context.txt` next to the formal names, so the glossary doesn't pull every model towards the formal spelling:

```
Victor Hugo, Victor Go, Vigo, Nguyệt Tâm Chơn Nhơn, Việt Tâm Chân Nhân, ...
```

Add further forms as you check later minutes.

### Scoring

`grouth_truth.txt` is the reference: the first 5 minutes, checked by hand against the audio, with names spelt as spoken. To score any transcripts against it (standard library only, so this runs anywhere, including a laptop):

```bash
python3 src/cli/score_transcript.py vsc-project/audio-transcribe/grouth_truth.txt \
  vsc-project/audio-transcribe/1.transcript.txt vsc-project/audio-transcribe/1.final.transcript.txt \
  --context vsc-project/audio-transcribe/1.context.txt
```

For each file it prints:
- the syllable error rate over the reference's time span (lines are joined, so files cut into different lines still compare);
- term recall for the glossary terms the reference holds;
- the count of `[?` marks.

To check whether the audio repair helps, run `transcribe_audio.py` once by hand with `--no-declip` and score both outputs.

The job needs `HF_TOKEN` set in the shell you submit from. `resume_env` needs the root `requirements.txt`, which includes the audio packages vLLM reads input with (`av`, `soundfile`, `soxr`) and `imageio-ffmpeg`.

The first run downloads Qwen3-Omni (about 60–70 GB) and PhoWhisper-large (about 6 GB) into the HF cache. To delete Qwen3-Omni afterwards:

```bash
rm -rf "$HF_HOME/hub/models--Qwen--Qwen3-Omni-30B-A3B-Instruct"
```

## Afterwards

Once you've read the transcript, rename the speakers by hand, e.g.:

```bash
sed -i 's/Person 1:/Interviewer:/; s/Person 2:/Storyteller:/' 1.transcript.txt
```

pyannote may sometimes put a storyteller's character voice under the other speaker. Spot-check those lines.

# Audio Transcribe

Turns one recording into a transcript with timestamps and speaker labels:

```
[00:12:03.4 → 00:12:11.9] Person 2: ...
```

- **Transcription:** `Qwen/Qwen3-ASR-1.7B`, with the language auto-detected. Vietnamese with English or French mixed in stays as spoken.
- **Speakers:** `pyannote/speaker-diarization-community-1`, with 2 to 4 speakers. They are numbered **Person 1**, **Person 2**, … in the order they are first heard.
- **Cutting:** Silero VAD. The audio is only ever cut inside a pause, so no word is split.
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
- Whisper hears only 30 s at a time, so a segment longer than that (no pause to cut at) is cut into equal parts, with a warning in the log.
- A segment whose text is mostly the same phrase repeated (a Whisper failure on silence or noise) is logged but kept.

The first run downloads PhoWhisper-large, about 6 GB, into the same cache.

## Review pass with Qwen3-Omni (SLURM)

`scripts/submit_transcript.sh` runs the whole job for `vsc-project/audio-transcribe/1.m4a` in one go. It takes no flags:

```bash
sbatch scripts/submit_transcript.sh
```

1. It transcribes the recording with `1.context.txt` in the audio venv (`~/venvs/audio-transcribe`), as above. An existing `1.transcript.txt` is first renamed to `1.transcript.<time>.txt`, so hand-written notes in it are kept.
2. It serves `Qwen/Qwen3-Omni-30B-A3B-Instruct` with vLLM in `resume_env`. For each line, the model hears the line's clip, reads the draft, the lines before and after, and the glossary, then fixes misheard words.

It writes next to the audio:

- `1.reviewed.transcript.txt`: the same lines, timestamps and speakers, with the reviewed text.
- `1.review.jsonl`: per line, the draft, the reviewed text and a status:
  - `same` or `changed`;
  - `kept draft: …` when the answer was empty, or kept less than half of a draft of 4+ syllables;
  - `failed: …` when the request failed.

Submit from a shell where `HF_TOKEN` is set. `resume_env` needs the root `requirements.txt`, which includes the audio packages vLLM reads input with (`av`, `soundfile`, `soxr`) and `imageio-ffmpeg`.

The first run downloads Qwen3-Omni, about 60–70 GB, into the HF cache. To delete it afterwards:

```bash
rm -rf "$HF_HOME/hub/models--Qwen--Qwen3-Omni-30B-A3B-Instruct"
```

## Afterwards

Once you've read the transcript, rename the speakers by hand, e.g.:

```bash
sed -i 's/Person 1:/Interviewer:/; s/Person 2:/Storyteller:/' 1.transcript.txt
```

pyannote may sometimes put a storyteller's character voice under the other speaker. Spot-check those lines.

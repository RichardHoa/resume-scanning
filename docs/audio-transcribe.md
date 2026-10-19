# Audio Transcribe

Turns one recording into a transcript with timestamps and speaker labels:

```
[00:12:03.4 → 00:12:11.9] Person 2: ...
```

- **Transcription:** `Qwen/Qwen3-ASR-1.7B`, with the language auto-detected. Vietnamese with English or French mixed in stays as spoken.
- **Speakers:** `pyannote/speaker-diarization-community-1`, fixed at 2 speakers. Whoever is heard first is **Person 1**.
- **Cutting:** Silero VAD. The audio is only ever cut inside a pause, so no word is split.

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

The first run downloads the models, about 5 GB in total, into `~/.cache/huggingface`.

## Afterwards

Once you've read the transcript, rename the speakers by hand, e.g.:

```bash
sed -i 's/Person 1:/Interviewer:/; s/Person 2:/Storyteller:/' 1.transcript.txt
```

pyannote may sometimes put a storyteller's character voice under the other speaker. Spot-check those lines.

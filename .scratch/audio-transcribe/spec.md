Status: implemented (uncommitted). Next: Qwen3-Omni review pass (implemented, uncommitted; not yet run on the compute machine). Next: PhoWhisper option `--phowhisper` (implemented, uncommitted; not yet run on the compute machine)

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
- **Glossary context (`--context FILE`).** This is optional. It names a plain-text file of terms the speakers use, kept next to the audio (e.g. `vsc-project/audio-transcribe/1.context.txt`). Terms are separated by commas or newlines. Each recording has its own vocabulary, so the file belongs to the recording and is not in the script. Without the flag there is no second pass, and the output is the plain first pass.

  The whole glossary is never sent to every segment. A speech LLM given a long list of terms that mostly aren't in the clip does worse on those terms, and it can copy the list into the transcript (Huber & Waibel, arXiv 2608.05759). Instead there are two passes:
  1. **First pass.** Every segment is transcribed with an empty context, with the language guard below applied.
  2. **Finding terms per segment.** Both the first-pass text and each term are normalised:
     - lowercased;
     - accents stripped, with `đ` turned into `d`;
     - punctuation dropped;
     - split into syllables.

     A term of k syllables is compared with every window of k syllables in the text. Syllables are paired up in order, and the window's score is the mean of the pairs' similarities. A mishearing usually swaps single syllables, so whole-phrase character similarity misses it. Each syllable is split into an onset and a rhyme:
     - **Onset (0.3 of the score).** It counts if both onsets are in the same sound group. Onsets that sound alike, including in the Southern accent, share a group: c/k/q(u), d/gi/r/v, ch/tr, s/x, g/gh, ng/ngh.
     - **Rhyme (0.7 of the score).** Its share is the `difflib` similarity of the two rhymes.

     A window is a match when it scores at least 0.7, or at least 0.8 for a term of 1–2 syllables, which would otherwise match common phrases. For example:
     - "đại đạo tông kỳ của độ" scores 0.72 against "Đại Đạo Tam Kỳ Phổ Độ";
     - "qua đài" scores 0.88 against "Cao Đài";
     - "có cái" does not match "Cao Đài".

     A segment keeps at most its 3 best-scoring terms. On the first run's transcript, 50 of 191 segments would be redone.
  3. **Second pass.** A segment is transcribed again only if at least one of its matched terms is not yet spelt exactly at every place it matched: its exact count (after normalising) in the first-pass text is lower than its match count. Its context is just its own matched terms, comma-separated. The language is left on auto-detect.
  4. **Leak guard.** The second-pass text replaces the first only if these checks pass:
     - It isn't empty.
     - Its language is one of the allowed ones.
     - No context term appears in it more often (exact count after normalising) than it matched in the first pass (count of non-overlapping matching windows).

     Otherwise the first-pass text is kept. This catches the model copying context terms that weren't spoken, as at 00:05:08 of the first run. A log line names each segment redone with its terms, and each second pass that was rejected.

  A term that is wrong in the first pass by more than the 0.75 threshold won't be found. This is accepted: shorter glossary entries (e.g. "Nguyệt Tâm Chơn Nhơn" on its own as well as the full title) match more easily. The first file, `1.context.txt`, lists:

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

## Next: Qwen3-Omni review pass (SLURM job)

Even with the two-pass glossary, the transcript has many misheard words. Most of the developer's corrections are words the conversation gives away:
- "bát cảnh" for "bác Cảnh";
- "đứa Phật", "Đức Phật pháp" and "đức hòa pháp" for "Đức Hộ Pháp";
- "nari đâu" for "narrator của", "quá xin lỗi" for "question list", "cố" for "ký ức của".

Qwen3-ASR's 1.7B decoder only writes down what it hears. The fix is a second model that listens to the same clip, reads the draft and knows the topic: `Qwen/Qwen3-Omni-30B-A3B-Instruct`, served by vLLM. SEA-LION v4.5 27B was ruled out because it can't take audio (text and images only). Qwen3-ASR is built on Qwen3-Omni, so Omni is not expected to hear better, only to understand the conversation better.

- **One SLURM job, no flags: `sbatch scripts/submit_transcript.sh`.** It runs exactly one setup, with its inputs fixed in the script:
  - audio `vsc-project/audio-transcribe/1.m4a`;
  - glossary `vsc-project/audio-transcribe/1.context.txt`.

  There is no model choice, no reference transcript and no scoring. The developer checks the output by hand.
- **Step 1: transcribe (the audio venv).** The job activates `~/venvs/audio-transcribe` and runs `src/cli/transcribe_audio.py 1.m4a --context 1.context.txt`, unchanged. This writes a fresh `1.transcript.txt`.
  - An existing `1.transcript.txt` (which may hold the developer's bracketed notes) is first renamed to `1.transcript.<YYYYmmdd-HHMMSS>.txt`, so nothing hand-written is lost.
  - `HF_TOKEN` must be in the environment `sbatch` is run from, since pyannote needs it.
  - The process exits before step 2, so the GPU is free for vLLM.
- **Step 2: review (the root venv, `resume_env`).** The job serves Qwen3-Omni with vLLM through `scripts/vllm_utils.sh`, the same way as the other jobs. It runs `src/cli/review_transcript.py`, then stops the server.
  - Serving flags: `--limit-mm-per-prompt.audio 1`, with `.image 0` and `.video 0`. Only text output is used (no speech output).
  - The model is set in the job script, not added to `model_profiles.sh`, so it doesn't join the profile list the other jobs and the bias suite use.
  - At most 16 requests are in flight.
- **One request per Segment.** Each line of `1.transcript.txt` is one Segment. Its clip is cut from `1.m4a` at the line's timestamps, decoded to 16 kHz mono with `imageio-ffmpeg`, and sent as a WAV `input_audio` part. With it go:
  - a short topic note: an interview in Vietnamese with an elderly Southern-accented Cao Đài follower, with English and French words mixed in;
  - the whole glossary from `1.context.txt`;
  - the text of the line before and the line after, marked as read-only context;
  - the line's draft text.
- **Instructions to the model.**
  - Listen to the clip and fix only words the draft misheard.
  - Write what was said, in the language it was said. Never translate, summarise or reword. Keep fillers and repeats ("dạ", "à", "thì", stammered words).
  - Spell glossary terms exactly as listed, but only where they are actually heard.
  - Where unsure, keep the draft's word.
  - Answer as JSON `{"text": "..."}`, constrained by a schema.
  - Thinking off. Temperature 0, and 0.3 on retries. 3 attempts.
- **Guard.** The reviewed text replaces the draft only if:
  - it isn't empty;
  - for a draft of 4 or more syllables, at least half of the draft's syllables survive in order (`difflib` ratio ≥ 0.5 on lowercased syllables, punctuation dropped).

  Otherwise the draft is kept and the reason is logged. This catches a model that rewrites or summarises a line. A very short draft (e.g. "Yet." on a 1 s clip) is not guarded, since a full rewrite is often the right fix there.
- **Output, next to the audio.**
  - `1.reviewed.transcript.txt`: the usual line format, with the same timestamps and speaker labels as `1.transcript.txt`; only the text changes.
  - `1.review.jsonl`: one row per Segment with its times, speaker, draft, reviewed text and status (`same`, `changed`, `kept draft: <reason>` or `failed: <error>`), for checking by hand.
  - A summary in the job log: how many lines were changed, kept or failed.
- **Dependencies.** Exact pins are added to the root `requirements.txt` only (nothing is added to `requirements-audio.txt`):
  - vLLM 0.30.0's `audio` extra: `av`, `soundfile` and `soxr` (`scipy` is already pinned);
  - `imageio-ffmpeg==0.6.0`, to decode `1.m4a` (the compute machine has no system ffmpeg).
- **Model weights.** These go in the HF cache (`$HF_HOME/hub`), not in any requirements file. Qwen3-Omni-30B-A3B-Instruct is about 60–70 GB in bf16. That fits the job's one 96 GB GPU (RTX Pro 6000 Blackwell). To delete it afterwards: `rm -rf "$HF_HOME/hub/models--Qwen--Qwen3-Omni-30B-A3B-Instruct"`. The guide gives this command.
- **Where it lives.**
  - Job: `scripts/submit_transcript.sh`.
  - Code: `src/cli/review_transcript.py`, using `src/providers/vllm_client.py` like `proofread.py` does.
  - Prompt and schema: `src/prompts/transcript_review_prompts.py`.
  - Guide: a "Review pass" section in `docs/audio-transcribe.md`.
- **To check on the compute machine on the first run.**
  - That vLLM 0.30.0 serves Qwen3-Omni's audio input.
  - That the pinned `av`/`soundfile`/`soxr` versions install alongside it.
- **Out of scope here.** A reference transcript and scoring, SEA-LION, PhoWhisper, changes to `transcribe_audio.py`, and changes to speaker labels or timestamps.

## Next: PhoWhisper option (`--phowhisper`)

An optional flag, `--phowhisper`, makes `transcribe_audio.py` transcribe with `vinai/PhoWhisper-large` instead of Qwen3-ASR. It is reached through `scripts/transcribe_audio.sh`, which already passes every argument through to the Python script. This lets the developer compare a Vietnamese-tuned Whisper against Qwen3-ASR on the same recording.

- **Only the transcriber changes.** Decoding, diarization, VAD, cutting into Segments, timestamps, `Person N:` labels and the line format all stay the same. Only step 5 (transcribing each Segment) uses PhoWhisper. Empty Segments are still left out.
- **Language.** PhoWhisper is fine-tuned on Vietnamese only, so every Segment is transcribed with `language="vi"`, `task="transcribe"`. There is no auto-detect and no "redo as Vietnamese" step. English and French words come out however the model hears them.
- **No glossary.** `--phowhisper` together with `--context` is an error. The script stops before loading any model, with a message saying the glossary pass is Qwen-only. Porting the second pass to Whisper's `prompt_ids` could come later, if the plain output looks promising.
- **Segments over 30 s.** Whisper only hears 30 s, so anything after that would be dropped. In PhoWhisper mode, a Segment still longer than `MAX_SEGMENT_S` after `split_long` (no usable pause) is cut into equal parts of at most 30 s as a last resort (equal parts, so no tiny tail clip is left for Whisper to hallucinate on), and a warning is logged for each such Segment. The Qwen path is unchanged.
- **Hallucinations.** Whisper can invent text on near-silent or short clips, or loop on a phrase. Generation uses `no_repeat_ngram_size=10` (tokens, about 4 syllables, so normal speech isn't blocked), and a warning names each Segment whose text still compresses more than 2.4× with zlib (Whisper's own repetition threshold). Its text is kept, because the developer checks the output by hand.
- **Runtime.** It loads with plain `transformers` (`WhisperForConditionalGeneration` + `WhisperProcessor`, already in the audio venv through `qwen-asr`), so `requirements-audio.txt` gets no new entry. It runs in bf16 on `cuda:0`, in batches of `ASR_BATCH_SIZE`, with `max_new_tokens` held within Whisper's limit (~440). The weights go in the HF cache.
- **Output.** The output is `<stem>.phowhisper.transcript.txt`, so it sits beside the Qwen `<stem>.transcript.txt` and never overwrites it. `review_transcript.py` strips `.transcript.txt`, so a review of it would write `<stem>.phowhisper.reviewed.transcript.txt`.
- **SLURM job unchanged.** `scripts/submit_transcript.sh` stays Qwen3-ASR + Qwen3-Omni with no flags. `--phowhisper` is run by hand on a compute node.
- **Where it lives.**
  - Code: `src/cli/transcribe_audio.py` (flag, model loading, per-Segment transcription, the 30 s cut).
  - Usage line: `scripts/transcribe_audio.sh`.
  - Guide: a short `--phowhisper` paragraph in `docs/audio-transcribe.md`.
- **Not done.** No scoring or reference transcript, no glossary pass, no ADR (an optional flag is easy to reverse), and no glossary entry.

## Out of Scope

- Translation.
- Word-level timestamps, SRT and JSON output.
- SLURM batch submission.
- Speaker naming beyond Person 1 / Person 2.
- An LLM cleanup pass in `transcribe_audio.py` itself (it would quietly change what was said). An LLM review as a separate step after it is in "Next: Qwen3-Omni review pass".
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
- 2026-10-19: The glossary as one global context did not work well on the rerun:
  - Some terms were fixed (Janet Hoskins, Allan Kardec, Missions Étrangères, François Hugo).
  - Many still weren't ("đại đạo tông kỳ của độ", "việt tâm chân nhân"). Chơn Nhơn, Lý Thái Bạch, Quyền Giáo Tông and Nội Ứng Binh never appeared at all.
  - At 00:05:08 the model wrote the end of the glossary into the transcript, in file order ("…Troisième Amnistie de Dieu en Orient Missions Étrangères de Caodaï Allan Kardec Janet Hoskins cơ duyên").

  Decided: the two-pass, per-segment glossary with a leak guard (above). Options rejected:
  - A fuzzy find-and-replace on the output: it would change real words.
  - Changing to a model with decoder hotword biasing (faster-whisper/PhoWhisper, wav2vec2 + pyctcdecode): a new stack, and likely weaker on mixed Vietnamese, French and English.
  - Passing the previous segment's text as context: errors carry forward.
- 2026-10-19: The two-pass glossary rerun still had many misheard words (the developer's bracketed corrections in the first 3 lines: "bát cảnh"→"bác Cảnh", "Đức Phật pháp"→"Đức Hộ Pháp", "nari đâu"→"narrator của", "quá xin lỗi"→"question list", "cố"→"ký ức của").
  - A four-way comparison was first planned: Qwen3-ASR, + SEA-LION review, + Qwen3-Omni review, and PhoWhisper-large, scored on a hand-corrected 5 minutes.
  - Decided instead: build only Qwen3-ASR + Qwen3-Omni review, as one SLURM job with no flags (`scripts/submit_transcript.sh`). There is no reference and no scoring; the developer checks the output by hand.
  - SEA-LION was dropped because it can't hear the audio. PhoWhisper and the comparison were dropped as not needed for now.
  - This reverses the earlier "no LLM cleanup": the review is a separate step with its own output file, and the unreviewed transcript stays next to it.
  - The review runs in the root `requirements.txt` venv, so the ASR venv gets no heavy additions.

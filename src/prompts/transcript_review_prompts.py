"""
Prompt and output schema for the transcript review pass (src/cli/review_transcript.py).

The model hears one Segment's clip and reads Qwen3-ASR's draft of it. It fixes misheard words only: the draft's
wording, fillers and repeats are what was said, and stay.
"""

TOPIC = (
    "An interview recorded in Vietnam, mostly in Vietnamese. The interviewee is an elderly Cao Đài follower with a "
    "Southern accent; the interviewers are students. English and French words are mixed in."
)

SYSTEM_PROMPT = """\
You check an automatic transcript of a recorded interview. You get the audio clip of one segment and the speech
recognizer's draft of it. The recognizer often mishears words, names and religious terms. Listen to the clip and
write down what was said.

- Fix only words the draft misheard. Where the draft matches what you hear, keep its words exactly.
- Write what was said, in the language it was said. Never translate, summarise, reword or tidy the grammar.
- Keep fillers, repeats and false starts ("dạ", "à", "thì", "cái cái", "để mà con để mà").
- Spell a glossary term exactly as listed, but only where you actually hear it. Never add a term that is not spoken.
- The lines before and after are context only. Never copy their words into this segment.
- Where you are unsure, keep the draft's word.
- If the clip has no speech, answer with empty text.

Answer as JSON: {"text": "<the segment's corrected text>"}."""


def user_text(glossary, previous, draft, following):
    return "\n\n".join([
        f"Topic: {TOPIC}",
        "Glossary (exact spellings): " + ", ".join(glossary),
        f"Line before (context only): {previous or '(none)'}",
        f"Line after (context only): {following or '(none)'}",
        f"Draft of this segment: {draft}",
        "The audio clip of this segment follows.",
    ])


def review_schema():
    return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

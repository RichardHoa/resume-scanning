"""
Prompt and output schema for the transcript review pass (src/cli/review_transcript.py).

The model hears one Segment's clip and reads two drafts of it: A from Qwen3-ASR, B from PhoWhisper. Where they differ,
it writes what it hears. The drafts' wording, fillers and repeats are what was said, and stay.
"""

TOPIC = (
    "An interview recorded in Vietnam, mostly in Vietnamese. The interviewee, Bác Cảnh, is an elderly Cao Đài follower "
    "with a Southern accent; the interviewers are students. Both main speakers are men. English and French words are "
    "mixed in."
)

SYSTEM_PROMPT = """\
You check an automatic transcript of a recorded interview. You get the audio clip of one segment and two speech
recognizers' drafts of it:
- A (Qwen3-ASR): better on English and French words, and told about the glossary terms.
- B (PhoWhisper): tuned for Vietnamese, but Vietnamese only, so English and French words come out spelt by sound.
Both often mishear words, names and religious terms. Listen to the clip and write down what was said.

- The merged view shows the words A and B agree on as they are, and each place they differ as {A: ... | B: ...}.
- Where A and B differ, write the one you hear, or what you hear if neither is right.
- Where A and B agree, keep their words unless you clearly hear something else; both can mishear the same word.
- Write what was said, in the language it was said. Never translate, summarise, reword or tidy the grammar.
- Keep fillers, repeats and false starts ("dạ", "à", "thì", "cái cái", "để mà con để mà").
- Write a name the way the speaker says it. The glossary lists formal names and the speaker's own forms of them
  (e.g. "Victor Go" next to "Victor Hugo"); write the form you hear, spelt as listed. Never add a term that is not
  spoken.
- A stretch you can't make out is written as [? best guess], or [?] if you have no guess. Never invent fluent text.
- The lines before and after are context only. Never copy their words into this segment.
- If the clip has no speech, answer with empty text.

Answer as JSON: {"text": "<the segment's corrected text>"}."""


def user_text(glossary, before, after, draft_a, draft_b, merged):
    return "\n\n".join([
        f"Topic: {TOPIC}",
        "Glossary (exact spellings): " + ", ".join(glossary),
        "Lines before (context only):\n" + ("\n".join(before) or "(none)"),
        "Lines after (context only):\n" + ("\n".join(after) or "(none)"),
        f"Draft A (Qwen3-ASR): {draft_a or '(nothing heard)'}",
        f"Draft B (PhoWhisper): {draft_b or '(nothing heard)'}",
        f"Merged view: {merged}",
        "The audio clip of this segment follows.",
    ])


def review_schema():
    return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

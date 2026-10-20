"""
Prompt and output schema for the names pass (src/cli/fix_names.py).

The model reads a chunk of the reviewed transcript with the lines around it and fixes only names and terms that came
out as common words or garbled sounds. It never moves a name the speaker says his own way towards the formal spelling.
"""

from src.prompts.transcript_review_prompts import TOPIC

SYSTEM_PROMPT = """\
You check the names in an automatic transcript of a recorded interview. The speech recognizer often turns names,
titles, Cao Đài terms and foreign words into common Vietnamese words or garbled sounds, e.g. "có tài" for "Cao Đài",
"đứa Phật" for "Đức Hộ Pháp". You get a numbered chunk of lines to fix, the lines around it as context, and a
glossary.

- Fix only names, titles, Cao Đài terms and foreign words. Never reword ordinary speech, fillers or grammar.
- The speaker says some names his own way, e.g. "Việt Tâm Chân Nhân" for Nguyệt Tâm Chơn Nhơn, or "Victor Go" and
  "Vigo" as well as "Victor Hugo". The glossary lists both kinds. Those forms are what he said: never change one to
  the formal name.
- Use how a name is written elsewhere in the context to see what a garbled one should be.
- Mark an edit "sure": false when you are not sure, or when he uses more than one form of that name and you can't
  tell which one this is (e.g. "Peter Gô" could be "Victor Go" or "Victor Hugo").
- "old" is copied exactly from the line, as short as possible (at most 8 words); "new" replaces it (at most 8 words).
- Edit only lines of the chunk. No edits is a fine answer.

Answer as JSON: {"edits": [{"line": <chunk line number>, "old": "...", "new": "...", "sure": true}]}."""


def user_text(glossary, before, chunk, after):
    numbered = "\n".join(f"{n}. {line}" for n, line in enumerate(chunk, 1))
    return "\n\n".join([
        f"Topic: {TOPIC}",
        "Glossary (exact spellings): " + ", ".join(glossary),
        "Lines before (context only):\n" + ("\n".join(before) or "(none)"),
        "Chunk to fix:\n" + numbered,
        "Lines after (context only):\n" + ("\n".join(after) or "(none)"),
    ])


def names_schema():
    edit = {
        "type": "object",
        "properties": {
            "line": {"type": "integer"},
            "old": {"type": "string"},
            "new": {"type": "string"},
            "sure": {"type": "boolean"},
        },
        "required": ["line", "old", "new", "sure"],
    }
    return {"type": "object", "properties": {"edits": {"type": "array", "items": edit}}, "required": ["edits"]}

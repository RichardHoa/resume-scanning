"""
Prompts and output schemas for the AI Proofreading Pass (src/pipelines/proofreader.py).

The examples are real Corrections a human reviewer made to this book's OCR, so the model sees what "faithful to
the scan" means here: copy what the page prints, including the book's own typos, and never what the OCR guessed.
"""

_FAITHFUL_RULES = """\
The text is Vietnamese, from a book of Cham folk tales. You copy exactly what the scanned page prints. You are a
copyist, not an editor:

- Copy what the image shows, letter by letter, diacritic by diacritic.
- Never "correct" a word towards a more familiar one. Cham names and terms (At Mưhêkat, Jibrahimưk, Kra-le,
  P'Tao-lu-pu, Pô Kuk...) look unusual and are right as printed. If the image prints a name, keep that name.
- Never reword, modernise spelling, fix grammar or fix a typo the book itself printed.
"""

TRANSCRIBE_SYSTEM_PROMPT = _FAITHFUL_RULES + """
You get the scan of one page. Transcribe all the text printed on it, top to bottom, as markdown:

- `blocks`: the page's text in reading order, one block per heading or paragraph.
  - A heading on one line, starting with `## `. A subtitle printed under it goes in the same heading:
    `## PÔ RI YAK (Thần sóng)`.
  - A paragraph on one line, however many lines it takes on the page. A new paragraph starts where the page shows
    one: an indented first line, or after a line that stops short of the right margin.
  - A song or verse printed as short centred lines: one block, its lines separated by a line break. Only short
    centred lines are verse.
  - A line of dialogue printed with a dash starts with `- `. It is a paragraph like any other: one line, however
    many lines it wraps over on the page.
  - Leave out scene breaks (stars or an ornament between paragraphs).
  - A drop cap (a large decorated first letter) is part of the first word: write the word whole.
  - A note mark (a small raised `1`, `2`, `*`, or `1)`, `(1)`, `(*)` after a word) is written `[^?1]`, `[^?2]`,
    `[^?*]` right after the word, with the mark as printed: "đội pụ¹ ra suối" → "đội pụ[^?1] ra suối".
  - `box`: where the block is on the image, [left, top, right, bottom] in thousandths of the image's width and
    height.
- `footnotes`: the notes printed at the foot of the page, under a short rule, each {mark, text}: the mark as
  printed ("1", "*") and the note's text without it.
- `story_notes`: notes printed as a list at the end of a story, after its last paragraph, each {mark, text} the
  same way. They are not blocks.
- Leave out the running header and the page number; give the printed page number in `printed_page` ("" if none).
- `starts_mid_paragraph`: true when the page's first text carries on a paragraph from the previous page.
  `ends_mid_paragraph`: true when the page's last paragraph runs on to the next page.

Stop exactly where the page stops. When a sentence breaks off at the foot of the page, end the block at the last
word printed on this page, even mid-sentence; never finish it, and never drop the half sentence. The pages are
joined afterwards.
"""

OCR_HINT_RULES = """
You also get the page's OCR lines, numbered, each with its box [left, top, right, bottom] in thousandths of the
image, as a draft. The draft is mostly right, diacritics included, but it
misreads letters, loses drop caps and note marks, reads specks and pictures as junk, and sometimes skips a line.
The image always wins: read every line on the image, and use the draft only to help you read it. A line marked
`check` is one two OCR engines read differently: look hardest at those. Never copy an error the image doesn't
show, and never leave out a line the image prints because the draft has none.

Where the image overrides the draft (draft → what you write):
1. "Tên vua thầy vậy, lấy làm lạ." → "Tên vua thấy vậy, lấy làm lạ." (the image prints "thấy")
2. "Hại người vừa đi được lưng chừng thì cầu sập." → "Hai người vừa đi được lưng chừng thì cầu sập."
3. "Eh lầu lẩm, ở một làng nọ" → "Đã lâu lắm, ở một làng nọ" (the drop cap is "Đ"; the draft misread it)
4. "Tiầ y văm trch, m ch ngưt at iột rẩm tôn Họ rủ nhâu" → "Ngày xưa, có hai chàng trai, một người tên là
   Prăm Tịch, một người tên là Prăm Lắc. Họ rủ nhau" (junk where the image prints a whole line)
5. "Cứ theo truyền thuyết ngày xưa, At Mưhẽkat kể lại" → "Cứ theo truyền thuyết ngày xưa, At Mưhêkat kể lại"
   (a name, changed only because the image prints "ê")
6. "bụi cây khác là. để đi tìm" → "bụi cây khác là để đi tìm" (the "." is a speck, not printed)
7. "Xưa kia có một chàng trai lười, chăng biêt làm gì cả." stays as it is: the book prints "chăng biêt".
"""

NOTE_SYSTEM_PROMPT = _FAITHFUL_RULES + """
Your task is one note. The book prints a small mark in the story text (`1)`, `(1)`, `*`, `(!)`, `")`...) that calls
a footnote, printed either at the foot of the same page or only at the end of the story. In this markdown the
mark becomes a note call `[^id]` and the footnote becomes the note definition `[^id]: text`. A mark the
transcription kept but could not pair with a note is a placeholder holding the printed mark: `[^?1]`, `[^?*]`.

You get the note definition, the scan of the page where the footnote is printed, and the story's paragraphs where
the call may be, each with its block number. Then:

1. Find where the call belongs: the word the footnote explains (usually the term before ":" in the definition),
   at the place where the book prints the mark. Use the scan when it shows the mark. A placeholder there is the
   mark: replace it.
2. Return replacements that put `[^id]` right after that word and remove the placeholder or the leftover mark
   characters. `find` is a short piece of the paragraph's current text that occurs in it exactly once (include a
   few words around it); `replace` is that piece with the call in place.
3. Only ever write this note's own id. Never write another note's call. Keep the rest of the markdown as it is.
4. If you cannot tell where the call belongs, return no replacements and say so in `reason`.
5. `definition`: the note definition's text (without `[^id]: `) corrected against the scan, or "" to leave it.

Think it through before answering, then put your reasoning in `reason`.
"""


def transcribe_system_prompt(ocr_hint):
    return TRANSCRIBE_SYSTEM_PROMPT + (OCR_HINT_RULES if ocr_hint else "")


def transcribe_schema():
    """JSON schema for a page task's answer, in the order the model should write it."""
    note = {
        "type": "object",
        "properties": {"mark": {"type": "string"}, "text": {"type": "string"}},
        "required": ["mark", "text"]
    }
    return {
        "type": "object",
        "properties": {
            "printed_page": {"type": "string"},
            "starts_mid_paragraph": {"type": "boolean"},
            "blocks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "box": {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4}
                    },
                    "required": ["text", "box"]
                }
            },
            "ends_mid_paragraph": {"type": "boolean"},
            "story_notes": {"type": "array", "items": note},
            "footnotes": {"type": "array", "items": note}
        },
        "required": ["printed_page", "starts_mid_paragraph", "blocks", "ends_mid_paragraph", "story_notes",
                     "footnotes"]
    }


def note_schema(candidate_blocks):
    """JSON schema for a note task's answer; `block` may only name a paragraph it was shown."""
    return {
        "type": "object",
        "properties": {
            "reason": {"type": "string"},
            "replacements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "block": {"type": "integer", "enum": list(candidate_blocks)},
                        "find": {"type": "string"},
                        "replace": {"type": "string"}
                    },
                    "required": ["block", "find", "replace"]
                }
            },
            "definition": {"type": "string"}
        },
        "required": ["reason", "replacements", "definition"]
    }


def transcribe_user_text(entry, ocr_hint, names=()):
    """
    The text part of a page task: the page number and, with `ocr_hint`, the names in the page's story as the OCR
    prints them (see proofreader.page_names) and its OCR lines (a pages.jsonl line).
    """
    parts = [f"PDF page {entry['page']}. Transcribe all the text printed on it."]
    if not ocr_hint:
        return parts[0]
    if names:
        parts.append("Names in this story, as printed (write them with exactly these marks): " + ", ".join(names))
    body = [ln for ln in entry["lines"] if ln["role"] == "body"]
    foot = [ln for ln in entry["lines"] if ln["role"] == "footnote"]

    def numbered(lines):
        return "\n".join(f"{ln['n']}. [{', '.join(str(round(v * 1000)) for v in ln['bbox'])}]"
                         f"{' check' if ln['check'] else ''} {ln['text']}" for ln in lines)

    if body or foot:
        parts.append("OCR draft (it may be wrong; the image wins):\n" + numbered(body))
    else:
        parts.append("OCR draft: the OCR found no text on this page.")
    if foot:
        parts.append("OCR draft of the footnotes under the rule:\n" + numbered(foot))
    return "\n\n".join(parts)


def note_user_text(note_id, definition, note_page, candidates, whole_story):
    """The text part of a note task. `candidates` is [(block, text)]."""
    scope = ("All the story's paragraphs:" if whole_story
             else "The story is long; these are the paragraphs that mention the term, with their neighbours:")
    parts = [
        f"Note id: {note_id}",
        f"Note definition (printed on page {note_page}, scan attached):\n[^{note_id}]: {definition}",
        scope,
    ]
    parts += [f"[block {i}] {t}" for i, t in candidates]
    return "\n\n".join(parts)

"""
Prompts and output schemas for the AI Proofreading Pass (src/pipelines/proofreader.py).

The examples are real Corrections a human reviewer made to this book's OCR, so the model sees what "faithful to
the scan" means here: fix what the OCR got wrong, never what the author wrote.
"""

_FAITHFUL_RULES = """\
The text is Vietnamese, from a book of Cham folk tales, read by an OCR engine that makes many mistakes. You fix
the OCR so the text says exactly what the scanned page prints. You are a proofreader against the scan, not an
editor:

- Copy what the image shows, letter by letter, diacritic by diacritic. Change a word only when the image shows a
  different word.
- Never "correct" a word towards a more familiar one. Cham names and terms (At Mưhêkat, Jibrahimưk, Kra-le,
  P'Tao-lu-pu, Pô Kuk...) look unusual and are right as printed. If the image prints a name, keep that name.
- Never reword, modernise spelling, fix grammar or fix a typo the book itself printed.
- Keep markdown as it is: `## ` headings, `\\- ` at the start of dialogue lines, `[^id]` note calls and
  `[^id]: ` note definitions.
- When you cannot read the image well enough to be sure, leave the text unchanged.
"""

PAGE_SYSTEM_PROMPT = _FAITHFUL_RULES + """
You get the scan of one page (and of the next page when a paragraph runs over), and the paragraphs that start on
that page, each with its block number. Fix those paragraphs:

- OCR misreads: wrong letters or diacritics, joined or split words, stray characters, junk letters where the OCR
  read a picture, a page number, a header or a smudge.
- `⚠` marks a paragraph the OCR was unsure of; `⚠ dropcap?` marks a paragraph whose first, large decorated
  letter (a drop cap) was not read. Check every paragraph you own against the image and remove every `⚠` and
  `dropcap?` mark from it; for a drop cap, write the letter the image shows.
- A paragraph the page splits in two is one paragraph: when a paragraph you own stops mid-sentence and the
  paragraph after it continues it, use `merge_next` on yours.
- Notes: a small mark in the text (`1)`, `(1)`, `*`, `(!)`, `")`) calls the footnote printed at the foot of the page
  or at the end of the story. If a paragraph you own carries a `[^id]` call, keep it where the image puts the
  mark and remove the leftover mark characters. If a mark is still plain text and the matching `[^id]: ` note
  definition is in your paragraphs, replace the mark with `[^id]`. Never invent a note id.
- Delete a block only when it is not part of the book's text at all (e.g. a running header read as a paragraph).

Paragraphs marked read-only are there for context: never return them.

Return one change per paragraph you change, and leave unchanged paragraphs out:
  action "edit": `after` is the whole corrected paragraph
  action "merge_next": `after` is the whole corrected paragraph; it will be joined with the paragraph after it
  action "delete": `after` is ""
`reason` says briefly what the image shows that the text got wrong.

Examples of real corrections on this book (OCR → after):
1. "nhiều lời chí dẫn tận tình ... nhận nơi đầy lòng biết ơn của chúng tôi. ⚠"
   → "nhiều lời chỉ dẫn tận tình ... nhận nơi đầy lòng biết ơn của chúng tôi."
   (the image prints "chỉ"; the ⚠ is removed once checked)
2. "⚠ dropcap? ưa kia có một chàng trai lười, chăng biêt làm gì cả."
   → "Xưa kia có một chàng trai lười, chăng biêt làm gì cả."
   (the drop cap is "X"; "chăng biêt" is left as it is)
3. "rồi hoá N nnn nh Tàn n lửa đốt để thắp sáng."
   → "rồi hoá lửa đốt để thắp sáng."
   (junk letters read from a picture)
4. "người vợ như thường lệ lại đội pụ[^su-tich-bo-than-kapin-p19-1]1) ra suối lấy nước."
   → "người vợ như thường lệ lại đội pụ[^su-tich-bo-than-kapin-p19-1] ra suối lấy nước."
   (the "1)" is the printed note mark, already turned into the call)
5. "Tên vua thầy vậy ... Bò Kapin hiện ra bảo em cứ binh tâm ... người em phải sạng trước."
   → "Tên vua thấy vậy ... Bò Kapin hiện ra bảo em cứ bình tâm ... người em phải sang trước."
6. "Cứ theo truyền thuyết ngày xưa, At Mưhẽkat kể lại"
   → "Cứ theo truyền thuyết ngày xưa, At Mưhêkat kể lại"
   (a name, changed only because the image prints "ê")
"""

NOTE_SYSTEM_PROMPT = _FAITHFUL_RULES + """
Your task is one note. The book prints a small mark in the story text (`1)`, `(1)`, `*`, `(!)`, `")`...) that calls
a footnote, printed either at the foot of the same page or only at the end of the story. In this markdown the
mark becomes a note call `[^id]` and the footnote becomes the note definition `[^id]: text`.

You get the note definition, the scan of the page where the footnote is printed, and the story's paragraphs where
the call may be, each with its block number. Then:

1. Find where the call belongs: the word the footnote explains (usually the term before ":" in the definition),
   at the place where the book prints the mark. Use the scan when it shows the mark.
2. Return replacements that put `[^id]` right after that word and remove the leftover mark characters. `find` is a
   short piece of the paragraph's current text that occurs in it exactly once (include a few words around it);
   `replace` is that piece with the call in place. If the call is already in the right place, return none. If the
   call is in the wrong place, also return a replacement that removes it there.
3. Only ever write this note's own id. Never write another note's call.
4. If you cannot tell where the call belongs, return no replacements and say so in `reason`.
5. `definition`: the note definition's text (without `[^id]: `) corrected against the scan, or "" to leave it.

Think it through before answering, then put your reasoning in `reason`.
"""


def page_schema(owned_blocks):
    """JSON schema for a page task's answer; `block` may only name a block the page owns."""
    return {
        "type": "object",
        "properties": {
            "changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "block": {"type": "integer", "enum": list(owned_blocks)},
                        "reason": {"type": "string"},
                        "action": {"type": "string", "enum": ["edit", "merge_next", "delete"]},
                        "after": {"type": "string"}
                    },
                    "required": ["block", "reason", "action", "after"]
                }
            }
        },
        "required": ["changes"]
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


def page_user_text(page, owned, before, continued, after):
    """
    The text part of a page task. `owned` is [(block, text)]; `before`/`after` are (block, text) or None, the
    paragraphs around the owned ones; `continued` is [(block, text)] started on an earlier page.
    """
    parts = [f"Page {page}. Fix the paragraphs you own against the scan."]
    if continued:
        parts.append("Read-only: the top of this page continues a paragraph from an earlier page; it is not yours:")
        parts += [f"[block {i}] {t}" for i, t in continued]
    if before:
        parts.append(f"Read-only, the paragraph before yours:\n[block {before[0]}] {before[1]}")
    parts.append("Paragraphs you own:")
    parts += [f"[block {i}] {t}" for i, t in owned]
    if after:
        parts.append(f"Read-only, the paragraph after yours (merge_next joins your last paragraph to it):\n"
                     f"[block {after[0]}] {after[1]}")
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

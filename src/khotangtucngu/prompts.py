"""
The prompts and output schemas of a page's two kinds of request (vocabulary: vsc-project/khoTangTucNguoiNguoiViet/
GLOSSARY.md): the layout request sees the whole page with its Line Numbers and answers the printed book page number and
the Line Number each Proverb Entry and letter heading starts on; each Entry Span request sees one Entry Span cut from
the page, with the two Vision reads of its lines, and answers its Blocks in reading order. The Topic Index's requests
(topic_index.py) each see one Index Line: a number line's with no Vision read, a heading line's with its two reads.
"""
import json

from src.khotangtucngu.assembly import ALPHABET, BLOCK_KINDS
from src.khotangtucngu.citations import load_abbreviations
from src.khotangtucngu.diacritics import marked_reading, read_of_line, syllables
from src.khotangtucngu.settings import FRONT_MATTER
from src.providers.vlm_requests import sha1

_BOOK = """\
Source: scans of Kho tàng tục ngữ người Việt (2002), Vietnamese proverbs ordered by the letter of their first word.
"""

LAYOUT_SYSTEM_PROMPT = _BOOK + """\
Input: the scan of one whole page. A white strip added on its right labels each printed line with a red Line Number
("L1", "L2", ...), joined to the line's right end by a red tick. Line Numbers are not printed in the book.

Task: give the Line Number each Proverb Entry and letter heading starts on, so the page can be cut into one piece per
Proverb Entry. Read each Line Number from the red label on the line's row, following its tick. Never count lines.

Output:
- `printed_page`: the page number in the Running Head; "" if none is printed.
- `body_start`: the Line Number of the first line under the Running Head; 1 if the page has none.
- `starts`: the Line Number of each start, top to bottom. A letter heading and the first Proverb Entry under it each
  get their own start.

Starts:
- Letter heading: a large letter in a shaded box ("A").
- Proverb Entry: the line printing its number at the left margin ("482.") and the proverb in bold. A proverb printed
  over two lines starts on its first.

Never starts:
- Running Head: at the top above a rule, the page number with either a proverb's first words and "..." ("Cha bòn ...")
  or the title "KHO TÀNG TỤC NGỮ NGƯỜI VIỆT".
- Lines under a proverb, which belong to its Proverb Entry: Citations (Source Abbreviations with page numbers,
  "NASL II 59a"), Variants after "BK", notes in italics, a Correction after "Sửa lại:", a See-also after "Xem thêm".
- The same lines at the top of a page with no numbered proverb above them: they finish the page before's last Proverb
  Entry.
"""

SPAN_SYSTEM_PROMPT = _BOOK + """\
Input: one Entry Span, a piece cut across the whole width of one page's scan, and two OCR reads of each of its printed
lines.

Task: copy its printed text as Blocks, top to bottom.

An Entry Span usually holds one Proverb Entry: its number ("482.") and the proverb in bold, then, in this order and each
only if printed, Citations, Variants after "BK", notes in italics, a Correction after "Sửa lại:", a See-also after
"Xem thêm". It may instead hold a letter heading (a large letter in a shaded box), two Proverb Entries, or the end of a
Proverb Entry begun above it (those lines with no proverb above them; copy their Blocks as they come).

Blocks, by `kind`. `number` is 0 except on `proverb`; `citations` is "" except on `variant`.
- `letter`: `text` = the heading's letter, as printed.
- `proverb`: `number` = its printed number; `text` = the proverb without its number.
- `citations`: `text` = all Citation lines under the proverb, as printed:
  "HT 63 NL 7 PNTN 20b TNLG II 7, 25 TNPD I 13 VC I 9 VD 12".
- `variant`: one Block per Variant. "BK" precedes one Variant, or a list with each line starting "- ". `text` = the
  Variant's wording without "BK" or "- ", with words printed in italics between asterisks: "Ác *báo ngộ* ác báo.".
  `citations` = the Citations printed after it, as printed: "NNCC 27".
- `note`: one Block per paragraph of explanation. `text` = plain text, no asterisks though printed in italics. Keep its
  first words as printed ("VD:", "Theo VD,").
- `correction`: `text` = what follows "Sửa lại:", as printed: the wrong wording, the Source Abbreviation(s) that printed
  it, "=", the corrected wording with words printed in italics between asterisks:
  "Nằm giữa mất... CCM = Nằm giữa *không* mất...".
- `see_also`: `text` = the names after "Xem thêm", as printed: "M 526 T 65".

Copying:
- Copy what the scan prints, letter by letter, diacritic by diacritic, typos included. Never modernise, correct, reword
  or add a word.
- Join the lines of a Block printed over several lines with a space.
- Write a subscript as a Unicode subscript: VNP₁₁, VNP₂ I.
- Keep the spaces of a Source Abbreviation as printed: "TNPD I 13", "VC I 9", "NASL II 4b".

OCR reads, by Line Number: one of the line alone, one of the whole page. They are hints:
- [line read|page read] marks a word the reads are unsure of: "[mồ|mô]", "[VC I 10|VC110]"; one side is empty if only
  the other read has it. Spell what the scan prints, which may be neither. Never copy the brackets.
- An unmarked word was read the same both times and is usually right. Change it only where the scan clearly prints
  otherwise, never for what the word ought to be.
- "(one read)": the line has one read, so no word is marked.
- "(no read)": the line has no read; copy it from the scan.
- Take the Blocks, asterisks, Source Abbreviations and numbers from the scan, never from the reads.

Source Abbreviations, spelled letter for letter. A Citation names one of them. A Correction may print one without its
volume; copy it so:
""" + ", ".join(load_abbreviations(FRONT_MATTER)) + "\n"


_INDEX = """\
Input: one printed line cut from a page of the book's topic index (Hệ thống tra cứu theo chủ đề). The index files the
book's Proverb Entries under four chủ đề (I-IV) and their numbered tiểu chủ đề, naming each only by its letter and
number.
"""

INDEX_NUMBERS_SYSTEM_PROMPT = _BOOK + _INDEX + """\
Task: copy the entry numbers the line prints.

The line is either:
- a row's first line: a large letter at its left, then numbers separated by commas: "C 93, 262, 303, 389,";
- a row's later line: numbers only, separated by commas: "1191, 1201, 1385, 1386,".

Output:
- `letter`: the large letter at the line's left, as printed ("C", "Đ", "Â"); "" if the line begins with a number.
- `numbers`: every number the line prints, left to right, each once, as printed.

Copy only what this line prints, number by number. Never add a number it doesn't print, never continue or complete a
run of numbers, never drop one. Dots, dashes and specks between the numbers are scan noise: one comma separates every
two numbers.
"""

INDEX_HEADING_SYSTEM_PROMPT = _BOOK + _INDEX + """\
Task: copy the line's text as printed.

The line is usually one of the index's headings, or part of one:
- a chủ đề's roman numeral, alone and centred: "II";
- a chủ đề's title, in capitals, perhaps over two lines: "GIỚI TỰ NHIÊN. QUAN HỆ CỦA CON NGƯỜI";
- a tiểu chủ đề, its number then its title in bold: "17. Tiền bạc, của cải, vay mượn, nợ nần";
- the rest of a title wrapped onto this line: "tằm, săn bắn, thả cá, đánh bắt cá,...".

Output: `text`: the line as printed, a tiểu chủ đề's number and its full stop included.

Copying:
- Copy what the scan prints, letter by letter, diacritic by diacritic, capitals as capitals, typos included. Never
  modernise, correct, reword or add a word.

OCR reads of the line: one of the line alone, one of the whole page. They are hints:
- [line read|page read] marks a word the reads are unsure of: "[mồ|mô]"; one side is empty if only the other read has
  it. Spell what the scan prints, which may be neither. Never copy the brackets.
- An unmarked word was read the same both times and is usually right. Change it only where the scan clearly prints
  otherwise.
- "(one read)": the line has one read, so no word is marked.
"""


def index_numbers_user_text(page, n):
    """A number line's user text: no read of the line, so the model's read is independent of Vision's
    (docs/adr/0007-number-lines-read-without-a-hint.md beside the GLOSSARY)."""
    return f"Copy the entry numbers of this line, line {n} of PDF page {page}."


def index_heading_user_text(page, n, line_read, page_read):
    return f"The two reads of the line:\n{reading_line(n, line_read, page_read)}\n\nCopy the text of this line, line " \
           f"{n} of PDF page {page}."


def index_numbers_schema():
    return {
        "type": "object",
        "properties": {
            "letter": {"type": "string", "enum": [""] + ALPHABET},
            "numbers": {"type": "array", "items": {"type": "integer", "minimum": 0}},
        },
        "required": ["letter", "numbers"],
    }


def index_heading_schema():
    return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}


def index_numbers_prompt_sha1():
    return sha1(INDEX_NUMBERS_SYSTEM_PROMPT + json.dumps(index_numbers_schema(), sort_keys=True))


def index_heading_prompt_sha1():
    return sha1(INDEX_HEADING_SYSTEM_PROMPT + json.dumps(index_heading_schema(), sort_keys=True))


def layout_user_text(page):
    return f"Give the starts of PDF page {page}."


def reading_line(n, line_read, page_read):
    """Line Number `n` with its two reads, as the Entry Span's user text gives it."""
    if syllables(line_read) and syllables(page_read):
        return f"L{n}: {marked_reading(line_read, page_read)}"
    if syllables(line_read) or syllables(page_read):
        return f"L{n} (one read): {read_of_line(line_read, page_read)}"
    return f"L{n} (no read):"


def span_user_text(page, leading, readings):
    """The user text of an Entry Span of PDF page `page`, with `readings`, the two reads of its lines as
    [(Line Number, line read, page read)]; a `leading` one begins at no start the model named: the top of the page, or
    the lines below a Confirmed Span."""
    lines = "\n".join(reading_line(*reading) for reading in readings)
    ask = f"Copy the Blocks of this Entry Span of PDF page {page}."
    if leading:
        ask += (" It begins at no Proverb Entry's start, so it should only finish the Proverb Entry above it, on this "
                "page or the page before. If it prints a numbered proverb, copy it as a `proverb` Block.")
    return f"The two reads of its lines:\n{lines}\n\n{ask}"


def layout_schema():
    return {
        "type": "object",
        "properties": {
            "printed_page": {"type": "string"},
            "body_start": {"type": "integer", "minimum": 1},
            "starts": {"type": "array", "items": {"type": "integer", "minimum": 1}},
        },
        "required": ["printed_page", "body_start", "starts"],
    }


def span_schema():
    # No `pattern` on a string: with one, job 7357's Entry Span answers held raw '"' and newlines (past
    # "disable_any_whitespace") and ~3000 attempts ran to max_tokens. Our hypothesis, unchecked on the server's xgrammar
    # version: it puts the regex between the quotes as it is, so [^...] lets them into the string and it never closes
    printed = {"type": "string"}
    return {
        "type": "object",
        "properties": {
            "blocks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": BLOCK_KINDS},
                        "number": {"type": "integer", "minimum": 0},
                        "text": printed,
                        "citations": printed,
                    },
                    # `citations` comes after `text` and may be left out. p122-L19 ran to max_tokens of "}]}}" after
                    # "...CCM = Ăn mắm..." on all 3 attempts; our hypothesis, unchecked against its spiral: a required
                    # `citations` kept a model that closes its Block after `text` inside the string
                    "required": ["kind", "number", "text"],
                },
            },
        },
        "required": ["blocks"],
    }


def layout_prompt_sha1():
    """The hash a layout answer is stamped with: its system prompt and schema (the user text is stamped per page)."""
    return sha1(LAYOUT_SYSTEM_PROMPT + json.dumps(layout_schema(), sort_keys=True))


def span_prompt_sha1():
    """The hash an Entry Span answer is stamped with: its system prompt and schema (the user text is stamped per
    Entry Span)."""
    return sha1(SPAN_SYSTEM_PROMPT + json.dumps(span_schema(), sort_keys=True))

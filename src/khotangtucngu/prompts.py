"""
The prompts and output schemas of a page's two kinds of request (vocabulary: vsc-project/khoTangTucNguoiNguoiViet/
GLOSSARY.md): the layout request sees the whole page with its Line Numbers and answers the printed book page number and
the Line Number each Proverb Entry and letter heading starts on; each Entry Span request sees one Entry Span cut from
the page and answers its Blocks in reading order.
"""
import json

from src.khotangtucngu.assembly import BLOCK_KINDS
from src.providers.vlm_requests import sha1

_BOOK = """\
The pages are scans of Kho tàng tục ngữ người Việt (2002), a collection of Vietnamese proverbs ordered by the letter of
their first word.
"""

LAYOUT_SYSTEM_PROMPT = _BOOK + """\
You get the scan of one whole page, with a white strip added on its right. In the strip, each printed line of the page
has its Line Number in red ("L1", "L2", ...), with a red tick running from the right end of the line to it. The Line
Numbers are not printed in the book. Say on which Line Number each Proverb Entry starts, so the page can be cut into
pieces of one Proverb Entry each.

What a page prints:
- The Running Head, at the top above a rule: the page number, and either the first words of a proverb followed by
  "..." (e.g. "Cha bòn ...") or the book's title "KHO TÀNG TỤC NGỮ NGƯỜI VIỆT". Give the page number in
  `printed_page` ("" if none is printed). `body_start` is the Line Number of the first line under the Running Head
  (1 if the page has none).
- A letter heading: a large letter in a shaded box (e.g. "A"), opening that letter's proverbs.
- Proverb Entries. Each begins with the line printing its number ("482.") at the left margin and the proverb in bold.
  Under it come, each only if printed: the Citations (Source Abbreviations with page numbers, e.g. "NASL II 59a"),
  Variants after "BK", notes in italics, a Correction after "Sửa lại:" and a See-also after "Xem thêm". These belong
  to the Proverb Entry above them and never start one. A proverb printed over two lines starts on its first.
- A page may begin by finishing the last Proverb Entry of the page before: Citations, a Variant, a note, a Correction
  or a See-also with no numbered proverb above them on this page. They start nothing.

`starts` is the Line Number of the first line of each Proverb Entry (the line printing its number) and of each letter
heading, top to bottom. A letter heading and the first Proverb Entry under it each have their own start. Read each Line
Number from the red label on the same row as the line, following its tick; never count lines yourself.
"""

SPAN_SYSTEM_PROMPT = _BOOK + """\
You get one Entry Span: a piece cut across the whole width of the scan of one page. It usually holds one Proverb
Entry. It may instead hold a letter heading, or the lines that finish the last Proverb Entry of the page before, and
now and then two Proverb Entries. Copy its printed text as Blocks, in reading order, top to bottom.

What an Entry Span may print:
- A letter heading: a large letter in a shaded box (e.g. "A"), opening that letter's proverbs.
- Proverb Entries. Each begins with its number ("482.") and the proverb in bold. Under it, in this order, each only
  if printed: the Citations (Source Abbreviations with page numbers, e.g. "NASL II 59a", "TNLG II 7, 25"); Variants
  after "BK"; notes in italics; a Correction after "Sửa lại:"; a See-also after "Xem thêm".
- The end of the last Proverb Entry of the page before: Citations, a Variant, a note, a Correction or a See-also with
  no proverb above them. Copy those Blocks as they come.

The Blocks, by `kind`:
- `letter`: `text` is the letter of a letter heading, as printed.
- `proverb`: `number` is its printed number; `text` is the proverb, without its number.
- `citations`: `text` is all of the Citation lines printed under the proverb, as printed, e.g.
  "HT 63 NL 7 PNTN 20b TNLG II 7, 25 TNPD I 13 VC I 9 VD 12".
- `variant`: one Block per Variant. "BK" is followed by one Variant, or by a list of Variants, each line starting
  "- ". `text` is the Variant's wording only, without "BK" or "- ", with each word printed in italics between
  asterisks: "Ác *báo ngộ* ác báo.". `citations` is the Citations printed after it, as printed: "NNCC 27".
- `note`: one Block per paragraph of explanation, as plain text with no asterisks, though it is printed in italics.
  Keep its first words as printed, such as "VD:" or "Theo VD,".
- `correction`: the text after "Sửa lại:", as printed: the wrong wording, the Source Abbreviation(s) that printed it,
  "=", then the corrected wording with each word printed in italics between asterisks:
  "Nằm giữa mất... CCM = Nằm giữa *không* mất...".
- `see_also`: the names after "Xem thêm", as printed: "M 526 T 65".
`number` is 0 for every Block but a proverb, and `citations` is "" for every Block but a Variant.

You copy exactly what the scan prints. You are a copyist, not an editor:
- Copy letter by letter, diacritic by diacritic, the book's own typos included. Never modernise, correct or reword
  anything, and never add a word.
- A Block printed over several lines is one Block: join its lines with a space, so a sentence or a list reads whole.
- A subscript is written as a Unicode subscript, as printed: VNP₁₁, VNP₂ I.
- A Source Abbreviation is copied with its spaces as printed: "TNPD I 13", "VC I 9", "NASL II 4b".
"""


def layout_user_text(page):
    return f"Say on which Line Number each Proverb Entry and letter heading of PDF page {page} starts."


def span_user_text(page, leading):
    """The user text of an Entry Span of PDF page `page`; a `leading` one is the top of the page, before its first
    start."""
    if leading:
        return (f"Copy the Blocks of this Entry Span of PDF page {page}, in reading order. It is the top of the page, "
                f"finishing the last Proverb Entry of the page before, so it should hold no proverb of its own; if it "
                f"does print a numbered proverb, copy it as a `proverb` Block.")
    return f"Copy the Blocks of this Entry Span of PDF page {page}, in reading order."


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
                        "text": {"type": "string"},
                        "citations": {"type": "string"},
                    },
                    "required": ["kind", "number", "text", "citations"],
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

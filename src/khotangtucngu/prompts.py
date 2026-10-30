"""
The page request's prompt and output schema: one request per PDF page answers the printed book page number and the
page's Blocks in reading order (vocabulary: vsc-project/khoTangTucNguoiNguoiViet/GLOSSARY.md).
"""
import json

from src.providers.vlm_requests import sha1

LETTER, PROVERB, CITATIONS, VARIANT, NOTE, CORRECTION, SEE_ALSO = (
    "letter", "proverb", "citations", "variant", "note", "correction", "see_also")
BLOCK_KINDS = [LETTER, PROVERB, CITATIONS, VARIANT, NOTE, CORRECTION, SEE_ALSO]

SYSTEM_PROMPT = """\
The pages are scans of Kho tàng tục ngữ người Việt (2002), a collection of Vietnamese proverbs ordered by the letter of
their first word. You get the scan of one whole page. Copy its printed text as Blocks, in reading order, top to bottom.

What a page prints:
- The Running Head, at the top above a rule: the page number, and either the first words of a proverb followed by
  "..." (e.g. "Cha bòn ...") or the book's title "KHO TÀNG TỤC NGỮ NGƯỜI VIỆT". Give the page number in
  `printed_page` ("" if none is printed). Never copy any other word of the Running Head: it is not a Block.
- A letter heading: a large letter in a shaded box (e.g. "A"), opening that letter's proverbs.
- Proverb Entries. Each begins with its number ("482.") and the proverb in bold. Under it, in this order, each only
  if printed: the Citations (Source Abbreviations with page numbers, e.g. "NASL II 59a", "TNLG II 7, 25"); Variants
  after "BK"; notes in italics; a Correction after "Sửa lại:"; a See-also after "Xem thêm".

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

A page may begin by finishing the last Proverb Entry of the page before: Citations, a Variant, a note, a Correction
or a See-also with no proverb above it. Copy those Blocks first, as they come.

You copy exactly what the scan prints. You are a copyist, not an editor:
- Copy letter by letter, diacritic by diacritic, the book's own typos included. Never modernise, correct or reword
  anything, and never add a word.
- A Block printed over several lines is one Block: join its lines with a space, so a sentence or a list reads whole.
- A subscript is written as a Unicode subscript, as printed: VNP₁₁, VNP₂ I.
- A Source Abbreviation is copied with its spaces as printed: "TNPD I 13", "VC I 9", "NASL II 4b".
"""


def user_text(page):
    return f"Copy the Blocks of PDF page {page}, in reading order."


def page_schema():
    return {
        "type": "object",
        "properties": {
            "printed_page": {"type": "string"},
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
        "required": ["printed_page", "blocks"],
    }


def prompt_sha1():
    """The hash a page answer is stamped with: the system prompt and the schema (the user text is stamped per page)."""
    return sha1(SYSTEM_PROMPT + json.dumps(page_schema(), sort_keys=True))

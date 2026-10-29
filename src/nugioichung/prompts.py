"""
Prompts and output schemas for the two Nữ Giới Chung passes (docs/adr/0001-two-pass-vlm-no-ocr-draft.md), kept apart
from the book proofreader's.
"""
import json

from src.nugioichung.regions import KINDS

# A transcribed text with no run of more than three dots, spaces between them or not: each run of spaces and dots
# between two other characters holds at most three dots. Structured output enforces it, so the model can't copy a
# row of leader dots one by one until it runs out of tokens
NO_DOT_RUN = r"^ *(\. *){0,3}([^. ] *(\. *){0,3})*$"

_NEWSPAPER = """\
The pages are scans of Nữ Giới Chung (Femina Annamite), a Vietnamese weekly newspaper printed in Saigon in 1918. The
print is old, faint and speckled. Some pages carry handwriting added later by a library (shelf numbers, dates,
stamps): these Library Marks are not part of the newspaper.
"""

LAYOUT_SYSTEM_PROMPT = _NEWSPAPER + """
You get the scan of one whole page. Split the printed page into Regions and list them in reading order.

An Issue is made of Items, each of one kind:
- `article`: editorial text, with its title, and often a section printed above it (e.g. "Xã-thuyết",
  "Gia-chánh") and an author.
- `ad`: an advertisement for a product, shop or business, often in a box, sometimes in French.
- `notice`: the masthead, subscription prices, the editorial office's address and other notices of the paper.
- `contents`: the Table of Contents (Mục-lục).
- `footnotes`: the numbered notes printed at the foot of an Article, under it. They are a Region of that Article.

A Region is a rectangle of the page holding one part of one Item:
- One column of an Article is one Region; an Article set in three columns on this page is three Regions.
- A boxed Ad is one Region. A heading that spans several columns goes in the Region of the column it starts.
- The Footnotes printed under an Article are one Region of kind `footnotes`, with that Article's title. If they are
  set in two columns, they are two Regions.
- Every printed line of the page is in exactly one Region, and Regions never overlap.
- Never make a Region of the running header at the top of the page or of the printed page number, and never of a
  Library Mark. A printed picture belongs to the Region of its Item.

For each Region give:
- `kind`: one of the kinds above.
- `title`: its Item's title, copied exactly as printed, 1918 spelling included. For a Region that carries on an
  Item whose title is printed in an earlier Region of this page, repeat that title. "" if you can't see the title
  on this page (e.g. an Article carried on from the previous page) or the Item has none.
- `section` and `author`: as printed for the Item, "" if not printed on this page.
- `continues`: true when this Region carries on an Item begun in an earlier Region, on this page or a previous one
  (the second column of an Article; the top of the first column, when it carries on the previous page's Article).
  false when the Region begins its Item.
- `box`: [left, top, right, bottom] in thousandths of the image's width and height, around all of the Region's
  printed text, its heading included: every letter of its first and last line and of both ends of each line falls
  inside. Look at where the text actually starts and stops on the scan; never guess round figures.

The order of `regions` is the reading order: a column top to bottom, columns left to right, and an Article's
columns before the next Item that starts under them. Also give the printed page number in `printed_page` ("" if
none is printed).
"""


def layout_user_text(page):
    return f"Split PDF page {page} into its Regions, in reading order."


def layout_schema():
    return {
        "type": "object",
        "properties": {
            "regions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": list(KINDS)},
                        "title": {"type": "string"},
                        "section": {"type": "string"},
                        "author": {"type": "string"},
                        "continues": {"type": "boolean"},
                        "box": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 1000},
                                "minItems": 4, "maxItems": 4},
                    },
                    "required": ["kind", "title", "section", "author", "continues", "box"],
                },
            },
            "printed_page": {"type": "string"},
        },
        "required": ["regions", "printed_page"],
    }


TRANSCRIBE_SYSTEM_PROMPT = _NEWSPAPER + """
You get one Region of a page, cut from the scan: one part of one Item. A tall Region comes as Strips, horizontal
slices cut between printed lines, and you get one Strip of it. Transcribe all the text printed in it, top to bottom,
as Markdown in `text`.

You copy exactly what the scan prints. You are a copyist, not an editor:
- Copy letter by letter, diacritic by diacritic. Keep the 1918 spelling (Đờn-bà, sạch sẻ), the hyphens between
  syllables, the Hán characters and the newspaper's own typos exactly as printed. Never modernise, correct or
  reword anything.
- Leave out Library Marks: handwriting, shelf numbers and stamps added to the scan.
- Leave out the running header and the page number if part of one shows.
- Write a printed picture as `[Hình]` on its own line, with no description.

Layout of `text`:
- A title or section heading on its own line, starting with `### `. A heading set over several printed lines (an
  Ad's name: "TỦ SẮT" / "HIỆU" / "WERSTAEN") is one heading line, its printed lines joined with a space. Words in
  large type that a sentence runs through ("nên mua TỦ SẮT WERSTAEN mà dùng.") are not a heading: they stay in
  the sentence, as printed.
- A paragraph on one line, however many printed lines it takes, in an Ad as in an Article. Join the printed lines
  with a space, so a sentence or a word broken across lines reads whole; a line that ends in a hyphen joins the
  next line with no space, keeping the hyphen. A new paragraph starts where the scan shows one (an indented first
  line, or after a line that stops short, such as a slogan, a shop's name or its address in an Ad); separate
  paragraphs with a blank line.
- Keep the printed line breaks, one printed line per line, only in: a Hán saying with its phiên âm and its
  translation, and a poem.
- A table of prices or other figures set in rows and columns: a Markdown table.
- A Table of Contents: a nested Markdown list, its sections as items and their entries under them.
- A Footnote call in the text, a number in parentheses such as "(7)", is copied as printed.
- A run of dots, spaced or not (the leader dots between a label and its price or page number, or a long ellipsis),
  is written as three dots `...`, however long it is printed. Never copy dots one by one. In a Markdown table the
  leader dots are left out: the label and the figure go in their own columns.

A Footnotes Region holds the numbered notes printed under an Article. Answer it in `footnotes` instead of `text`:
one entry per Footnote, in printed order, with `number` the number printed in its parentheses (7 for "(7)") and
`text` the note after that number, copied by the same rules. If the Region begins partway through a Footnote whose
number is printed before it, give that first part as an entry with `number` 0.

`starts_mid_paragraph`: true when the Region's first line carries on a paragraph (or a Footnote) from before it (the
line is not indented and continues a sentence). `ends_mid_paragraph`: true when its last paragraph (or Footnote)
runs on past the Region's foot. Stop exactly where the Region stops, even mid-sentence or mid-word; never finish a
sentence.
"""


def transcribe_user_text(region, cut):
    what = KINDS[region.kind].label
    if region.title:
        what += f' of the Item "{region.title}"'
    where = f"Region {region.n} of PDF page {region.page}"
    if cut.strip:
        where = f"Strip {cut.strip} of {cut.of}, top to bottom, of {where}"
    return f"{where}: {what}. Transcribe it."


def transcribe_schema():
    return {
        "type": "object",
        "properties": {
            "text": {"type": "string", "pattern": NO_DOT_RUN},
            "starts_mid_paragraph": {"type": "boolean"},
            "ends_mid_paragraph": {"type": "boolean"},
        },
        "required": ["text", "starts_mid_paragraph", "ends_mid_paragraph"],
    }


def footnotes_schema():
    """The answer for a Footnotes Region: its Footnotes as {number, text}, 0 for a Footnote carried on from before."""
    return {
        "type": "object",
        "properties": {
            "footnotes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "number": {"type": "integer", "minimum": 0},
                        "text": {"type": "string", "pattern": NO_DOT_RUN},
                    },
                    "required": ["number", "text"],
                },
            },
            "starts_mid_paragraph": {"type": "boolean"},
            "ends_mid_paragraph": {"type": "boolean"},
        },
        "required": ["footnotes", "starts_mid_paragraph", "ends_mid_paragraph"],
    }


def prompt_sha1_input(system, schema):
    """What a pass's prompt hash is taken over: its system prompt and schema(s) (the user text is stamped per task)."""
    return system + json.dumps(schema, sort_keys=True)

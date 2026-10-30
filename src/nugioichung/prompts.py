"""
Prompts and output schemas for the two Nữ Giới Chung passes (docs/adr/0001-two-pass-vlm-no-ocr-draft.md), the
transcription pass as a read and a format request, kept apart from the book proofreader's.
"""
import json

from src.nugioichung.regions import KINDS

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


_CROP = """
You get one Region of a page, cut from the scan: one part of one Item. A tall Region comes as Strips, horizontal
slices cut between printed lines, and you get one Strip of it.
"""

READ_SYSTEM_PROMPT = _NEWSPAPER + _CROP + """
Copy its printed lines, top to bottom, one printed line per entry of `lines`.

You copy exactly what the scan prints. You are a copyist, not an editor:
- Copy letter by letter, diacritic by diacritic. Keep the 1918 spelling (Đờn-bà, sạch sẻ), the hyphens between
  syllables, the Hán characters and the newspaper's own typos exactly as printed. Never modernise, correct or
  reword anything.
- Copy each line as it is printed, the hyphen at its end included. Never join lines, and never add Markdown or any
  other formatting: another step lays the text out.
- Leave out Library Marks: handwriting, shelf numbers and stamps added to the scan.
- Leave out the running header and the page number if part of one shows.
- Write a printed picture as the entry `[Hình]`, with no description.
- A run of dots, spaced or not (the leader dots between a label and its price or page number, or a long ellipsis),
  is written as three dots `...`, however long it is printed. Never copy dots one by one.
- A Footnote's number, in parentheses such as "(7)", is copied at the start of its line as printed.

`starts_mid_paragraph`: true when the first line carries on a paragraph (or a Footnote) from before it (the line is
not indented and continues a sentence). `ends_mid_paragraph`: true when its last paragraph (or Footnote) runs on past
its foot. Stop exactly where the image stops, even mid-sentence or mid-word; never finish a sentence.
"""

FORMAT_SYSTEM_PROMPT = _NEWSPAPER + _CROP + """
You also get its printed lines, already copied from the scan one per line. Write the same text as Markdown in
`text`, looking at the scan to see how it is laid out.

Change no letter. Never add, drop, correct, reword or reorder a word, a letter, a diacritic or a hyphen: you only
decide where lines break and add Markdown marks.

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
- Keep the printed line breaks only in a Hán saying with its phiên âm and its translation, and in a poem: one
  printed line per line, each starting with `> `.
- `[Hình]`, a printed picture, on its own line.
- A table of prices or other figures set in rows and columns: a Markdown table, the leader dots left out, the label
  and the figure in their own columns.
- A Table of Contents: a nested Markdown list, its sections as items and their entries under them.
"""


def _where(region, cut):
    what = KINDS[region.kind].label
    if region.title:
        what += f' of the Item "{region.title}"'
    where = f"Region {region.n} of PDF page {region.page}"
    if cut.strip:
        where = f"Strip {cut.strip} of {cut.of}, top to bottom, of {where}"
    return f"{where}: {what}."


def read_user_text(region, cut):
    return f"{_where(region, cut)} Copy its printed lines."


def format_user_text(region, cut, read):
    """The format request's text: the read lines joined by code into paragraphs (`read["paragraphs"]`), or if the
    printed lines found on the scan didn't match them, the read lines as they are."""
    if read["paragraphs"] is None:
        return (f"{_where(region, cut)} Its printed lines:\n\n" + "\n".join(read["lines"])
                + "\n\nWrite them as Markdown.")
    return (f"{_where(region, cut)} Its printed lines, joined into paragraphs by code from where each line starts and "
            f"stops on the scan (a new paragraph at an indented line, after a line that stops short, and at a centred "
            f"line), one paragraph per line with a blank line between:\n\n" + "\n\n".join(read["paragraphs"])
            + "\n\nWrite them as Markdown. Where the scan shows the paragraphs break otherwise, break them as the "
              "scan shows.")


def read_schema():
    return {
        "type": "object",
        "properties": {
            "lines": {"type": "array", "items": {"type": "string"}},
            "starts_mid_paragraph": {"type": "boolean"},
            "ends_mid_paragraph": {"type": "boolean"},
        },
        "required": ["lines", "starts_mid_paragraph", "ends_mid_paragraph"],
    }


def format_schema():
    return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}


def prompt_sha1_input(system, schema):
    """What a pass's prompt hash is taken over: its system prompt and schema(s) (the user text is stamped per task)."""
    return system + json.dumps(schema, sort_keys=True)

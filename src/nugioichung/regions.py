"""
The Regions the layout pass finds on a page, the Strips a tall one is cut into, and the kinds of Item they belong to.
"""
from typing import List, NamedTuple, Tuple


class Kind(NamedTuple):
    label: str                      # as the Issue Markdown names it
    colour: Tuple[int, int, int]    # its outline on the page in the review viewer


# By the name the layout pass gives each kind
ARTICLE, FOOTNOTES = "article", "footnotes"
KINDS = {
    ARTICLE: Kind("Article", (0, 102, 204)),
    FOOTNOTES: Kind("Footnotes", (0, 153, 102)),
    "ad": Kind("Ad", (204, 102, 0)),
    "notice": Kind("Notice", (153, 51, 153)),
    "contents": Kind("Table of Contents", (204, 0, 51)),
}


def page_key(page):
    """A PDF page's name in the run folder: its layout request and its page image."""
    return f"p{page:02d}"


def region_label(page, n):
    return f"page {page} region {n}"


class Region(NamedTuple):
    page: int           # PDF page
    n: int              # its place in the page's reading order, from 1
    kind: str           # a key of KINDS
    title: str          # its Item's title as printed, "" if none
    section: str
    author: str
    continues: bool     # it carries on an Item begun in an earlier Region
    box: List[int]      # [left, top, right, bottom] in thousandths of the page, edges snapped onto gaps and rules
    layout_box: List[int]       # the box as the layout pass gave it
    strips: List[List[int]]     # the boxes of its Strips, top to bottom; [] if it is transcribed whole
    lines: List[list]           # the printed lines (pages.PrintedLine) found on the scan in each of its cuts

    @property
    def key(self):
        """Its name in the run folder: its transcription request."""
        return f"{page_key(self.page)}-r{self.n:02d}"

    @property
    def label(self):
        return region_label(self.page, self.n)

    @property
    def cuts(self):
        """What its transcription requests read, in order: the Region whole, or each of its Strips."""
        if not self.strips:
            return [Cut(self.key, self.label, self.page, self.box, 0, 0, self.lines[0])]
        return [Cut(f"{self.key}-s{k:02d}", f"{self.label} strip {k}", self.page, box, k, len(self.strips), lines)
                for k, (box, lines) in enumerate(zip(self.strips, self.lines), 1)]


class Cut(NamedTuple):
    """What one transcription request reads: a whole Region, or one Strip of it."""
    key: str            # its request's name in the run folder
    label: str
    page: int           # PDF page
    box: List[int]
    strip: int          # its place among its Region's Strips, from 1; 0 for a whole Region
    of: int             # how many Strips its Region has; 0 for a whole Region
    lines: list         # its printed lines (pages.PrintedLine) found on the scan, top to bottom


class PageLayout(NamedTuple):
    printed_page: str   # "" if none is printed
    regions: List[Region]
    outside: List[List[int]]    # the boxes of printed text that falls inside no Region


def warning(kind, place, reason, page, box=None):
    """
    A Warning: something in the transcribed Issue for the developer to look at, with its reason and the place on PDF
    page `page` it concerns, `box` in thousandths of the page (None: the whole page). Its id, from its kind and
    `place`, stays the same when the run's outputs are rebuilt, so a Resolution names it.
    """
    return {"id": f"{kind}:{place}", "kind": kind, "reason": reason, "page": page, "box": box}

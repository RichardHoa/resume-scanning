"""
The Regions the layout pass finds on a page, and the kinds of Item they belong to.
"""
from typing import List, NamedTuple, Tuple


class Kind(NamedTuple):
    label: str                      # as the Issue Markdown names it
    colour: Tuple[int, int, int]    # its outline on the drawn page


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
    """A PDF page's name in the run folder: its layout request and its drawn page."""
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
    box: List[int]      # [left, top, right, bottom] in thousandths of the page

    @property
    def key(self):
        """Its name in the run folder: its transcription request."""
        return f"{page_key(self.page)}-r{self.n:02d}"

    @property
    def label(self):
        return region_label(self.page, self.n)


class PageLayout(NamedTuple):
    printed_page: str   # "" if none is printed
    regions: List[Region]

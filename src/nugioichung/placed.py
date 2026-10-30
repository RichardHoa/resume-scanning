"""
Text that knows where each stretch of it was printed, so the review viewer can highlight, for any stretch of an
Issue's text, the printed line (or the whole Region or Strip) it was read from. A place is (cut key, line), `line`
the index of the printed line in the cut's read lines, or None for the whole cut.
"""


class PlacedText:
    """`text` with `spans`, (start, end, place) in order and not overlapping. Text in no span has no place: the
    separators between paragraphs and the ⚠ marks code adds."""
    __slots__ = ("text", "spans")

    def __init__(self, text="", spans=()):
        self.text = text
        self.spans = tuple(spans)

    @classmethod
    def at(cls, text, place):
        """`text`, all of it printed at `place` (None: no place)."""
        return cls(text, [(0, len(text), place)] if text and place is not None else [])

    def __add__(self, other):
        if isinstance(other, str):
            other = PlacedText(other)
        n = len(self.text)
        return PlacedText(self.text + other.text, self.spans + tuple((a + n, b + n, p) for a, b, p in other.spans))

    def __radd__(self, other):
        return PlacedText(other) + self

    def __bool__(self):
        return bool(self.text)

    def endswith(self, suffix):
        return self.text.endswith(suffix)

    def place_at(self, i):
        """The place of the character at `i`, or None."""
        return next((p for a, b, p in self.spans if a <= i < b), None)

    def places(self):
        """Its places, in order, each once."""
        return list(dict.fromkeys(p for _, _, p in self.spans))

    def slice(self, start, stop):
        return PlacedText(self.text[start:stop], [(max(a, start) - start, min(b, stop) - start, p)
                                                  for a, b, p in self.spans if a < stop and b > start])

    def strip(self):
        start = len(self.text) - len(self.text.lstrip())
        return self.slice(start, max(start, len(self.text.rstrip())))

    def split(self, pattern):
        """The pieces between the matches of `pattern`, a compiled regex."""
        pieces, start = [], 0
        for m in pattern.finditer(self.text):
            pieces.append(self.slice(start, m.start()))
            start = m.end()
        return pieces + [self.slice(start, len(self.text))]

    def sub(self, pattern, repl):
        """Each match of `pattern` replaced by `repl(match)`, a string, which takes the place of the text it replaces
        (a span that only partly covers a match ends or starts where the replacement does)."""
        out, moves, start = [], [], 0
        for m in pattern.finditer(self.text):
            out.append(self.text[start:m.start()])
            new_start = sum(map(len, out))
            out.append(repl(m))
            moves.append((m.start(), m.end(), new_start, new_start + len(out[-1])))
            start = m.end()
        out.append(self.text[start:])

        def move(x):
            shift = 0
            for old_start, old_end, new_start, new_end in moves:
                if x < old_start:
                    break
                if x < old_end:
                    return new_start
                shift = new_end - old_end
            return x + shift

        spans = [(move(a), move(b), p) for a, b, p in self.spans]
        return PlacedText("".join(out), [(a, b, p) for a, b, p in spans if a < b])

    def stretches(self):
        """The whole text as (stretch, place) in order, a stretch with no place given None, neighbours with the same
        place as one."""
        out, at = [], 0
        for a, b, p in self.spans:
            if a > at:
                out.append([self.text[at:a], None])
            if out and out[-1][1] == p and out[-1][1] is not None:
                out[-1][0] += self.text[a:b]
            else:
                out.append([self.text[a:b], p])
            at = b
        if at < len(self.text):
            out.append([self.text[at:], None])
        return [tuple(s) for s in out]

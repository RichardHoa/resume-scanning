"""
Score transcripts against a reference transcript of the same recording (e.g. the first 5 minutes, checked by hand).

For each hypothesis file it prints:
  - the syllable error rate: the text of every line starting before the reference's last end time, joined, against
    the joined reference text (lowercased, accents kept, punctuation dropped, [? markers dropped but their words kept),
    so runs whose lines are cut differently can be compared;
  - with --context, term recall: for each glossary term (formal or the speaker's own form) in the reference, how many
    of its occurrences the hypothesis has too;
  - the count of [? marks.

Standard library only, so it runs anywhere. Writes no files. Spec in .scratch/audio-transcribe/spec.md
("Next: two-model fusion, names pass and scoring (v2)", step 5).

Usage: python src/cli/score_transcript.py REFERENCE HYPOTHESIS... [--context GLOSSARY]
"""
import argparse
import re
import sys
import unicodedata

LINE = re.compile(r"^\[(\S+) → (\S+)\] (?:(Person \d+): )?(.*)$")


def seconds(stamp):
    """'HH:MM:SS.s' -> seconds."""
    hours, minutes, secs = stamp.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(secs)


def read_lines(path):
    """(start, end, text) for each transcript line; anything else in the file (e.g. a blank line) is skipped."""
    lines = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            m = LINE.match(raw.rstrip("\n"))
            if m:
                lines.append((seconds(m.group(1)), seconds(m.group(2)), m.group(4)))
    return lines


def syllables(text):
    """Lowercased syllables with accents kept, in one Unicode form; punctuation and [? markers drop out."""
    return re.findall(r"\w+", unicodedata.normalize("NFC", text).lower())


def edit_distance(ref, hyp):
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        current = [i]
        for j, h in enumerate(hyp, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (r != h)))
        previous = current
    return previous[-1]


def count_of(term, words):
    k = len(term)
    return sum(words[i:i + k] == term for i in range(len(words) - k + 1))


def read_glossary(path):
    """Terms separated by commas or newlines, as transcribe_audio.py reads them."""
    with open(path, encoding="utf-8") as f:
        return [t.strip() for t in re.split(r"[,\n]", f.read()) if t.strip()]


def main():
    parser = argparse.ArgumentParser(description="Score transcripts against a reference transcript")
    parser.add_argument("reference")
    parser.add_argument("hypotheses", nargs="+")
    parser.add_argument("--context", help="glossary file, for term recall")
    args = parser.parse_args()

    reference = read_lines(args.reference)
    if not reference:
        sys.exit(f"[Score] {args.reference} has no transcript lines")
    until = max(end for _, end, _ in reference)
    ref_words = syllables(" ".join(text for _, _, text in reference))
    terms = []
    if args.context:
        for term in read_glossary(args.context):
            words = syllables(term)
            if words and count_of(words, ref_words):
                terms.append((term, words))
    if not ref_words:
        sys.exit(f"[Score] {args.reference} has no words")
    print(f"Reference {args.reference}: {len(ref_words)} syllables up to {until:.1f} s")

    for path in args.hypotheses:
        lines = [text for start, _, text in read_lines(path) if start < until]
        hyp_text = " ".join(lines)
        hyp_words = syllables(hyp_text)
        errors = edit_distance(ref_words, hyp_words)
        print(f"\n{path}")
        print(f"  syllable error rate: {errors / len(ref_words):.1%} ({errors} errors in {len(ref_words)})")
        if terms:
            found = total = 0
            missed = []
            for term, words in terms:
                want = count_of(words, ref_words)
                got = min(want, count_of(words, hyp_words))
                found, total = found + got, total + want
                if got < want:
                    missed.append(f"{term} {got}/{want}")
            print(f"  term recall: {found}/{total}" + (f"; missed: {', '.join(missed)}" if missed else ""))
        print(f"  [? marks: {hyp_text.count('[?')}")


if __name__ == "__main__":
    main()

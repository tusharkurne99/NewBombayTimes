"""
build_crossword_quality_wordlist.py
Downloads a real, crossword-community-maintained SCORED word list (not
just a valid-English-words list) and filters it to single words usable
in our grids.

Why this exists: a generic English dictionary (word_bank.txt) tells you a
word is VALID, but not whether it's a GOOD crossword word -- one that
interlocks well with other words and that solvers actually enjoy seeing.
Testing showed this is the difference between Midi/Crossword-size grids
timing out completely vs. solving in under a minute at REALISTIC
(16-20%) black-square density, matching real NYT daily density -- see
project log for the density-vs-vocabulary-quality investigation.

Source: christophsjones/crossword-wordlist on GitHub (MIT-spirit, shared
freely for the crossword-construction community; built from NYT/WSJ/WaPo/
UKACD/Peter Broda's list/Peter Norvig's frequency data). ~170k entries,
each with a 1-50 quality score (50 = "wouldn't hesitate to use it").

Run: python build_crossword_quality_wordlist.py
Produces: crossword_quality_words.txt (WORD<tab>score, one per line)
"""

import re
import urllib.request

import paths

WORDLIST_URL = ("https://raw.githubusercontent.com/christophsjones/"
                 "crossword-wordlist/master/crossword_wordlist.txt")
MIN_LEN = 3
MAX_LEN = 15


def main():
    print("Downloading crossword-quality word list...")
    raw_path = paths.CROSSWORD_WORDLIST_RAW
    urllib.request.urlretrieve(WORDLIST_URL, raw_path)

    entries = {}
    with open(raw_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if ";" not in line:
                continue
            word, _, score_str = line.rpartition(";")
            word = word.strip()
            try:
                score = int(score_str.strip())
            except ValueError:
                continue

            # Single alphabetic words only -- the source list includes
            # multi-word phrases too (real crosswords use those), but our
            # grid representation only supports one unbroken word per slot.
            if " " in word:
                continue
            cleaned = re.sub(r"[^A-Za-z]", "", word).upper()
            if not cleaned.isalpha():
                continue
            if not (MIN_LEN <= len(cleaned) <= MAX_LEN):
                continue

            entries[cleaned] = max(entries.get(cleaned, 0), score)

    print(f"  -> {len(entries)} single-word entries")

    with open(paths.CROSSWORD_QUALITY_WORDS, "w") as f:
        for w, s in sorted(entries.items()):
            f.write(f"{w}\t{s}\n")

    print(f"Wrote {paths.CROSSWORD_QUALITY_WORDS}")
    print("\nScore key (from the source list's README):")
    print("  50 = common word/phrase, use without hesitation")
    print("  25 = acceptable")
    print("  2  = lowest quality still included")


if __name__ == "__main__":
    main()
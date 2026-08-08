"""
build_word_bank.py
One-time (or occasional) setup script: downloads a large public-domain
English word list, filters it down to words that are (a) crossword-usable
length (3-15 letters) and (b) actually common enough for a solver reader
to recognize -- using wordfreq's Zipf frequency score.

Without step (b), the grid solver happily fills your puzzle with valid but
obscure dictionary words (e.g. "NORIA", "XYLIC") nobody has heard of.

Run once: python build_word_bank.py
Produces: word_bank.txt (one word per line, uppercase)
"""

import urllib.request
from wordfreq import zipf_frequency
from word_filters import is_safe_context_free_word

WORDLIST_URL = "https://raw.githubusercontent.com/dwyl/english-words/master/words_alpha.txt"
MIN_LEN = 3
MAX_LEN = 15
# Zipf frequency scale is roughly 1 (very rare) to 7 (extremely common,
# e.g. "the"). 3.0 is a reasonable "an average adult would recognize this"
# cutoff -- tune down (more words, more obscure) or up (fewer, safer) later.
MIN_ZIPF = 3.0


def main():
    print("Downloading word list...")
    raw_path = "words_alpha.txt"
    urllib.request.urlretrieve(WORDLIST_URL, raw_path)

    with open(raw_path) as f:
        all_words = [w.strip().upper() for w in f if w.strip()]
    print(f"  -> {len(all_words)} raw words")

    print("Filtering by length + frequency (this takes a minute)...")
    kept = []
    dropped_hallucination_risk = 0
    for w in all_words:
        if not w.isalpha():
            continue
        if not (MIN_LEN <= len(w) <= MAX_LEN):
            continue
        zipf = zipf_frequency(w.lower(), "en")
        if zipf < MIN_ZIPF:
            continue
        # Second filter, independent of frequency: does this word have a
        # real dictionary meaning the clue-writing LLM can ground a clue
        # in, given it gets NO other context for plain filler words? Zipf
        # alone lets proper-noun-only words like "Paine" (only WordNet
        # sense: Thomas Paine) through, and the LLM then hallucinates a
        # clue for a meaning that doesn't exist. See word_filters.py for
        # the full reasoning.
        if not is_safe_context_free_word(w, zipf):
            dropped_hallucination_risk += 1
            continue
        kept.append(w)

    kept = sorted(set(kept))
    print(f"  -> {len(kept)} words kept (zipf >= {MIN_ZIPF}, "
          f"passed hallucination-risk check)")
    print(f"  -> {dropped_hallucination_risk} words dropped by the "
          f"hallucination-risk check despite passing the frequency filter")

    with open("word_bank.txt", "w") as f:
        f.write("\n".join(kept))

    print("Wrote word_bank.txt")
    print("\nNext: add Indian-context words (cities, cricket, Bollywood, "
          "politics terms) to word_bank.txt manually -- generic English "
          "frequency lists won't know these are common in your context.")


if __name__ == "__main__":
    main()
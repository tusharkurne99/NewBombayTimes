"""
merge_sources.py
Combines the word sources into pools for grid_generator.py, and builds a
word -> clue-context map for clue_generator.py.

Two output pools now, not one -- Mini vs. Midi/Crossword need different
vocabulary:
  merged_word_bank.txt        -- Mini (5x5): word_bank.txt + trivia/news
  midi_crossword_word_bank.txt -- Midi/Crossword: crossword_quality_words.txt
                                   (a real crossword-community SCORED word
                                   list, not just a valid-word list) +
                                   trivia/news. Testing showed this is the
                                   difference between Midi/Crossword grids
                                   solving in under a minute at realistic
                                   (16-20%) black-square density vs. not
                                   solving at all with a generic dictionary
                                   -- see build_crossword_quality_wordlist.py
                                   and the project log for why.

Also computes an "interlock_score" for every topical (news/trivia) word:
how well-attested it is in the curated crossword-quality list (0 if it
isn't in that list at all, meaning it's untested for how well it plays
with other crossword words -- still fine for Mini via word_bank.txt-style
filtering, but riskier to lean on for Midi/Crossword).

Priority when a word appears in multiple sources (news is freshest/most
specific, trivia is evergreen-but-still-specific, plain word bank has no
context at all):
    news candidates.json  >  india_trivia.json  >  plain word bank (no context)

Run: python merge_sources.py
Produces:
  merged_word_bank.txt          -- Mini word pool
  midi_crossword_word_bank.txt  -- Midi/Crossword word pool
  word_context.json             -- word -> {source, snippet, topic/score,
                                     interlock_score} for clues + grid tuning
  priority_words.txt            -- words WITH context (news+trivia)
"""

import json
import os

from wordfreq import zipf_frequency
from word_filters import is_safe_context_free_word, is_sensitive_word
import paths

# See project_log_week1_part3.md section 3 / the review_recommended
# mechanism in clue_generator.py: the user has editorial control over
# CLUES (can pick between alternates or write one by hand) but not over
# WORDS -- rejecting a word means re-running grid generation, which isn't
# realistic for a daily catch. That makes word-level filtering the one
# actual safety net for what appears in the grid at all, so it has to be
# applied everywhere a word can enter the pool, not just the generic word
# banks. This was a real gap: is_sensitive_word() was applied to
# word_bank.txt and crossword_quality_words.txt, but NOT to news/trivia
# words, which bypass both of those and go straight into the topical/
# priority pool on the strength of having real context alone --
# topicality was never a signal for appropriateness.


def load_word_bank(path):
    if not os.path.exists(path):
        print(f"  (skipping {path} -- not found)")
        return set()
    with open(path) as f:
        return {w.strip().upper() for w in f if w.strip()}


def load_quality_word_bank(path, min_score=40, wordnet_filter_max_len=10):
    """
    Returns (word_set, score_dict) from crossword_quality_words.txt
    (WORD<tab>score per line). score_dict has EVERY word's score
    (unfiltered), used separately to compute interlock_score for topical
    words regardless of whether they clear the filler threshold.

    word_set (the actual Midi/Crossword filler pool) applies:
    1. score >= min_score (40) -- the source list's own quality score.
    2. is_safe_context_free_word() -- the SAME WordNet-based "does this
       word have real, checkable dictionary meaning" filter already built
       and proven for word_bank.txt (the PAINE/KYRIE hallucination fix),
       but ONLY for words up to wordnet_filter_max_len letters.

    Why the length cutoff on filter #2, found by testing, not assumed:
    applying the WordNet filter to ALL lengths does fix crosswordese/junk
    (e.g. "DRJ", "GARYS" -- scored decently in the source list but have
    no real meaning) -- verified. But it also disproportionately guts the
    LONG end of the word list: legitimate long crossword answers are
    often proper nouns or compound/technical terms with weak WordNet
    coverage, so the filter was removing genuine words, not just junk, at
    those lengths. Concretely: unrestricted WordNet filtering left only
    ~45 words of length 15 (down from ~2000+ before filtering), and
    Crossword (15x15, which needs several mutually-compatible 15-letter
    answers) did not solve within 3 minutes with that pool -- a real
    regression, not a hypothetical one. Restricting the WordNet filter to
    words <=10 letters (where the actual junk was concentrated in real
    puzzle output) restored long-word volume (~2072 words of length 15)
    and Crossword solved in ~1 second with clean output on retest.
    """
    if not os.path.exists(path):
        print(f"  (skipping {path} -- not found; run "
              f"build_crossword_quality_wordlist.py for Midi/Crossword support)")
        return set(), {}

    word_set = set()
    score_dict = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or "\t" not in line:
                continue
            word, score_str = line.split("\t")
            score = int(score_str)
            score_dict[word] = score
            if score < min_score or is_sensitive_word(word):
                continue
            if len(word) <= wordnet_filter_max_len:
                if is_safe_context_free_word(word, zipf_frequency(word.lower(), "en")):
                    word_set.add(word)
            else:
                word_set.add(word)  # long words: trust the score, skip WordNet check
    return word_set, score_dict


def load_news_candidates(path):
    """Returns dict: word -> context dict.

    Carries through provenance metadata (outlet, article link, how many
    articles/sources mentioned it, when the scrape ran) beyond just the
    snippet text -- this is what lets a human reviewer actually judge a
    topical clue instead of just reading a bare sentence with no way to
    check where it came from or how fresh/well-attested it is. See
    clue_generator.py's context_meta field.
    """
    if not os.path.exists(path):
        print(f"  (skipping {path} -- not found)")
        return {}
    with open(path) as f:
        data = json.load(f)

    scraped_at = data.get("generated_at", "")
    out = {}
    dropped = 0
    for c in data.get("candidates", []):
        word = c["word"].upper()
        if is_sensitive_word(word):
            dropped += 1
            continue
        top_snippet = c["snippets"][0] if c.get("snippets") else {}
        out[word] = {
            "source": "news",
            "snippet": top_snippet.get("text", ""),
            "score": c.get("score", 0),
            "news_outlet": top_snippet.get("source", ""),
            "article_link": top_snippet.get("link", ""),
            "mentions": c.get("mentions", 0),
            "num_sources": c.get("num_sources", 0),
            "scraped_at": scraped_at,
        }
    if dropped:
        print(f"  (dropped {dropped} sensitive word(s) from news candidates)")
    return out


def load_trivia(path):
    """Returns dict: word -> context dict.

    Carries the source Wikipedia title/URL and pageview count through, for
    the same reason as load_news_candidates() above -- provenance a human
    reviewer can actually check, not just a bare snippet.
    """
    if not os.path.exists(path):
        print(f"  (skipping {path} -- not found)")
        return {}
    with open(path) as f:
        data = json.load(f)

    out = {}
    dropped = 0
    for e in data:
        word = e["word"].upper()
        if is_sensitive_word(word):
            dropped += 1
            continue
        source_title = e.get("source_title", "")
        wikipedia_url = (
            "https://en.wikipedia.org/wiki/" + source_title.replace(" ", "_")
            if source_title else ""
        )
        out[word] = {
            "source": "trivia",
            "snippet": e.get("snippet", ""),
            "topic": e.get("topic", ""),
            "score": e.get("pageviews_3mo", 0),
            "wikipedia_title": source_title,
            "wikipedia_url": wikipedia_url,
            "pageviews_3mo": e.get("pageviews_3mo", 0),
        }
    if dropped:
        print(f"  (dropped {dropped} sensitive word(s) from trivia)")
    return out


def main():
    print("Loading sources...")
    general = load_word_bank(paths.WORD_BANK)
    india_generic = load_word_bank(paths.INDIA_WORD_BANK)
    quality_words, quality_scores = load_quality_word_bank(paths.CROSSWORD_QUALITY_WORDS)
    news_ctx = load_news_candidates(paths.CANDIDATES)
    trivia_ctx = load_trivia(paths.INDIA_TRIVIA)

    print(f"  general word bank: {len(general)} words")
    print(f"  india word bank (no context): {len(india_generic)} words")
    print(f"  crossword-quality word bank (filtered): {len(quality_words)} words")
    print(f"  news candidates (with context): {len(news_ctx)} words")
    print(f"  trivia words (with context): {len(trivia_ctx)} words")

    # Build the context map with the priority order: news > trivia.
    # (Words present only in the plain word banks get no context entry --
    # that's fine, they're filler and will get a generic/dictionary clue.)
    word_context = {}
    for word, ctx in trivia_ctx.items():
        word_context[word] = ctx
    for word, ctx in news_ctx.items():
        word_context[word] = ctx  # news overwrites trivia if both present

    # Interlock score: how well-attested is this topical word in the
    # curated crossword-quality list? 0 = not in that list at all (still
    # usable, just untested for how well it interlocks -- fine for Mini,
    # a real risk factor for Midi/Crossword where the grid is much less
    # forgiving of an isolated/incompatible word).
    for word, ctx in word_context.items():
        ctx["interlock_score"] = quality_scores.get(word, 0)

    # Mini pool: word_bank.txt-based, as before.
    mini_pool = general | india_generic | set(news_ctx) | set(trivia_ctx)

    # Midi/Crossword pool: crossword-quality words + all topical words
    # (even ones with interlock_score 0 -- they're still worth TRYING to
    # seed, since seed_priority_words() already handles a seed attempt
    # failing gracefully; the interlock_score is there for grid_generator
    # or a future constructor-review step to make an informed choice, not
    # to hard-block low-scoring topical words).
    midi_crossword_pool = quality_words | set(news_ctx) | set(trivia_ctx)

    print(f"\nMini pool: {len(mini_pool)} unique words")
    print(f"Midi/Crossword pool: {len(midi_crossword_pool)} unique words")
    print(f"Words with clue context (priority words): {len(word_context)}")

    with open(paths.MERGED_WORD_BANK, "w") as f:
        f.write("\n".join(sorted(mini_pool)))
    print(f"Wrote {paths.MERGED_WORD_BANK}")

    with open(paths.MIDI_CROSSWORD_WORD_BANK, "w") as f:
        f.write("\n".join(sorted(midi_crossword_pool)))
    print(f"Wrote {paths.MIDI_CROSSWORD_WORD_BANK}")

    with open(paths.WORD_CONTEXT, "w") as f:
        json.dump(word_context, f, indent=2)
    print(f"Wrote {paths.WORD_CONTEXT} (now includes interlock_score per word)")

    with open(paths.PRIORITY_WORDS, "w") as f:
        f.write("\n".join(sorted(word_context.keys())))
    print(f"Wrote {paths.PRIORITY_WORDS}")


if __name__ == "__main__":
    main()
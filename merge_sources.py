"""
merge_sources.py
Combines the three word sources into one pool for grid_generator.py, and
builds a word -> clue-context map for the (upcoming) clue_generator.py.

Priority when a word appears in multiple sources (news is freshest/most
specific, trivia is evergreen-but-still-specific, plain word bank has no
context at all):
    news candidates.json  >  india_trivia.json  >  plain word bank (no context)

Run: python merge_sources.py
Produces:
  merged_word_bank.txt  -- full word pool for grid_generator.py
  word_context.json     -- word -> {source, snippet, topic/score} for clues
  priority_words.txt    -- words WITH context (news+trivia); grid_generator
                           tries these first so real puzzles actually
                           contain today's news / India trivia, rather than
                           picking them only by chance against ~6000 filler
                           words
"""

import json
import os


def load_word_bank(path):
    if not os.path.exists(path):
        print(f"  (skipping {path} -- not found)")
        return set()
    with open(path) as f:
        return {w.strip().upper() for w in f if w.strip()}


def load_news_candidates(path):
    """Returns dict: word -> context dict."""
    if not os.path.exists(path):
        print(f"  (skipping {path} -- not found)")
        return {}
    with open(path) as f:
        data = json.load(f)

    out = {}
    for c in data.get("candidates", []):
        word = c["word"].upper()
        snippet = c["snippets"][0]["text"] if c.get("snippets") else ""
        out[word] = {
            "source": "news",
            "snippet": snippet,
            "score": c.get("score", 0),
        }
    return out


def load_trivia(path):
    """Returns dict: word -> context dict."""
    if not os.path.exists(path):
        print(f"  (skipping {path} -- not found)")
        return {}
    with open(path) as f:
        data = json.load(f)

    out = {}
    for e in data:
        word = e["word"].upper()
        out[word] = {
            "source": "trivia",
            "snippet": e.get("snippet", ""),
            "topic": e.get("topic", ""),
            "score": e.get("pageviews_3mo", 0),
        }
    return out


def main():
    print("Loading sources...")
    general = load_word_bank("word_bank.txt")
    india_generic = load_word_bank("india_word_bank.txt")
    news_ctx = load_news_candidates("candidates.json")
    trivia_ctx = load_trivia("india_trivia.json")

    print(f"  general word bank: {len(general)} words")
    print(f"  india word bank (no context): {len(india_generic)} words")
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

    # Full pool for the grid solver = everything, deduped.
    full_pool = general | india_generic | set(news_ctx) | set(trivia_ctx)

    print(f"\nMerged pool: {len(full_pool)} unique words")
    print(f"Words with clue context (priority words): {len(word_context)}")

    with open("merged_word_bank.txt", "w") as f:
        f.write("\n".join(sorted(full_pool)))
    print("Wrote merged_word_bank.txt")

    with open("word_context.json", "w") as f:
        json.dump(word_context, f, indent=2)
    print("Wrote word_context.json")

    with open("priority_words.txt", "w") as f:
        f.write("\n".join(sorted(word_context.keys())))
    print("Wrote priority_words.txt")


if __name__ == "__main__":
    main()
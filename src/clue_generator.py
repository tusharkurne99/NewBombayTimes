"""
clue_generator.py
Takes a filled grid (from grid_generator.py) plus word context (from
merge_sources.py) and generates a clue for every answer, using a local
Ollama model. Produces the final playable puzzle JSON.

Design notes:
- One word per Ollama call, not batched. Small local models are much less
  reliable than a hosted frontier model at strict multi-item JSON output --
  keeping it one-word-per-call makes each failure isolated and easy to
  retry/debug, at the cost of being slower. Fine for a once-a-day batch
  of ~10-14 words.
- Words WITH context (today's news / India trivia, from word_context.json)
  get a context-aware prompt, so the clue is actually topical -- this is
  the whole point of the project, not just "a crossword with Indian words
  in it."
- Words with NO context (generic filler from word_bank.txt) get a plain
  clue prompt -- there's no news/trivia fact to hang a topical clue on.
- Validation + retry: small local models sometimes leak the answer into
  the clue, or ignore length limits. Reject and retry on those; fall back
  to a trivial template after a few failed attempts so the pipeline never
  crashes on a bad generation.

Run: python clue_generator.py <mini|midi|crossword>
Reads: output/test_grids/test_grid_<size>.json (from grid_generator.py),
       data/context/word_context.json (from merge_sources.py, optional --
       works without it, just with fewer topical clues)
Produces: output/puzzles/puzzle_<date>_<size>.json -- the final, playable puzzle
"""

import json
import re
import sys
from datetime import date

import requests

import paths

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.2:3b"  # swap to "llama3.1:8b" for higher quality, slower
MAX_RETRIES = 3
MAX_CLUE_WORDS = 10
TEMPERATURE = 0.7


def build_prompt(word, context):
    if context and context.get("snippet"):
        return (
            f"You are writing a clue for a daily Indian-context crossword "
            f"puzzle, similar in style to the New York Times Mini.\n"
            f"Write ONE short, clever clue (max {MAX_CLUE_WORDS} words) for "
            f"the answer \"{word}\".\n"
            f"Use this real context for topicality: \"{context['snippet']}\"\n"
            f"Do not use the word \"{word}\" itself anywhere in the clue.\n"
            f"Respond with ONLY the clue text -- no quotation marks, no "
            f"explanation, nothing else."
        )
    return (
        f"Write ONE short, clever crossword clue (max {MAX_CLUE_WORDS} words) "
        f"for the answer \"{word}\".\n"
        f"Do not use the word \"{word}\" itself anywhere in the clue.\n"
        f"Respond with ONLY the clue text -- no quotation marks, no "
        f"explanation, nothing else."
    )


def call_ollama(prompt):
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": TEMPERATURE},
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()


def clean_clue(raw):
    # models sometimes wrap the answer in quotes or add a leading label
    # like "Clue:" despite instructions -- strip common junk defensively
    clue = raw.strip().strip('"').strip("'")
    clue = re.sub(r"^(clue|answer)\s*:\s*", "", clue, flags=re.IGNORECASE)
    return clue.strip()


def is_valid_clue(clue, word):
    if not clue:
        return False
    if word.lower() in clue.lower():
        return False  # answer leaked into the clue
    if len(clue.split()) > MAX_CLUE_WORDS + 4:  # generous margin over the ask
        return False
    return True


def fallback_clue(word, context):
    if context and context.get("topic"):
        return f"Term related to Indian {context['topic']} ({len(word)} letters)"
    return f"A {len(word)}-letter word"


def generate_clue(word, context):
    prompt = build_prompt(word, context)
    for attempt in range(MAX_RETRIES):
        try:
            raw = call_ollama(prompt)
        except requests.RequestException as e:
            print(f"  [{word}] Ollama request failed ({e}), retrying...")
            continue

        clue = clean_clue(raw)
        if is_valid_clue(clue, word):
            return clue
        print(f"  [{word}] rejected candidate clue: '{clue}' (attempt {attempt + 1})")

    print(f"  [{word}] all attempts failed, using fallback template")
    return fallback_clue(word, context)


def main():
    size_arg = sys.argv[1] if len(sys.argv) > 1 else "mini"
    if size_arg not in ("mini", "midi", "crossword"):
        print(f"Unknown size '{size_arg}' -- use mini, midi, or crossword")
        sys.exit(1)

    grid_path = paths.test_grid_path(size_arg)
    try:
        with open(grid_path) as f:
            grid = json.load(f)
    except FileNotFoundError:
        print(f"{grid_path} not found -- run 'python grid_generator.py "
              f"{size_arg}' first.")
        sys.exit(1)

    word_context = {}
    try:
        with open(paths.WORD_CONTEXT) as f:
            word_context = json.load(f)
        print(f"Loaded context for {len(word_context)} words")
    except FileNotFoundError:
        print("word_context.json not found -- proceeding with generic clues "
              "only (run merge_sources.py first for topical clues).")

    # quick check Ollama is reachable before doing any real work
    try:
        requests.get("http://localhost:11434/api/tags", timeout=5)
    except requests.RequestException:
        print("Cannot reach Ollama at localhost:11434 -- is 'ollama serve' "
              "running?")
        sys.exit(1)

    clues = {"across": {}, "down": {}}
    total = sum(len(v) for v in grid["words"].values())
    done = 0

    for direction in ("across", "down"):
        for number, entry in grid["words"][direction].items():
            word = entry["answer"]
            context = word_context.get(word)
            done += 1
            print(f"[{done}/{total}] Generating clue for {word} "
                  f"({'topical' if context else 'generic'})...")
            clue_text = generate_clue(word, context)
            clues[direction][number] = {
                "answer": word,
                "clue": clue_text,
                "length": entry["length"],
                "topical": context is not None,
                # Source snippet the clue was (supposedly) grounded in --
                # kept in the output rather than discarded after use, so a
                # human reviewer can actually check the clue against it.
                # This exists because of a real, serious finding: a clue
                # once fabricated a criminal accusation about a real,
                # named, unrelated person (see project log part 3) even
                # though real context was theoretically available -- a
                # small local model can produce fluent, confident, WRONG
                # text regardless of what it's given. No filter catches
                # this reliably; a human skim is the actual safeguard.
                "source_snippet": context.get("snippet", "") if context else "",
                "source": context.get("source") if context else None,
                # Every topical clue is flagged for review, not just ones
                # that look person/institution-related -- we don't yet
                # reliably know which topical words name a real person
                # (that would need entity-type metadata plumbed through
                # from scraper.py/india_trivia_scraper.py, not yet done).
                # Flagging all topical clues is the safe default until
                # that's more precise: a false positive here just means
                # skimming one extra clue, a false negative could mean
                # publishing another Pyarelal-style fabrication.
                "review_recommended": context is not None,
            }

    puzzle = {
        "id": f"{date.today().isoformat()}-{size_arg}",
        "date": date.today().isoformat(),
        "puzzle_type": size_arg,
        "size": grid["size"],
        "grid": grid["grid"],
        "numbering": grid["numbering"],
        "clues": clues,
    }

    out_path = paths.puzzle_path(date.today().isoformat(), size_arg)
    with open(out_path, "w") as f:
        json.dump(puzzle, f, indent=2)

    topical_count = sum(1 for d in clues.values() for e in d.values() if e["topical"])
    review_count = sum(1 for d in clues.values() for e in d.values()
                        if e["review_recommended"])
    print(f"\nWrote {out_path}")
    print(f"Topical clues: {topical_count}/{total}")
    print(f"\n*** {review_count} clue(s) flagged review_recommended=true. ***")
    print("*** Read every one against its source_snippet before calling ***")
    print("*** this puzzle final -- especially any about a real person  ***")
    print("*** or institution. See project_log_week1_part3.md section 3.***")


if __name__ == "__main__":
    main()
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

Run: python clue_generator.py
Reads: test_grid.json (from grid_generator.py), word_context.json
       (from merge_sources.py, optional -- works without it, just with
       fewer topical clues)
Produces: puzzle_<date>.json -- the final, playable puzzle
"""

import json
import re
import sys
from datetime import date

import requests

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
    try:
        with open("test_grid.json") as f:
            grid = json.load(f)
    except FileNotFoundError:
        print("test_grid.json not found -- run grid_generator.py first.")
        sys.exit(1)

    word_context = {}
    try:
        with open("word_context.json") as f:
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
            }

    puzzle = {
        "id": f"{date.today().isoformat()}-mini",
        "date": date.today().isoformat(),
        "size": grid["size"],
        "grid": grid["grid"],
        "numbering": grid["numbering"],
        "clues": clues,
    }

    out_path = f"puzzle_{date.today().isoformat()}.json"
    with open(out_path, "w") as f:
        json.dump(puzzle, f, indent=2)

    topical_count = sum(1 for d in clues.values() for e in d.values() if e["topical"])
    print(f"\nWrote {out_path}")
    print(f"Topical clues: {topical_count}/{total}")


if __name__ == "__main__":
    main()
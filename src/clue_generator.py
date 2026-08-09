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
  of ~10-90 words depending on size.
- Words WITH context (today's news / India trivia, from word_context.json)
  get a context-aware prompt, so the clue is actually topical -- this is
  the whole point of the project, not just "a crossword with Indian words
  in it." These are also the words flagged review_recommended=true (see
  below) -- get THREE independent clue candidates instead of one, so a
  human reviewer has real alternatives to choose from instead of a single
  take-it-or-leave-it clue.
- Words with NO context (generic filler from word_bank.txt) get a plain
  clue prompt and a single generated clue -- there's no news/trivia fact
  to hang a topical clue on, and word-level filtering (word_filters.py) is
  the actual safety net for these, not clue-time review. Burning 3x LLM
  calls on every filler word (dozens per puzzle) for no reviewing benefit
  would just slow the pipeline down.
- Validation + retry: small local models sometimes leak the answer into
  the clue, or ignore length limits. Reject and retry on those; fall back
  to a trivial template after a few failed attempts so the pipeline never
  crashes on a bad generation.
- Two models, not one: topical words (few per puzzle, and the ones a human
  will actually read closely) use the larger/higher-quality model;
  everything else uses the faster one. See TOPICAL_MODEL/GENERIC_MODEL.

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
GENERIC_MODEL = "llama3.2:3b"   # fast -- used for the bulk of filler words
TOPICAL_MODEL = "llama3.1:8b"   # higher quality -- used only for
                                 # review_recommended words, where quality
                                 # actually matters and volume is low
                                 # (typically well under 10 per puzzle)
MAX_RETRIES = 3
MAX_CLUE_WORDS = 10
TEMPERATURE = 0.7

# For review_recommended words, generate this many independently-generated
# candidate clues instead of one, so a human reviewer has real alternatives.
CLUE_OPTIONS_PER_TOPICAL_WORD = 3

# ---------------------------------------------------------------------------
# Shared crossword-clue craft rules, applied to every prompt regardless of
# whether the word has real context. Added because the earlier prompt --
# "write one short clever clue" with no further guidance -- produced clues
# that were often just a reworded dictionary definition or a lightly-edited
# copy of the source snippet, not something that reads like an actual
# constructed crossword clue. These rules encode conventions real crossword
# editors follow (part-of-speech/tense agreement, fragments over full
# sentences, no near-synonyms of the answer) that a small local model
# doesn't reliably know on its own without being told explicitly.
# ---------------------------------------------------------------------------
CLUE_STYLE_RULES = """Rules for writing the clue:
1. Match the clue's grammatical form to the answer's part of speech and
   tense. If the answer is a past-tense verb, the clue should read as a
   past-tense description, not a general definition. If the answer is a
   plural noun, the clue should imply plurality.
2. Write a fragment, not a full sentence -- this is standard for crossword
   clues (e.g. "Capital of France" rather than "This is the capital of
   France.").
3. Never use the answer word itself, a plural/possessive form of it, or an
   obvious derivative of it anywhere in the clue.
4. Do not just reword or lightly compress the source context into a
   sentence -- write something that reads like an actual composed
   crossword clue referencing the fact, not a paraphrase of it.
5. Avoid clues so generic they could fit many different answers (e.g. "A
   type of food") when a more specific angle is available from the context.
6. Keep the tone consistent with a daily newspaper crossword: concise,
   a little clever when it fits naturally, never forced, never offensive."""

# Per-option "angle" for the 3 topical clue candidates -- deliberately
# different framings, not just re-rolling the same prompt at a different
# temperature, so the 3 results are genuinely distinct choices rather than
# near-duplicates of each other.
CLUE_ANGLES = [
    ("direct", "Write a straightforward, factual clue based directly on "
               "the context given."),
    ("concise", "Write the SHORTEST possible clue that still clearly and "
                "unambiguously points to the answer -- headline-style, "
                "every word earning its place."),
    ("oblique", "If a natural wordplay, pun, or double meaning fits the "
                "answer, use it and end the clue with a question mark "
                "(standard crossword convention for wordplay clues). If "
                "nothing natural fits, instead write a more indirect or "
                "lesser-known-angle factual clue than the obvious one."),
]


def build_prompt(word, context, angle_instruction=None):
    angle_instruction = angle_instruction or (
        "Write a clear, well-constructed clue based on the context given."
    )
    if context and context.get("snippet"):
        return (
            f"You are an experienced crossword editor writing a clue for a "
            f"daily Indian-context crossword, in the style of the New York "
            f"Times Mini.\n\n"
            f"Answer: \"{word}\"\n"
            f"Real context to base the clue on: \"{context['snippet']}\"\n\n"
            f"{angle_instruction}\n"
            f"Maximum {MAX_CLUE_WORDS} words.\n\n"
            f"{CLUE_STYLE_RULES}\n\n"
            f"Respond with ONLY the clue text -- no quotation marks, no "
            f"labels like \"Clue:\", no explanation, nothing else."
        )
    return (
        f"You are an experienced crossword editor writing a clue for a "
        f"daily Indian-context crossword, in the style of the New York "
        f"Times Mini.\n\n"
        f"Answer: \"{word}\"\n"
        f"No special context is available for this word -- write a clean, "
        f"general-knowledge clue for it.\n"
        f"Maximum {MAX_CLUE_WORDS} words.\n\n"
        f"{CLUE_STYLE_RULES}\n\n"
        f"Respond with ONLY the clue text -- no quotation marks, no "
        f"labels like \"Clue:\", no explanation, nothing else."
    )


def call_ollama(prompt, model):
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": model,
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


def generate_clue(word, context, model=GENERIC_MODEL, angle_instruction=None):
    """Generate ONE validated clue, retrying on rejection, falling back to
    a trivial template if every attempt fails."""
    prompt = build_prompt(word, context, angle_instruction)
    for attempt in range(MAX_RETRIES):
        try:
            raw = call_ollama(prompt, model)
        except requests.RequestException as e:
            print(f"  [{word}] Ollama request failed ({e}), retrying...")
            continue

        clue = clean_clue(raw)
        if is_valid_clue(clue, word):
            return clue
        print(f"  [{word}] rejected candidate clue: '{clue}' (attempt {attempt + 1})")

    print(f"  [{word}] all attempts failed, using fallback template")
    return fallback_clue(word, context)


def generate_clue_options(word, context, n=CLUE_OPTIONS_PER_TOPICAL_WORD):
    """
    For review_recommended words: generate N independently-validated clue
    candidates, each from a different angle (see CLUE_ANGLES), using the
    higher-quality TOPICAL_MODEL. Returns a list of {"angle", "text"}
    dicts. If two angles happen to produce the same clue text (small
    models sometimes ignore the angle instruction), the duplicate is
    regenerated once with a plain prompt so the reviewer doesn't end up
    choosing between two identical options.
    """
    options = []
    seen_lower = set()
    for angle_name, angle_instruction in CLUE_ANGLES[:n]:
        clue = generate_clue(word, context, model=TOPICAL_MODEL,
                              angle_instruction=angle_instruction)
        if clue.lower() in seen_lower:
            # angle didn't produce anything distinct -- one plain retry
            # rather than showing the reviewer a duplicate.
            clue = generate_clue(word, context, model=TOPICAL_MODEL)
        seen_lower.add(clue.lower())
        options.append({"angle": angle_name, "text": clue})
    return options


def build_context_meta(context):
    """
    "Additional context about where the word/clue came from," surfaced for
    human review -- separate from source_snippet (which is what the LLM
    saw) so a reviewer can also check provenance/freshness/popularity
    signals the LLM never sees at all.
    """
    if not context:
        return None
    if context.get("source") == "news":
        return {
            "news_outlet": context.get("news_outlet", ""),
            "article_link": context.get("article_link", ""),
            "mentions": context.get("mentions", 0),
            "num_sources": context.get("num_sources", 0),
            "scraped_at": context.get("scraped_at", ""),
        }
    if context.get("source") == "trivia":
        return {
            "wikipedia_title": context.get("wikipedia_title", ""),
            "wikipedia_url": context.get("wikipedia_url", ""),
            "topic": context.get("topic", ""),
            "pageviews_3mo": context.get("pageviews_3mo", 0),
        }
    return None


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
            review_recommended = context is not None
            done += 1

            if review_recommended:
                print(f"[{done}/{total}] Generating {CLUE_OPTIONS_PER_TOPICAL_WORD} "
                      f"clue options for {word} (topical, review required)...")
                clue_options = generate_clue_options(word, context)
                clue_text = clue_options[0]["text"]
            else:
                print(f"[{done}/{total}] Generating clue for {word} (generic)...")
                clue_options = None
                clue_text = generate_clue(word, context, model=GENERIC_MODEL)

            clues[direction][number] = {
                "answer": word,
                "clue": clue_text,
                "length": entry["length"],
                "topical": review_recommended,
                # Multiple candidate clues -- ONLY populated for
                # review_recommended words. None for generic filler, since
                # there's nothing to choose between and no snippet to
                # ground alternate angles in anyway.
                "clue_options": clue_options,
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
                # Structured provenance (outlet/link/mentions for news;
                # Wikipedia title/URL/pageviews for trivia) -- lets a
                # reviewer judge freshness/prominence, not just read a
                # bare sentence with no way to check where it came from.
                "context_meta": build_context_meta(context),
                # Every topical clue is flagged for review, not just ones
                # that look person/institution-related -- we don't yet
                # reliably know which topical words name a real person
                # (that would need entity-type metadata plumbed through
                # from scraper.py/india_trivia_scraper.py, not yet done).
                # Flagging all topical clues is the safe default until
                # that's more precise: a false positive here just means
                # skimming one extra clue, a false negative could mean
                # publishing another Pyarelal-style fabrication.
                "review_recommended": review_recommended,
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
    print(f"\n*** {review_count} clue(s) flagged review_recommended=true, each ***")
    print(f"*** with {CLUE_OPTIONS_PER_TOPICAL_WORD} clue_options to choose from ***")
    print("*** (or write your own). Check each against its source_snippet ***")
    print("*** and context_meta before calling this puzzle final -- see    ***")
    print("*** project_log_week1_part3.md section 3 for why.               ***")


if __name__ == "__main__":
    main()

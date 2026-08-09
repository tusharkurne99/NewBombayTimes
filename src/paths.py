"""
paths.py -- central path definitions for the New Bombay Times pipeline.

Every module imports its file paths from here instead of hardcoding a
relative filename. Two reasons this exists:

1. All pipeline scripts live in src/, one level below the project root,
   but data/output files live in data/ and output/ (also one level below
   root) -- a hardcoded "word_bank.txt" would look in the wrong place
   depending on the caller's current working directory. Computing paths
   from this file's own location makes every script runnable from
   anywhere (src/, project root, scripts/, etc.) with identical behavior.
2. It's one place to look when reorganizing folders, instead of hunting
   through every module for a string literal.

Directory layout:
  data/raw/         -- large third-party downloads, rarely touched directly
  data/wordbanks/   -- built/merged word lists (the actual solver inputs)
  data/context/     -- scraped news/trivia + per-word clue context
  output/test_grids/ -- grid_generator.py output (grid only, no clues)
  output/puzzles/   -- clue_generator.py output (final, playable puzzles)
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(ROOT, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
WORDBANKS_DIR = os.path.join(DATA_DIR, "wordbanks")
CONTEXT_DIR = os.path.join(DATA_DIR, "context")

OUTPUT_DIR = os.path.join(ROOT, "output")
PUZZLES_DIR = os.path.join(OUTPUT_DIR, "puzzles")
TEST_GRIDS_DIR = os.path.join(OUTPUT_DIR, "test_grids")

for _d in (RAW_DIR, WORDBANKS_DIR, CONTEXT_DIR, PUZZLES_DIR, TEST_GRIDS_DIR):
    os.makedirs(_d, exist_ok=True)

# --- raw downloaded source data (build_word_bank.py / build_crossword_quality_wordlist.py) ---
WORDS_ALPHA = os.path.join(RAW_DIR, "words_alpha.txt")
CROSSWORD_WORDLIST_RAW = os.path.join(RAW_DIR, "crossword_wordlist_raw.txt")

# --- word banks: built once/occasionally by setup_evergreen.sh ---
WORD_BANK = os.path.join(WORDBANKS_DIR, "word_bank.txt")
INDIA_WORD_BANK = os.path.join(WORDBANKS_DIR, "india_word_bank.txt")
CROSSWORD_QUALITY_WORDS = os.path.join(WORDBANKS_DIR, "crossword_quality_words.txt")

# --- word banks: (re)built daily by merge_sources.py ---
MERGED_WORD_BANK = os.path.join(WORDBANKS_DIR, "merged_word_bank.txt")
MIDI_CROSSWORD_WORD_BANK = os.path.join(WORDBANKS_DIR, "midi_crossword_word_bank.txt")
PRIORITY_WORDS = os.path.join(WORDBANKS_DIR, "priority_words.txt")

# --- context / scraped data ---
CANDIDATES = os.path.join(CONTEXT_DIR, "candidates.json")
INDIA_TRIVIA = os.path.join(CONTEXT_DIR, "india_trivia.json")
INDIA_TRIVIA_OLD = os.path.join(CONTEXT_DIR, "india_trivia_old.json")
WORD_CONTEXT = os.path.join(CONTEXT_DIR, "word_context.json")


def test_grid_path(size_arg: str) -> str:
    return os.path.join(TEST_GRIDS_DIR, f"test_grid_{size_arg}.json")


def puzzle_path(date_str: str, size_arg: str) -> str:
    return os.path.join(PUZZLES_DIR, f"puzzle_{date_str}_{size_arg}.json")

#!/bin/bash
# setup_evergreen.sh
# Run this OCCASIONALLY, not daily:
#   - build_word_bank.py: builds the general English word bank (Mini).
#     Rarely needs rebuilding -- only if you change the filtering logic
#     in word_filters.py, or want to widen/narrow the word pool.
#   - build_crossword_quality_wordlist.py: downloads the curated,
#     community-scored crossword word list (Midi/Crossword). This is what
#     actually makes Midi/Crossword solvable in reasonable time -- see
#     grid_generator.py's comments on MIDI_DENSITY/CROSSWORD_DENSITY for
#     why a generic dictionary isn't enough at those sizes. Rarely needs
#     rebuilding -- the source list doesn't change often.
#   - india_trivia_scraper.py: refreshes India-context trivia from
#     Wikipedia. Weekly or monthly is plenty -- the underlying Wikipedia
#     content and pageview popularity don't change meaningfully day to
#     day, and re-running it daily would hammer Wikipedia's API for no
#     benefit.
#
# After running this, run run_daily.sh to actually produce puzzles using
# the refreshed assets.

set -e
cd "$(dirname "$0")"

if [ -d "venv" ]; then
    source venv/bin/activate
fi

echo "=== Building general word bank (Mini) -- takes a few minutes ==="
python build_word_bank.py

echo ""
echo "=== Downloading curated crossword-quality word list (Midi/Crossword) ==="
python build_crossword_quality_wordlist.py

echo ""
echo "=== Scraping India trivia from Wikipedia (takes several minutes) ==="
python india_trivia_scraper.py

echo ""
echo "=== Done. Evergreen assets refreshed. ==="
echo "Run ./run_daily.sh next to produce puzzles using them."
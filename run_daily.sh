#!/bin/bash
# run_daily.sh
# The actual daily puzzle pipeline. Run this every day to produce today's
# three puzzles (Mini, Midi, Crossword). Assumes word_bank.txt,
# crossword_quality_words.txt, and india_trivia.json/india_word_bank.txt
# already exist (built once via setup_evergreen.sh, refreshed occasionally,
# NOT rebuilt every day).
#
# `set -e` is the key fix for the exact bug we hit earlier: if any step
# fails partway through, the WHOLE pipeline stops immediately, rather than
# silently continuing with stale data from an earlier successful run (e.g.
# grid_generator.py using an old merged_word_bank.txt because
# merge_sources.py never ran or failed).
#
# Timing note: Mini + Midi are fast (seconds). Crossword (15x15) takes
# roughly 40-60 seconds to solve -- fine for an overnight/once-daily batch
# job, just don't expect this whole script to finish instantly.

set -e

# Always run from this script's own directory, regardless of where it's
# invoked from, so relative paths (word_bank.txt etc.) resolve correctly.
cd "$(dirname "$0")"

if [ -d "venv" ]; then
    source venv/bin/activate
fi

# echo "=== [1/4] Scraping today's news ==="
# python scrapper.py

# echo ""
# echo "=== [2/4] Merging word sources (news + trivia + general) ==="
# python merge_sources.py

echo ""
echo "=== [3/4] Generating grids (Mini, Midi, Crossword) ==="
# python grid_generator.py mini
python grid_generator.py midi
python grid_generator.py crossword

echo ""
echo "=== [4/4] Generating clues (requires Ollama running) ==="
# Fail fast with a clear message rather than letting clue_generator.py
# hang/error confusingly if Ollama isn't running.
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "ERROR: Ollama is not reachable at localhost:11434."
    echo "Start it in another terminal with: ollama serve"
    exit 1
fi
python clue_generator.py mini
python clue_generator.py midi
python clue_generator.py crossword

echo ""
echo "=== Done. Today's Mini, Midi, and Crossword puzzles are ready. ==="
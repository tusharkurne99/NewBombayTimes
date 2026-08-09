#!/bin/bash
# publish.sh
# Run this AFTER run_daily.sh and AFTER you've reviewed today's flagged
# clues (every review_recommended: true entry in output/puzzles/*.json --
# see project_log_week1_part3.md section 3 and project_log_week2.md
# section 5 for why this step matters, not just what it does).
#
# What it does:
#   1. publish_web.py slims today's reviewed puzzle files (stripping
#      editorial-only fields: clue_options, review_recommended,
#      source_snippet/source, context_meta) into web/data/puzzles/
#      latest_<size>.json -- what the live site actually reads.
#   2. Commits and pushes web/data/puzzles/ so GitHub Pages picks up the
#      change.
#
# This is deliberately a SEPARATE, manual step from run_daily.sh, not
# folded into it -- publishing is the one irreversible, outward-facing
# action in the whole pipeline (once pushed, it's live), so it should
# only happen after you've actually looked at the puzzle, not
# automatically the moment generation finishes.
#
# Usage: ./scripts/publish.sh [YYYY-MM-DD]   (defaults to today)

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ -d "$ROOT/venv" ]; then
    source "$ROOT/venv/bin/activate"
fi

cd "$ROOT/src"
python publish_web.py "$@"

cd "$ROOT"
if git diff --quiet -- web/data/puzzles/ && git diff --cached --quiet -- web/data/puzzles/; then
    echo ""
    echo "No changes in web/data/puzzles/ -- nothing to publish (already up to date?)."
    exit 0
fi

git add web/data/puzzles/
git commit -m "Publish puzzles for $(date +%Y-%m-%d)"

echo ""
read -p "Push to GitHub now, making this live? [y/N] " confirm
if [[ "$confirm" =~ ^[Yy]$ ]]; then
    git push
    echo "Pushed. Live once GitHub Pages finishes rebuilding (usually under a minute)."
else
    echo "Committed locally but NOT pushed. Run 'git push' yourself when ready."
fi

# New Bombay Times

Daily India-focused crossword pipeline (Mini/Midi/Crossword) -- news
scraping + Wikipedia trivia -> constraint-solved grid -> local-LLM clues.
Solo learning project; full design history and lessons-learned are in
[`docs/`](docs/).

## Layout

```
src/       pipeline modules (see docs/project_log_week1*.md for how each works)
scripts/   run_daily.sh (daily), setup_evergreen.sh (occasional)
data/      word banks, scraped news/trivia context
output/    generated grids (test_grids/) and final puzzles (puzzles/)
docs/      project logs + the full planning chat transcript
```

## Running it

```bash
./scripts/setup_evergreen.sh   # occasional: rebuild word banks + trivia
./scripts/run_daily.sh         # daily: scrape, merge, solve, generate clues
```

Requires the venv (`venv/`) with its dependencies installed, and Ollama
running locally (`ollama serve`) with `llama3.1:8b` pulled, for clue
generation.

**Before treating any puzzle as final**, open `output/puzzles/puzzle_<date>_<size>.json`
and read every clue with `"review_recommended": true` against its
`source_snippet` -- the local LLM has produced confidently wrong clues
before, including one fabricated claim about a real named person. See
`docs/project_log_week1_part3.md` section 3 for the details.

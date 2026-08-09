# New Bombay Times

Daily India-focused crossword pipeline (Mini/Midi/Crossword) -- news
scraping + Wikipedia trivia -> constraint-solved grid -> local-LLM clues.
Solo learning project; full design history and lessons-learned are in
[`docs/`](docs/).

## Layout

```
src/       pipeline modules (see docs/project_log_week1*.md for how each works)
scripts/   run_daily.sh (daily), setup_evergreen.sh (occasional), publish.sh (ship to the site)
data/      word banks, scraped news/trivia context
output/    generated grids (test_grids/) and final puzzles (puzzles/) -- full editorial data
web/       the actual website (static HTML/CSS/JS, deployed via GitHub Pages)
docs/      project logs + the full planning chat transcript
```

## Daily workflow

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
`docs/project_log_week1_part3.md` section 3 for the details. Each flagged
clue now comes with `clue_options` (3 alternate angles to choose from) and
`context_meta` (where the fact actually came from) -- pick the best option,
or edit `"clue"` directly in the JSON, before publishing.

Once you're happy with a day's clues:

```bash
./scripts/publish.sh           # slim + copy today's puzzles into web/, then git push
```

This is a deliberately separate, manual step -- it's the one
irreversible, outward-facing action in the pipeline (once pushed, the
site is live), so it shouldn't happen automatically the moment
generation finishes.

## The website (`web/`)

Plain HTML/CSS/JS, no framework, no build step -- `web/index.html` (today's
three puzzle cards) and `web/solve.html` (the actual solving UI: grid,
timer, username entry, per-day leaderboard). Reads puzzle data from
`web/data/puzzles/latest_<size>.json`, written by `publish.sh` above.

**Leaderboard note:** currently backed by `localStorage` (`web/assets/leaderboard.js`)
-- each visitor only sees their own browser's board, not a real shared
one. This is intentional for now (zero setup, zero cost) and isolated
behind a small interface specifically so it can be swapped for a real
shared backend (Firebase/Firestore) later without touching `index.html`/
`solve.html`.

### Hosting: GitHub Pages (free)

One-time setup:
1. GitHub repo -> **Settings -> Pages -> Source -> "GitHub Actions"**.
2. That's it -- `.github/workflows/pages.yml` deploys `web/` automatically
   on every push to `main` that touches it (which `publish.sh` does for
   you). Your site will be live at
   `https://<username>.github.io/<repo-name>/`.

### Automating the daily run

`run_daily.sh` and `publish.sh` still need something to actually trigger
them each day -- currently that's a scheduled task on the machine running
Ollama (Windows Task Scheduler calling into WSL), not a cloud job, since
the clue-generation step depends on a local LLM. `publish.sh` prompts for
confirmation before pushing, so it's still safe to run unattended up to
that point and finish the review by hand.

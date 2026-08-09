# New Bombay Times — Launch Plan
### Everything remaining, planned against a Saturday, Aug 15 2026 go-live

**Starting point:** today is Sunday, Aug 9. The backbone (scraping -> grid generation -> clue generation -> review) and a working website (`web/`, deployed via GitHub Pages, localStorage leaderboard) both exist and have been tested. This document is the full remaining task list, split into **backbone** and **web**, then organized into a realistic 6-day schedule. Items are marked **[must]** (blocks going live responsibly) or **[nice]** (real improvement, safe to cut or defer past Saturday if time runs short).

---

## Part 1 — Backbone (pipeline) remaining work

Carried over from `project_log_week2.md` section 7, re-prioritized with "about to have real visitors" in mind.

### 1.1 [must] Confirm the human review step is actually usable under time pressure
Right now, reviewing flagged clues means opening a raw JSON file and reading `review_recommended: true` entries by eye. That was fine while this was a one-person research project; it's a real risk once you're doing it every morning before work/school with a website waiting on you. **Action:** build a small script (`src/review_clues.py`, plain terminal output is enough -- no need for a web UI) that prints only the flagged clues for a given day, side by side with all 3 `clue_options` and the `context_meta` provenance, so a full review takes under a minute instead of scrolling raw JSON. This directly de-risks the daily habit this whole project depends on.

### 1.2 [nice] Crosswordese/junk-fill spot check on fresh output
The `SSSS`/`WSWS` class of bug is fixed, but that was found by inspecting specific past output -- not an exhaustive guarantee nothing else in that category exists. **Action:** after each of the next few real daily runs, skim the generated grids (not just the flagged clues) for anything that reads as meaningless. Low effort, worth doing precisely because you'll be looking at real output anyway during review.

### 1.3 [nice] Content-sensitivity spot check with fresh eyes
The sensitive-word list (~275 entries, sourced from a public list) is a strong baseline but was validated by me, not by you reading real daily output with your own judgment of what's appropriate for your audience. **Action:** flag anything borderline you personally notice during the first week of real runs; add it to `SENSITIVE_WORDS` in `word_filters.py` the same way MAHAL/NADU were added -- a small, ongoing list, not a one-time task.

### 1.4 [nice, explicitly deferred] Cricket data source, TMDb integration, 50/50 India/international balance
All three were discussed in `project_log_week1_part3.md` section 4 and never built. None of them block going live -- they're volume/variety improvements to the trivia pool, not correctness or safety issues. Revisit after the site has real visitors and you have a better sense of what's actually thin.

---

## Part 2 — The website: remaining work

### 2.1 [must] Turn on GitHub Pages (one click, if not already done)
Repo -> Settings -> Pages -> Source -> "GitHub Actions". Confirm the site is actually reachable at `https://<username>.github.io/<repo-name>/` before doing anything else this week -- everything downstream assumes this works.

### 2.2 [must] Mobile-friendly layout
This is the one you specifically flagged, and it's a real gap: the site was designed and tested on a desktop-width screen. A meaningful share of real visitors will be on a phone, and right now:
- The clue side-lists are hidden entirely below 760px width (a deliberate placeholder from the design phase, not a real mobile solution) -- there's currently no way to read the clue list on a phone at all except the single active-clue banner.
- There's no on-screen keyboard. Typing a crossword answer on a phone needs a visible keyboard, since a phone has no physical one -- right now the page just waits for `keydown` events that a touchscreen never sends on its own.
- Touch targets (grid cells, buttons) haven't been checked against a comfortable tap size on a real small screen.
- The masthead/switcher/toolbar row heights and the grid's cell-size formula were tuned by eye on a desktop viewport, not validated on real phone dimensions (e.g. a 375px-wide screen).

**Concrete plan:**
1. Replace the "hide clue lists below 760px" placeholder with an actual mobile pattern: a toggle or swipe between "grid view" and "clue list view," or a collapsible drawer -- something that keeps both usable, not one of them just gone.
2. Add a simple on-screen keyboard (a row of letter buttons plus backspace) shown only when a touch device is detected or the viewport is narrow, wired into the exact same input-handling code the physical keyboard already uses (the logic that fills a cell and advances shouldn't care whether the letter came from a `keydown` event or a tap).
3. Test on at least one real phone (not just a resized desktop browser window) before calling this done -- resized-browser testing misses real touch-target and virtual-keyboard-overlap issues.

### 2.3 [must] Real shared leaderboard (Firebase)
Today's leaderboard is per-browser only (localStorage) -- genuinely fine as a placeholder, not fine as the actual feature you pitched (a real daily competition across everyone who plays). Steps:
1. Create a free Firebase project (console.firebase.google.com -- a Google account is all that's needed).
2. Enable **Firestore** (Firebase's database product) in test mode initially.
3. Get your project's config keys from the Firebase console and add them to the site (I'll walk through exactly where).
4. I rewrite the *inside* of `getBoard`/`submitTime` in `web/assets/leaderboard.js` to read/write Firestore instead of `localStorage` -- `index.html` and `solve.html` don't need to change at all, since they only ever call those two functions.
5. Before opening this up publicly: Firestore's default "test mode" allows anyone to read/write anything, which is fine for a few days of your own testing but should be tightened (a proper security rule limiting what a write can contain -- a name and a time, nothing else) before real strangers are hitting it.

### 2.4 [must] Automate the daily run (Windows Task Scheduler)
`run_daily.sh` and `publish.sh` still require you to manually open a terminal. Once you're relying on this daily, a scheduled task removes the single point of failure of "I forgot" or "I was busy that morning." **Action:** set up a Task Scheduler entry that triggers WSL to run `run_daily.sh` at a fixed early-morning time; `publish.sh` stays a manual step on purpose (see `project_log_week3.md` section 3.3 for why publishing is deliberately not automatic).

### 2.5 [nice] "How to Play" and hamburger menu currently do nothing
Both exist visually (from the design pitch) but have no real behavior wired up. **Action:** at minimum, make "How to Play" open a short modal explaining the rules (timer, leaderboard, no account needed) -- this matters more once strangers are actually landing on the site with no context. The hamburger menu can either get real content (About, past puzzles archive) or be removed if there's nothing to put in it yet -- a menu button that does nothing is worse than no button.

### 2.6 [nice] Real favicon + basic SEO
The Artifact mockups used an emoji favicon (a mockup-tool convenience) -- the real deployed site should have an actual favicon file, plus a `<meta name="description">` and a proper page title, so a shared link or a search result shows something intentional rather than nothing/default.

### 2.7 [nice] A visible way to solve past puzzles
Right now `latest_<size>.json` is overwritten daily -- yesterday's puzzle is gone from the live site the moment today's is published (still recoverable from git history, just not visitor-facing). An archive page is a real, well-liked feature of puzzle sites (and good for search traffic later) but is meaningfully more work (needs a dated URL scheme, an index of past puzzles) -- explicitly fine to defer past Saturday.

---

## Part 3 — Day-by-day schedule to Saturday, Aug 15

Front-loaded so the riskiest/most time-uncertain items (Firebase, mobile) happen first, with buffer at the end.

**Monday, Aug 10**
- [must] Enable GitHub Pages, confirm the live URL actually works end to end (visit it, click into a puzzle, solve it for real).
- [must] Set up Task Scheduler for `run_daily.sh`.
- [must] Build the clue-review helper script (section 1.1) -- do this early since you'll want it every subsequent morning this week anyway.

**Tuesday, Aug 11**
- [must] Mobile layout, part 1: clue-list mobile pattern (drawer/toggle) + on-screen keyboard. This is the single biggest remaining chunk of real work -- give it the most time.

**Wednesday, Aug 12**
- [must] Mobile layout, part 2: real-phone testing and fixes from what Tuesday's build actually reveals. Layout bugs are always worse in practice than in theory -- budget the whole day, not just cleanup time.
- [must] Firebase account + Firestore setup (your part -- can happen in parallel/evenings, doesn't need my involvement beyond the walkthrough).

**Thursday, Aug 13**
- [must] Wire the real Firestore-backed leaderboard once Firebase is set up.
- [nice] "How to Play" modal + favicon/SEO basics, if time allows.

**Friday, Aug 14**
- [must] Full dry run: real morning pipeline run -> review via the new helper script -> publish -> confirm live site shows it correctly -> solve it end to end on both desktop and the phone you tested with -> confirm a leaderboard entry actually appears for someone else (a second browser/device counts).
- Buffer day for anything Tuesday/Wednesday's mobile work or Thursday's Firebase wiring didn't fully resolve.

**Saturday, Aug 15 — go live**
- Morning: real run, real review, real publish -- same as every day going forward, just the first one you're treating as "actually live to whoever you share it with."
- Tighten Firestore's security rule (section 2.3, step 5) before/as you share the link more widely.

---

## What "done" means for Saturday

Minimum bar to call this launched, everything else in this document beyond that is genuinely optional for day one:
- [ ] Site is live at a real URL, reachable by someone who isn't you.
- [ ] All three puzzle sizes load and are fully solvable on both desktop and a real phone.
- [ ] Leaderboard is shared (Firestore), not per-browser.
- [ ] The daily pipeline ran, was reviewed by you, and was published without you needing my help to do it.
- [ ] You've read this week's clues yourself and are comfortable calling them fit to publish.

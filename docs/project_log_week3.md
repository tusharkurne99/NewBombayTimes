# New Bombay Times — Project Log, Week 3
### Building the actual website — from zero web experience to a live, playable app

**Continuation note:** Picks up after `project_log_week2.md`. That document covered repo reorganization, a live Wikipedia rate-limit bug, word-filter hardening, and the clue-review workflow -- all on the *generation pipeline* side. This document covers the first work on the *product* side: the website itself. Written with explicit basics included throughout, since (per the user's own framing) this is genuinely new ground -- no prior web design or hosting experience going in. If a term is used before it's explained, that's a bug in this document, not something you're expected to already know.

---

## 1. The big picture: what actually needs to exist for a website to work

Before any code: a website that a stranger can visit is three separate things, and it's worth being precise about which one solves which problem, because the whole plan (and the free-hosting decision) rests on this.

1. **The content** -- HTML, CSS, and JavaScript files. HTML is structure (what elements exist: a heading, a grid, a button). CSS is appearance (colors, spacing, layout). JavaScript is behavior (what happens when you click something, type a letter, or finish a puzzle). These three are just *files* -- they don't need a server "running" any code to exist; a browser can open them directly.
2. **Hosting** -- somewhere those files physically live so a browser anywhere in the world can download them over the internet. This is the part that costs money for most kinds of websites (a server has to be kept running 24/7).
3. **A domain name** -- a human-readable address (`newbombaytimes.com`) that points at the hosting. Entirely optional; every host gives you a free, uglier-but-functional address already.

**The key decision that made this project free:** this site doesn't need a traditional "server" at all. A server is necessary when a site has to *compute* something per visitor (run a database query, check a password, generate a page on the fly). This site's content -- the crossword grid, the clues -- is the same for every visitor on a given day, already sitting there as a JSON file (JavaScript Object Notation -- a simple, human-readable text format for structured data; every `puzzle_*.json` file the pipeline produces is one of these). That makes this a **static site**: files that get served exactly as they are, with all the "computation" (rendering the grid, handling keystrokes, checking answers) happening inside the visitor's own browser via JavaScript, not on a server. Static hosting is free, at essentially unlimited scale, from several providers -- this project uses **GitHub Pages**, since the code already lives on GitHub and it requires zero new sign-ups.

---

## 2. Two rounds of design, before any real code

### 2.1 Why mockups first, in an isolated tool, before touching the real project
The homepage and solve-page designs were built first as **Artifacts** -- a separate preview tool that renders a single self-contained HTML file and gives back a shareable link, with no connection to the actual project repository. This was deliberate, not a detour: getting the *visual direction* approved (colors, layout, the logo, whether the leaderboard/timer concept even looked appealing) was cheap to iterate on there, and wrong only costs a re-render. Building it directly into the real site first, then discovering the color scheme or layout needed to change, would have meant redoing real, wired-up code instead of a static mockup. This is the same "isolate the risky part" principle from the very first week of this project (debugging the grid solver against a dummy word list before touching the scraper) -- here it's "get the design signed off cheaply before writing the real, interactive version."

### 2.2 What was actually decided in that phase
- Visual direction: a deliberate homage to NYT Games' actual crossword landing page (masthead, card layout, color language) but with an original identity -- own wordmark, own color values, explicitly *not* a copy.
- The logo went through one real revision: the first attempt (a small 2x2 grid of light/dark squares, meant to echo a crossword pattern) read as a domino/dice pip rather than anything meaningful. Replaced with an arch silhouette referencing the Gateway of India -- Bombay's actual, specific, recognizable monument -- which does real work as a brand mark instead of being generic crossword iconography.
- The core interactive concept -- pick a name for the day, solve against a timer, land in the daily top 5 for a small celebration (confetti) -- was prototyped and approved as an actual clickable demo (a real button that fires the real confetti animation), not just described in words.

---

## 3. From mockup to the real site: what "self-contained Artifact" vs. "real project" actually means

This is the part most worth understanding if you haven't built a multi-file website before.

### 3.1 Why one big HTML file had to become several files
The Artifact mockups were single files with everything inline: all the CSS inside a `<style>` tag, all the JavaScript inside a `<script>` tag, even the puzzle data itself pasted directly into the JavaScript as a big object. That's fine for a preview tool that can only host one file, but wrong for a real site for two concrete reasons:
1. **Duplication.** The homepage and the solve page share a lot -- the same colors, the same masthead, the same confetti effect. Keeping that in one file per page means every future tweak (say, changing the accent color) has to be made twice and will eventually drift out of sync.
2. **Embedded data goes stale.** A mockup with today's puzzle *pasted into the JavaScript* will always show today's puzzle, forever, even after the actual daily pipeline produces a new one tomorrow. The real site needs to ask, freshly, "what's today's puzzle?" -- which is what the next section is about.

**The fix:** shared pieces became their own files under `web/assets/` (`theme.css` for colors/layout tokens, `leaderboard.js` and `confetti.js` for behavior used by both pages), loaded into each HTML page via `<link rel="stylesheet">` (for CSS) and `<script src="...">` (for JavaScript) -- the standard way one file tells the browser "also load this other file." `web/index.html` and `web/solve.html` now only contain what's actually specific to each page.

### 3.2 `fetch()`: how a live page gets today's data instead of yesterday's
`fetch()` is a JavaScript function that asks the browser to download something over the network -- in this case, a JSON file sitting right there in the same website (`data/puzzles/latest_mini.json`). It's asynchronous, meaning the browser doesn't freeze waiting for the download; the code says "start this download, and *when* it finishes, run this other bit of code with the result" (the `.then(...)` pattern seen throughout `solve.html`). This is the mechanism that replaced the mockup's pasted-in data: the real page has no puzzle data baked into it at all until it actually runs in a browser and fetches whatever the *current* `latest_<size>.json` file contains -- which is exactly the file `publish.sh` overwrites every day.

### 3.3 The publish step: why generating a puzzle and making it public are two different actions
`publish_web.py` (new this week) takes a fully reviewed `puzzle_<date>_<size>.json` -- which carries a lot of internal-only information: alternate clue options that weren't chosen, links to the news articles a clue was based on, flags marking which clues need human review -- and writes a stripped-down copy containing only what a solver actually needs (the grid, the numbering, and the *chosen* clue text) to `web/data/puzzles/latest_<size>.json`. Two reasons this is a separate step from generation, not folded in automatically:
- **Nothing solver-facing should carry editorial metadata.** A visitor has no reason to see which clue options were rejected, or the raw links the pipeline scraped from.
- **Committing to git and pushing to GitHub are two different moments**, and this matters for a reason specific to this project: `git commit` saves a snapshot *locally* -- reversible, private, no effect on the live site. `git push` sends that snapshot to GitHub, which (via the automation in section 5) is what actually updates the live website. Given this pipeline's own history of an LLM occasionally fabricating something about a real person (documented in `project_log_week1_part3.md` and `project_log_week2.md`), the step that makes something *public* deliberately requires a typed confirmation (`scripts/publish.sh` asks "Push to GitHub now, making this live? [y/N]") rather than happening silently as a side effect of running the daily pipeline.

---

## 4. Building the actual solving experience

### 4.1 What a "crossword grid" is, to a browser
There's no special "crossword" feature in HTML -- the grid is just a `<div>` for each cell, arranged using **CSS Grid** (a layout system for arranging boxes into rows and columns, which is what the crossword's own grid structure maps onto very naturally). Each cell knows its row/column, whether it's black (part of the pattern, not a letter), and what number (if any) it should display in its corner -- all of this comes directly from the same `numbering` and `grid` fields already present in every puzzle JSON file the pipeline has been producing since Week 1.

### 4.2 Slot reconstruction: a small but important piece of logic
The puzzle JSON stores clues keyed by direction and number ("1-Across", "4-Down"), but doesn't explicitly list *which grid cells* belong to each clue -- that's implicit in the grid's black-square pattern. `buildSlots()` in `solve.html` re-derives this by scanning the grid for runs of non-black cells, the same conceptual operation `grid_generator.py`'s `find_slots()` already does in Python during generation (see `project_log_week1.md` section 5.2) -- reimplemented here in JavaScript because it has to run in the browser, not on the machine that generated the puzzle.

### 4.3 Keyboard interaction, and why it's more involved than it looks
Typing into a crossword has real conventions: typing a letter should move you to the *next* cell in the current word, not just sit still; arrow keys should move you within the grid and switch which direction ("across" vs "down") you're implicitly working in; clicking an already-selected cell should toggle between across and down if both exist there. None of this is a browser built-in -- it's all explicit `keydown` event handling (`document.addEventListener('keydown', ...)`) tracking a small amount of state: which cell is selected, and which direction is active.

### 4.4 The timer, pausing, and why `Date.now()` matters
The timer doesn't literally "count up" via some ticking mechanism -- it records the real-world timestamp (`Date.now()`, milliseconds since a fixed reference point) when solving starts, and on every display update just computes *elapsed = now - start*. This is more robust than incrementing a counter every second, because it can't drift out of sync if the browser tab is busy or throttled. Pausing works by remembering how much time had already elapsed, then starting a fresh "start" timestamp when resumed -- the same pattern used anywhere something needs to be pausable.

### 4.5 The leaderboard, and the specific tradeoff being made right now
`localStorage` is a small amount of storage the browser gives each website, persisting between visits, but **private to that one browser** -- nothing stored there is visible to anyone else, or even to the same person on a different device. The leaderboard today (`web/assets/leaderboard.js`) is deliberately built this way: it's a real, working feature (you genuinely get ranked against your own past solves), but it is **not yet a shared leaderboard** -- your "today's top 5" and someone else's are two different lists. This was an explicit scope decision (see the prior conversation) to ship *something real and testable* now rather than block the whole feature on setting up an external account/service. The interface (`getBoard`/`submitTime`/`formatTime`) was deliberately kept small specifically so the *inside* of those three functions can be rewritten to talk to a real shared backend (Firebase, covered in the next planning document) without either HTML page needing to change at all.

---

## 5. Hosting and automatic deployment

### 5.1 What "GitHub Pages" actually does
GitHub Pages is a free feature of GitHub (the code-hosting platform this project's repository already lives on) that takes a folder of static files and serves them as a real website at a URL like `https://<username>.github.io/<repo-name>/`. It has to be turned on once, in the repository's Settings, by choosing "GitHub Actions" as the deployment source (rather than the older "deploy from a branch" method) -- this is a manual, one-time click in the GitHub web UI, not something achievable from a script.

### 5.2 What a GitHub Actions "workflow" is
A **workflow** is a small YAML (a structured text format, similar in spirit to JSON but designed to be more human-writable) file that tells GitHub "when X happens, run these steps on a temporary cloud machine." `.github/workflows/pages.yml` says: whenever something inside `web/` changes on the `main` branch (which happens every time `publish.sh` pushes), spin up a fresh machine, grab the `web/` folder, and hand it to GitHub Pages to publish. This is what makes the site auto-update the moment `publish.sh` pushes a new day's puzzles -- no manual re-deploy step, no button to click on GitHub's side.

### 5.3 What's still a manual, local step, and why
The actual puzzle generation (scraping, grid-solving, clue-writing) still has to run somewhere with **Ollama** installed -- a program that runs a large language model directly on a computer's own hardware. Free cloud hosting (GitHub Pages included) only serves static files; it doesn't give you a computer to run other programs on. So generation still happens on the same local machine as before, on a schedule (Windows Task Scheduler, not yet configured -- see the companion planning document), with only the *finished, reviewed* output ever being pushed to the public repository.

---

## 6. Two real bugs, both about CSS layout, both worth understanding generally

These are documented in detail because the underlying lessons generalize well beyond this project.

### 6.1 "Selecting a clue scrolled the whole page"
**What happened:** clicking a clue in the side list was supposed to smoothly scroll that clue into view *within its own small list* if it wasn't already visible. The code used a standard browser method, `element.scrollIntoView()`.

**Why it went wrong:** `scrollIntoView()` finds the *nearest scrollable ancestor* and scrolls that -- but if the containing list is short enough that everything already fits (true for every Mini puzzle's clue list, which only has 5 entries), there's nothing to scroll *inside* the list, so the browser escalates the request outward and scrolls the whole page instead, even though the clue was already fully visible. This is why it specifically didn't happen on the Crossword (whose 30+ clue list is genuinely taller than its allotted space, so the internal scroll satisfies the request and the page itself never needs to move).

**The fix, and the general lesson:** replaced the built-in method with a few lines of manual math (compare the clue's position to the list's current visible window, and only adjust the *list's own* scroll position, never the page's). **General lesson:** a browser convenience method that "just works" in the common case can have a different, surprising behavior in an edge case (a container that never needs its own scrollbar) -- worth testing against the *smallest* realistic case, not just the largest, since scrolling bugs often hide there.

### 6.2 "The grid and clue list swapped between side-by-side and stacked, seemingly at random"
**What happened:** depending on which clue was currently selected, the whole page layout would flip between the grid-and-clues sitting next to each other, and the clues dropping below the grid -- for no reason visible in the puzzle itself.

**Why it went wrong:** this needs one piece of background -- **Flexbox** is a CSS layout system where a container can say "if my children don't all fit on one line, wrap them onto a new line" (`flex-wrap: wrap`). That's exactly what makes the site correctly switch to a mobile-friendly stacked layout on a narrow screen. The bug: the *width* of the grid's containing box wasn't fixed to a specific number of pixels -- it was left to be "however wide its content needs," and one piece of that content (the banner showing the current clue's text) was set to stretch to "100% of my container's width," which is a genuinely circular, ambiguous instruction when the container's own width isn't fixed yet. In practice, longer or shorter clue text subtly changed how wide the browser decided that box should be, by just enough to tip the *total* row width across the wrap threshold on some clues and not others.

**The fix, and the general lesson:** the code now calculates the grid's real pixel width directly (cell size times number of cells, plus the small gaps between them) and locks the container to exactly that width, removing the ambiguity entirely. **General lesson:** when a layout behaves inconsistently for a reason that seems unrelated to layout (here: clue text length), suspect a sizing ambiguity somewhere in the chain rather than assuming it's random -- CSS sizing that depends on "my content" is only as stable as that content is, and text length is rarely stable.

---

## 7. Cross-Cutting Lessons (new, in addition to Weeks 1-2)

1. **A static site removes an entire category of cost and complexity (servers, databases, always-on infrastructure) when the content genuinely doesn't need to be computed per-visitor** -- recognizing that this project's puzzles are "the same for everyone, once a day" was the single decision that made free hosting possible at all.
2. **Prototype the risky/subjective part (visual design, interaction feel) somewhere cheap to throw away, before wiring it into the real, harder-to-change system.** Same principle as isolating the CSP solver from the scraper in Week 1, applied to product design instead of an algorithm.
3. **Embedded/pasted-in data is a trap disguised as a shortcut.** It works perfectly in a demo and silently goes stale the moment the underlying data changes daily -- any "here's today's X" content needs a real fetch-fresh mechanism from day one, not as a later upgrade.
4. **The action that makes something public deserves its own deliberate step, separate from the action that produces it** -- especially in a pipeline with a known history of the generation step producing something wrong. `git commit` and `git push` being two different commands is what makes this possible to enforce cheaply.
5. **CSS layout bugs that look inconsistent or "random" are almost always a sizing ambiguity, not actual randomness** -- browsers are deterministic; the trick is finding which measurement was never pinned down in the first place.

# New Bombay Times — Project Log & Technical Reference
### Week 1: News-to-Crossword Pipeline
**Author's collaborator note:** This document is a running technical record of the project, written to be studied, not just skimmed. It covers what was built, the algorithms/concepts underneath each piece, what failed along the way and why, and what's left to do. Code artifacts referenced here were produced alongside this document during the same work session.

---

## 1. Project Overview

**Goal:** Build a daily crossword-puzzle product ("New Bombay Times") focused on Indian + light foreign context, in the style of NYT Games' Mini/Midi/Crossword, generated substantially by an automated pipeline rather than human constructors — as a personal learning project in applied ML, NLP, constraint satisfaction, and web development.

**Constraints shaping every design decision:**
- Solo project (no team) — code must be maintainable by one person.
- No budget — all tools/models/hosting must be free or near-free.
- Learning is a first-class goal, not just shipping — so this log deliberately keeps the *reasoning*, not just the final code.

**High-level pipeline (target end state):**
```
News (daily, changes)  ─┐
                         ├─► merged word pool ─► grid solver ─► filled grid ─► clue generator ─► puzzle JSON
Wikipedia (evergreen)  ─┘
```

This document covers the left half of that diagram in detail: news scraping, trivia scraping, and grid generation. Clue generation (the local LLM step) is designed but not yet built as of this writing.

---

## 2. System Architecture So Far

Four independent Python modules, deliberately decoupled so each can be developed/tested/debugged in isolation:

| Module | Purpose | Run frequency |
|---|---|---|
| `scraper.py` | Pull today's Indian + foreign news, extract candidate answer-words via NER | Daily |
| `india_trivia_scraper.py` | Pull India-context trivia (people, places, culture) from Wikipedia, weighted by real popularity | Occasional (weekly/monthly) |
| `build_word_bank.py` | One-time: build a large, frequency-filtered general English word list | Once, rarely re-run |
| `grid_generator.py` | Fill an NxN crossword grid from any word list, using constraint satisfaction | Daily (per puzzle) |

The decoupling matters pedagogically: grid generation was built and debugged against a **dummy word list first**, entirely independent of the scrapers, so that CSP-solver bugs and news-scraping bugs never got tangled together during debugging. This is a generally useful strategy: isolate the part with real algorithmic risk from the parts that are "just" data plumbing.

---

## 3. Environment Setup

- **Host:** Windows 11 laptop (MSI GF63 Thin 11UC), Intel i5-11400H, RTX 3050 (4GB VRAM), 16GB RAM.
- **Dev environment:** WSL2 (Ubuntu) rather than native Windows — chosen so the whole stack (Python, Ollama, future deployment target) matches a standard Linux environment, avoiding Windows-specific path/tooling quirks.
- **Python:** 3.11 specifically (not the system default 3.14) — spaCy's dependency chain (`click`, etc.) did not yet have working installs for 3.14 at time of writing; this is a common "bleeding-edge Python" problem with ML tooling and worth remembering as a default troubleshooting step (**try a known-stable Python minor version before debugging further**).
- **Local LLM runtime:** Ollama, installed via the Linux install script *inside* WSL (not the native Windows app), so the whole pipeline — scraping, solving, clue generation — is driven by Python scripts and CLI tools only, no GUI app dependency. GPU passthrough to WSL2 confirmed working (`nvidia-smi` inside WSL shows the RTX 3050 directly, since WSL2 shares the Windows GPU driver).
- **Models pulled:** `llama3.2:3b` (fast, fits comfortably in 4GB VRAM) and `llama3.1:8b` (higher quality, borderline VRAM fit at Q4 quantization) — chosen for the clue-generation step specifically because the user wanted hands-on experience with local open-source LLMs rather than defaulting to a hosted API.

---

## 4. Module: `scraper.py` — Daily News → Candidate Words

### 4.1 What it does
1. Pulls RSS feeds from five Indian outlets (The Hindu, Hindustan Times, Times of India, NDTV, India Today) plus one foreign source (BBC World), using `feedparser`.
2. Deduplicates articles, keeps only the last ~30 hours (a little more than 24h to tolerate feed lag).
3. Runs spaCy's pretrained NER pipeline (`en_core_web_sm`) over each article's title + summary to extract entities tagged `PERSON`, `GPE` (places), `ORG`, `EVENT`, `NORP` (nationalities/religious/political groups), `FAC`, `LOC`.
4. Scores each candidate word by how many articles mention it and how many distinct sources carry it — a simple proxy for "this is actually today's story," not just one outlet's pet topic.
5. Writes `candidates.json`: word, score, mention count, source count, and up to 3 supporting article snippets (used later for clue context).

### 4.2 Why RSS, not full-site scraping
News sites' HTML is generally not free to scrape wholesale (ToS restrictions vary, often prohibit it); RSS feeds are explicitly published for programmatic consumption, so this sidesteps that legal gray area entirely for the "which entities are in the news" signal. Full-article-text scraping (for richer clue context) was explicitly deferred as a "when this is a real business, get proper licensing" problem, not a week-1 concern.

### 4.3 Concepts involved
- **RSS/Atom feed parsing** — a solved, mechanical problem; `feedparser` handles the format differences transparently.
- **Named Entity Recognition (NER)** — a standard NLP task: given text, label spans as belonging to categories like person, place, organization. spaCy's `en_core_web_sm` is a small pretrained pipeline (no training required) good enough for this use case. This is *not* a generative/LLM task — it's a sequence-labeling classifier, architecturally simpler and much cheaper to run than calling an LLM per article.

### 4.4 Problems found and fixed
| Problem observed | Root cause | Fix |
|---|---|---|
| `TARUNTEJPAL` appeared as one word | Multi-word entity ("Tarun Tejpal") had its space stripped by the cleaning regex before splitting | Split multi-word entities into individual tokens *before* stripping punctuation, so each name part becomes its own candidate |
| `INDIA`, `IRAN`, `RUSSIA`, `CHINA` dominated the top of every day's list | These countries are mentioned in international news constantly, regardless of whether there's a genuinely new *India-specific* story | Added a manual down-weighting penalty (`ALWAYS_IN_NEWS_PENALTY`, scaled to 25% of raw score) for a short list of countries that are structurally always in the news |
| `THE` appeared as a top candidate | An entity like "The West" or "The Centre" was split on whitespace, and "THE" survived as a token | Added a small stopword filter (`STOPWORDS`) applied specifically during the multi-word-entity split step |

**Note on the `ALWAYS_IN_NEWS_PENALTY` list:** this is a small, deliberate exception to the "avoid hand-maintained lists" principle established later in this document (§6.4) — it's justified here because the list is short, closed, and unlikely to need expansion (major world powers don't change), unlike the open-ended "what counts as a generic descriptor word" problem in §6.4, which had no natural upper bound.

---

## 5. Module: `grid_generator.py` — Constraint-Based Grid Filling

This was the most algorithmically substantial piece of week 1, and also the source of the most instructive bugs.

### 5.1 The problem, formally
Crossword grid-filling is a **Constraint Satisfaction Problem (CSP)**:
- **Variables:** each across/down "slot" in the grid (a contiguous run of white squares in one direction).
- **Domains:** for each slot, all words from the word list of matching length.
- **Constraints:**
  - *Unary:* trivially satisfied by domain construction (only same-length words are candidates).
  - *Binary:* for every pair of slots that cross (share a grid cell), the letter at that cell must agree between the across word and the down word occupying it.

This is the same problem class as Sudoku or map-coloring — a well-studied area of symbolic AI (notably, this is essentially the CS50 AI course's crossword assignment, and the `arielfayol37/Crossword` GitHub repo referenced during planning is a clean implementation of the same idea).

### 5.2 Algorithm used: Backtracking search + forward checking
1. **Slot detection:** scan the grid pattern row-by-row and column-by-column to find all across/down runs of length ≥ 2, and assign standard crossword numbering (a cell gets a number if it starts an across or down slot, scanned in reading order).
2. **Crossing detection:** for every pair of slots sharing a cell, record which index within each slot's word corresponds to that shared cell.
3. **Domain construction:** group the word list by length so each slot only considers same-length candidates.
4. **Variable selection heuristic — Minimum Remaining Values (MRV):** at each step of the search, pick the *unfilled* slot with the *fewest* remaining candidate words. Intuition: this slot is most likely to fail, so discovering that failure early (rather than late) prunes the search tree faster. This is a standard, well-established CSP heuristic, not something invented for this project.
5. **Forward checking:** after tentatively placing a word in a slot, immediately prune the domains of all *crossing* slots to only words consistent with the newly placed letters. If any crossing slot's domain becomes empty, that placement is a dead end — back out *before* recursing further, rather than discovering the failure several levels deeper. This is a lightweight relative of full **arc consistency (AC-3)** — it only propagates one step (from the just-assigned variable outward) rather than iterating to a fixpoint across the whole constraint graph, which is a reasonable complexity/performance tradeoff for a 5x5 grid.
6. **Backtracking:** if a slot has no valid word left to try (after forward checking), undo the last assignment and try the next candidate for the previous slot; recurse.

### 5.3 Bug #1 — real implementation bug: incomplete rollback on forward-check failure
**Symptom:** grid generation failed even with word lists that plausibly should have worked, and failed *instantly* (a few milliseconds) rather than after an exhaustive search — a strong tell that something was being pruned incorrectly rather than the search genuinely exhausting all options.

**Root cause:** `forward_check()` prunes multiple crossing slots' domains one at a time. The original code only recorded/restored the prunings *if the whole forward-check call succeeded*; if a later crossing slot in the same call hit an empty domain (a dead end), the function returned `None` immediately — but the domains it had *already* pruned earlier in that same call were left mutated. Because the domains dictionary is a shared, mutated-in-place structure across the whole search, this silently and permanently corrupted the search state for all subsequent attempts.

**Fix:** roll back every partial pruning made during a forward-check call the moment a dead end is discovered within that same call, before returning `None`.

**Lesson:** this is a classic category of bug in backtracking search implementations — *any* early-return path out of a function that mutates shared state must guarantee it undoes exactly what it did, not just what a "successful" path would have undone. Worth specifically auditing for on any backtracking/recursive-search code.

### 5.4 Bug #2 — not a bug, a misunderstanding of the problem domain: "fully checked" grids
**Symptom:** after fixing Bug #1, generation *still* failed — including with a hand-typed dummy list of ~44 words, and even with a larger (~300 word) list, and even with a fully open 3x3 grid.

**Investigation:** timing showed these failures were near-instantaneous, and domain sizes looked reasonable (dozens of candidates per slot) — so this wasn't obviously a word-scarcity problem on its face. Deeper inspection revealed the real issue: **American-style crosswords (NYT included) are, by convention, "fully checked" — every white square belongs to *both* an across word and a down word.** This is different from British/cryptic-style grids, which often have many "unchecked" squares. Full-checking means every single letter is a constraint shared between two words simultaneously, which makes the CSP *much* harder to satisfy than a typical Sudoku-style puzzle with sparser constraints — it's closer in difficulty to constructing a **word square** (a grid where rows and columns are all independently valid words) than to an ordinary logic puzzle.

**Why this matters:** it means grid *solvability* is fundamentally gated by word list *size and density*, not by clever pattern design. Changing the black-square pattern (which was the first fix attempted) does not meaningfully relax this constraint for a 5x5 grid — every non-trivial American-style pattern will still be fully checked. **This is the actual reason professional crossword software ships with word lists in the hundreds of thousands of entries** (e.g., the well-known Peter Broda word list used by professional constructors) — it's not overkill, it's structurally necessary.

**Fix (data, not code):** downloaded a public-domain English word list (`dwyl/english-words`, ~370,000 words, via GitHub) and filtered it.

### 5.5 Bug #3 — solvable but bad: raw dictionary produces obscure fill
**Symptom:** with the full 370k-word raw dictionary, the solver *succeeded* — but filled the grid with words like `LANX`, `BHOY`, `XYLIC`, `NORIA` — technically valid English words, but not ones an ordinary solver would recognize.

**Root cause:** a raw dictionary treats every valid word as equally good. Real crossword quality depends on the solver being **able to infer the word from a clue**, which implicitly requires the word to be reasonably common. Solvability (a word exists that satisfies the constraints) and quality (the word is one people know) are separate axes, and only the first was being optimized for.

**Fix:** used the `wordfreq` library (Zipf frequency scale, roughly 1=extremely rare to 7=extremely common) to filter the dictionary down to words with `zipf_frequency >= 3.0` — reducing the pool from ~370,000 to ~6,300 words, all plausibly recognizable to an average adult reader. This became the standard "word bank" build process, encapsulated in `build_word_bank.py`.

**Lesson:** *any time you're generating content for a human audience via constraint satisfaction or search, "a solution exists" and "the solution is good" are different objectives, and only the first is captured by the raw constraints.* The frequency filter is effectively adding a soft quality objective on top of a hard feasibility constraint.

### 5.6 Current status
`grid_generator.py` reliably fills a 5x5 grid (pattern: symmetric black squares in two opposite corners, avoiding the earlier "fully checked corner pattern is a word square" trap by using 4 black squares rather than 2) from the ~6,300-word frequency-filtered word bank, in well under a second, producing recognizable words on every run.

---

## 6. Module: `india_trivia_scraper.py` — Evergreen India-Context Trivia

### 6.1 Motivation
`scraper.py` captures *today's* news, which is necessarily transient and sparse — most days won't mention, say, a specific classical dance form or a specific Prime Minister from decades ago. A separate, evergreen source of India-specific trivia (people, places, cinema, cricket, culture, history) fills out the word pool with recognizable Indian content that isn't tied to a particular day's headlines.

### 6.2 Why Wikipedia, and why not IMDb/Cricinfo
Wikipedia was chosen deliberately over more "obvious" domain-specific sources:
- Wikipedia offers an **official, sanctioned API** (`MediaWiki API` + `Wikimedia REST API`) explicitly intended for reuse; content is CC BY-SA licensed.
- **IMDb and ESPN Cricinfo were considered and explicitly rejected** — both prohibit automated scraping in their Terms of Service. Building scrapers against them would not be a legally sound foundation for this project, regardless of technical feasibility. (Noted alternative for future film data: TMDb, which has a free, official API with a built-in "popularity" field, explicitly designed for this kind of reuse. Cricket-specific data was left as an open problem — no clearly free, ToS-compliant equivalent was identified yet.)

This is a generally applicable lesson: **"can I technically scrape this" and "am I allowed to scrape this" are different questions, and a project's data-sourcing layer should be designed around sources that answer "yes" to both.**

### 6.3 What it does (mechanism)
1. For each of 14 hand-chosen Wikipedia categories (e.g. "Indian cricketers," "Prime Ministers of India," "Indian classical dance"), fetch **all** member page titles via the MediaWiki `categorymembers` API, using pagination (`cmcontinue`) to get the complete list rather than a partial one.
2. For each title, fetch its **pageview count** over the trailing 3 months via the Wikimedia Pageviews REST API (an official, key-free endpoint) — used as a real-world popularity signal.
3. Keep only the top-K (20) most-viewed titles *per category*, so that inherently lower-traffic categories (e.g. classical dance) still get fair representation rather than being drowned out by inherently higher-traffic ones (e.g. cricket) under a single global threshold.
4. Fetch a short (2-sentence) plain-text intro extract for each surviving title, to use as future clue-generation context.
5. Convert each title into 1+ crossword-answer word(s) (see §6.4/6.5).
6. Deduplicate by word (keeping the more-viewed source when a word appears from multiple titles), and write `india_trivia.json` (word + topic + source + snippet + popularity score) and `india_word_bank.txt` (just the words).

### 6.4 Bug #4 — systematic alphabetical bias
**Symptom:** on first real run, *every single source article title started with the letter A* — meaning topically-important but alphabetically-later entities (most cricketers, most actors, etc.) were never even considered.

**Root cause:** the MediaWiki `categorymembers` API returns results sorted alphabetically by default, and the original code requested only the first 60 members per category (`cmlimit=60`) with no pagination. This wasn't a popularity-ranking artifact — the popularity ranking never got the chance to run over a representative sample, because the *input* to that ranking was already truncated to an alphabetical prefix before scoring even began.

**Fix:** raise the per-request limit to the API's non-bot maximum (500) and add a pagination loop using the `cmcontinue` continuation token, so the *full* category is retrieved before any popularity-based filtering happens. This is a good general lesson about API pagination: **when an API's default ordering is not the ordering you actually want, truncating the first page of results silently bakes that ordering's bias into everything downstream** — the fix has to happen at the retrieval stage, not the filtering stage.

### 6.5 Design iteration — filtering out generic/descriptor words

This was the most conceptually interesting part of the week, and is worth a full subsection because three different approaches were tried, two were rejected with concrete evidence, and the third was adopted for a principled (not just empirical) reason.

**The problem:** Wikipedia titles like "Kailasa Temple, Ellora" or "Khajuraho Group of Monuments" are multi-word, but a crossword answer must be a single unbroken word. Naively splitting on whitespace produces junk answers like `TEMPLE`, `GROUP`, `MONUMENTS`, `LIST`, `HISTORY` — real English words, but not meaningfully "the answer" to any specific trivia fact, and liable to get an oddly specific, misleading clue attached (e.g., pairing the generic word `TEMPLE` with a snippet specifically about the Kailasa Temple would produce a nonsensical clue, since many temples exist).

**Approach 1 — hand-maintained blacklist/suffix-strip list (initial implementation).** A fixed Python set of words like `{"TEMPLE", "FORT", "GROUP", "MONUMENTS", ...}` was stripped from the end of multi-word titles, plus a separate blacklist of standalone generic words. **Explicitly identified as a weak solution by the project owner during review**, on the correct grounds that such a list can never be exhaustive — any future category could introduce a new descriptor word ("Cathedral," "Stupa," "Basilica," "Circuit") that the list doesn't know about, silently reintroducing the same class of bug.

**Approach 2 (rejected) — word-frequency thresholding.** Hypothesis: generic descriptor words are simply *more common* in everyday English than specific proper nouns, so a frequency cutoff (via the already-available `wordfreq` library) could replace the hand list. **Empirically disproven**: `zipf_frequency("delhi") = 4.29` while `zipf_frequency("monuments") = 3.69` — i.e., a specific, obviously-desirable proper noun (Delhi) scored as *more* common than a generic word we wanted to exclude (monuments). This makes sense on reflection: a word can be "common" for two different reasons — because it's a generic everyday term, *or* because it names something famous — and raw frequency conflates both, giving no clean threshold that separates them.

**Approach 3 (rejected) — part-of-speech tagging.** Hypothesis: spaCy's POS tagger could distinguish proper nouns (`PROPN`, keep) from common nouns (`NOUN`, drop) within a title. **Empirically disproven**: tested directly on real titles ("Kailasa Temple, Ellora," "Konark Sun Temple," etc.) — spaCy tagged *every* word in these short, capitalized, context-free titles as `PROPN`, including "Temple." This is a known limitation of POS taggers on short text: capitalization is a strong cue the tagger leans on heavily, and title-case phrases with no surrounding sentence give it little else to work with.

**Approach 4 (adopted) — WordNet "named instance" detection.** WordNet (a large, structured lexical database) encodes, for many entries, an explicit relationship called `instance_hypernym` — marking a word sense as referring to *a specific named individual thing* (e.g., "Delhi" as an instance-of "national capital") as opposed to a *general type* (e.g., "temple" as a type of building, with no instance relationship). This gives a principled, three-way rule:

  - Word not found in WordNet at all → WordNet's ~150,000-entry vocabulary doesn't recognize it → almost certainly a specific proper noun/name not in general use → **keep**.
  - Word found in WordNet, and at least one sense has an `instance_hypernym` → it's specifically encoded as a named individual thing (a real place, e.g.) → **keep**, even though it may also be "common" in the everyday-frequency sense.
  - Word found in WordNet, with only general "type" senses (no instance relationship) → it's a generic descriptor → **drop** (if it's trailing in a multi-word title).

  **Validated against every case that broke Approaches 2 and 3**, including the Delhi/monuments conflict — correctly kept `DELHI`, `GOA`, `INDIA`, `BRAHMAPUTRA` while correctly dropping `TEMPLE`, `FORT`, `MUSEUM`, `DISTRICT`, `HERITAGE`, `LIST`, `GROUP`, `MONUMENTS`, `HISTORY`, `SITES`.

  **One known residual failure mode, disclosed rather than hidden:** "Western Ghats" → only `WESTERN` survives, because WordNet's entry for "ghat" happens to mean "steps leading to a river" (an unrelated, genuinely generic sense) — a **homograph collision**, not a systematic gap. This is qualitatively different from the blacklist problem: it doesn't grow as new categories are added, and it affects a small, essentially unpredictable set of words rather than an open-ended category.

**Reusable lesson for future filtering problems in this project:** when trying to replace a hand-maintained list with something more principled, the right first move is not to reach for the fanciest available tool (an LLM, a large tagging model), but to ask *what structured signal in an existing, well-scoped resource actually encodes the distinction I care about* — here, WordNet's instance/type distinction was a much closer semantic match to "is this a proper name or a category word" than either raw frequency or POS tagging, both of which were answering adjacent-but-different questions.

### 6.6 Bug #5 — missing snippets due to unresolved redirects
**Symptom:** roughly 40% of entries in the first real run had no context snippet at all.

**Root cause:** many Wikipedia page titles are redirects to a different canonical title (or a section of one). A naive "look up this exact title in the extracts response" dictionary lookup silently misses these, because the API's response is keyed by the *final* (redirect-target) title, not the *originally requested* one.

**Fix:** the MediaWiki API's `extracts` query, when passed `redirects: 1`, returns explicit `redirects` and `normalized` mapping arrays (`from` → `to`) alongside the page data. Walking these mappings backward reconstructs a lookup table keyed by the *originally requested* titles, so the dictionary lookup succeeds even when a redirect or normalization occurred in between.

### 6.7 Design choice: person names → surname only
For "person" categories (politicians, cricketers, actors, musicians, athletes), only the *last* token of the title is kept as the answer (e.g., "Sachin Tendulkar" → `TENDULKAR`, not both `SACHIN` and `TENDULKAR`). This is a **positional rule, not a word-list rule** — it needs no maintenance as new names are encountered, unlike a blacklist. It also matches a real convention in professional crossword clueing, where public figures are conventionally clued by surname.

---

## 7. Module: `build_word_bank.py` — General English Word Bank

A small, one-time-use script: downloads the `dwyl/english-words` public-domain word list (~370k words) from GitHub, filters to lengths 3–15, and keeps only words with `wordfreq` Zipf frequency ≥ 3.0 (a tunable "an average adult would recognize this" threshold), producing `word_bank.txt` (~6,300 words). This exists as a distinct, rarely-rerun step because it's slow (Zipf lookup for 370k words takes real time) and doesn't need to change often — it's a foundational asset, not daily-pipeline output.

---

## 8. Cross-Cutting Lessons (worth remembering beyond this project)

1. **Isolate algorithmically risky components from data-plumbing components during development.** The grid solver's bugs were all found and fixed against a trivial dummy word list, before any scraped data was involved — this made root-causing dramatically faster than if scraping and solving had been debugged simultaneously.
2. **"A solution exists" and "the solution is good" are different objectives.** Constraint satisfaction gives you feasibility; quality (recognizability, appropriateness, tone) usually needs a second, separate filtering/scoring layer on top (frequency filtering for word banks; popularity filtering for trivia; the same pattern would apply again for clue quality).
3. **When an upstream API has a default ordering you don't want, the bias has to be fixed at the retrieval stage, not downstream.** Truncating a paginated, alphabetically-sorted API response and then trying to "fix" the result with better scoring/filtering doesn't work — the bias is already baked into which items you even have access to.
4. **Recursive/backtracking code that mutates shared state must roll back exactly what it changed on every exit path, not just the "expected" ones.** This is a narrow but high-value thing to specifically audit for.
5. **Before reaching for a hand-maintained list (or, at the other extreme, a heavyweight model) to encode a semantic distinction, check whether an existing structured resource already encodes that exact distinction.** WordNet's instance/type relationship was a much better fit for "proper name vs. generic word" than either word frequency or POS tagging — both plausible-sounding, both empirically wrong for this specific distinction.
6. **Legal/ToS legitimacy of a data source should be checked before technical feasibility, not after.** IMDb and Cricinfo were both technically scrapable but explicitly excluded on ToS grounds; Wikipedia and (for future film data) TMDb were chosen specifically because they offer sanctioned, documented reuse.

---

## 9. Open Items / Not Yet Built

- **Clue generation** (`clue_generator.py`): designed (local Ollama model, per-word prompts including news/trivia snippet context where available, validator to catch answer-leakage into the clue, fallback templates) but not yet implemented/tested as of this document.
- **Merging** `candidates.json` (daily news) + `india_word_bank.txt` (evergreen trivia) + `word_bank.txt` (general filler) into a single pool for the grid solver — not yet wired up.
- **Cricket-specific evergreen data source** — left unresolved; no ToS-compliant free API identified yet, deliberately not scraping Cricinfo.
- **Film-specific popularity data via TMDb** — identified as a good future addition, not yet built.
- **Midi (10x10) and full (15x15) grid sizes** — deferred; only the 5x5 Mini pattern has been built/tested.
- **Website/app frontend, hosting** — entirely deferred, per the original week-1 scope (this document covers only the generation pipeline).

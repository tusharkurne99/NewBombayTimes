# New Bombay Times — Project Log, Week 2
### Handoff to Claude Code, repo reorganization, a live rate-limit bug, word-filter hardening, and an editorial review workflow

**Continuation note:** Picks up after `project_log_week1_part3.md` and the full `Claude-Building an India-focused crossword platform.md` chat transcript (the original chat-based workflow, ending mid-way through fixing Crossword's wall-clock timeout — see `grid_generation_algorithms.md` §"Version 4" for that specific fix, documented separately since it's purely a grid-generation change). This document covers the first Claude Code session on the project: a workflow change (direct repo access instead of copy-pasting files from a chat), a full repo reorganization, a real production bug found on the user's own machine, two real word-filtering gaps found and fixed, and a new editorial-review feature for topical clues.

---

## 1. Workflow change: from chat-pasted files to direct repo access

Every prior session (`project_log_week1*.md`, the chat transcript) worked by generating code in a chat interface, which the user then copy-pasted into local files and ran manually — including running tests, debugging failures, and reporting results back into the chat by hand. This session switched to Claude Code operating directly on the actual project repository: reading real files, running the actual pipeline, and verifying results directly rather than asking the user to run something and paste output back.

**Immediate practical effect:** claims in this log are backed by commands actually run against the real repo (shown as such below), not code reviewed by inspection alone. Where something couldn't be run in the working environment (e.g. no live news feed changes during testing), that's noted explicitly, same standard as prior logs.

---

## 2. Repository reorganization

### 2.1 Spelling mismatches, found by inspection
Two files on disk had names that didn't match what every docstring, comment, and cross-reference in the *rest* of the codebase already called them:
- `scrapper.py` on disk vs. `scraper.py` referenced everywhere else (comments in `grid_generator.py`, `word_filters.py`, etc.)
- `indian_trivia_scrapper.py` on disk vs. `india_trivia_scraper.py` referenced in its own docstring and elsewhere

**More than cosmetic:** `setup_evergreen.sh` called `india_trivia_scraper.py` — a filename that never existed on disk. This script would have failed with "file not found" the moment someone actually ran it fresh; it likely only ever worked because the user had been running the module some other way (e.g. by its real, misspelled name directly). Fixed by renaming the files to the spelling everything else expected, rather than the other way around, and fixing the script's call site.

### 2.2 Flat-directory structure replaced with src/scripts/data/output/docs
Previously every script, word list, scraped-data file, generated puzzle, and doc lived side by side in one directory. Reorganized into:
```
src/       -- 8 pipeline modules + new paths.py
scripts/   -- run_daily.sh, setup_evergreen.sh
data/      -- raw/ (large downloads), wordbanks/, context/ (scraped news/trivia)
output/    -- test_grids/, puzzles/, _legacy/ (pre-multi-size era files)
docs/      -- project logs + the full planning chat transcript
```

**The part that made this safe rather than just tidier:** every pipeline module had ~30 hardcoded relative filenames scattered through it (`"word_bank.txt"`, `"candidates.json"`, etc.), which only worked because everything lived in one flat directory and scripts were always run from inside it. Moving files without fixing this would have silently broken every read/write. Added `src/paths.py` as the single source of truth for every file path, computed relative to the project root (derived from `paths.py`'s own file location, not the caller's current directory) — this is what lets `run_daily.sh`/`setup_evergreen.sh` work correctly regardless of which directory they're invoked from.

**Verified, not assumed:** ran `run_daily.sh` from `/tmp` (a directory with no relationship to the project) after the move — full pipeline (scraper → merge → all 3 grid sizes → clues) completed correctly, writing output to the right places.

---

## 3. A real bug, found on the user's own machine: Wikipedia API rate-limiting

### 3.1 Symptom
Running `setup_evergreen.sh` for real crashed partway through `india_trivia_scraper.py`, mid-way through the "Indian musicians" category, with `requests.exceptions.HTTPError: 429 Client Error: Too Many Requests`.

### 3.2 Root cause
No retry/backoff logic existed anywhere in the module's three Wikipedia API call sites (category-member listing, extracts, pageviews). Large categories make thousands of sequential requests — "Indian cricketers" alone is ~2000 titles, each needing a pageviews lookup — and Wikipedia's API does rate-limit sustained bursts, even with the module's existing small per-request delay (`REQUEST_DELAY = 0.15`). A single 429 crashed the whole script immediately.

**Made worse by an existing design choice:** results are only written to disk at the very end of `main()`, so the crash didn't just lose the one category that hit the limit — it lost every category already scraped before it (Prime Ministers, independence activists, rivers, World Heritage Sites, cuisine, cricketers, film actors — all gone, since none of it had been persisted yet).

### 3.3 Fix
- Added `_get_with_retry()`: retries on HTTP 429/5xx with exponential backoff (2s, 4s, 8s, 16s, 32s), honoring the API's `Retry-After` header when the server sends one. Applied to all three call sites.
- **Found a second, more subtle bug while fixing the first:** `get_pageviews()` was catching 429 as a generic `requests.RequestException` and silently returning `0` views for that title — not a crash, but a silent *data-quality* bug. This corrupts the popularity ranking without any visible symptom: rate-limited titles (systematically, whichever ones happen to be requested during a rate-limit window — often clustered toward the end of a long category, since bursts compound over time) would rank as "unpopular" instead of being retried, biasing which titles make it into the top-K by an artifact of request timing rather than real popularity. Fixed the same way as the other call sites, with one care taken: the retry helper deliberately does **not** call `raise_for_status()` on its final returned response, because `get_pageviews()` needs to see a plain 404 (meaning "no pageview data for this title," a normal/expected case, not an error) without an exception being thrown — an early version of the fix got this wrong and would have broken the existing 404-handling.
- Wrapped per-category extract-fetching in its own try/except, so a persistent failure fetching *one* category's snippets no longer discards the whole run's accumulated data from every other category (that entry just ends up with an empty snippet instead of being lost entirely).

### 3.4 Verified against the live API, not just in theory
Re-running the full scraper after the fix hit **five real 429s** during the "Indian cricketers" category — the same failure class that crashed the original run — backed off correctly each time (observed real `Retry-After` values of 12-19 seconds), and completed the entire run successfully: 150 unique entries, 0 missing snippets.

### 3.5 Lesson
A batch job that makes thousands of sequential calls to a third-party API needs retry/backoff as a baseline requirement, not an afterthought — and a script that only persists results at the very end turns any single unhandled failure into a total loss of work, not just a partial one. Both problems compound: the second makes the first much more costly when it eventually happens (and at this request volume, it reliably does happen).

---

## 4. Word-filtering gaps found and fixed

Prompted by the user's explicit framing for this phase of the project: since the review workflow (see §5) gives editorial control over **clues** but not **words** (rejecting a word would mean re-running grid generation, not realistic as a daily habit), word-level filtering is the only real safety net for what appears in the grid at all — it has to be airtight, not "mostly right."

### 4.1 A genuine filter bug, found by direct testing: `SSSS` and `WSWS`
**Symptom:** real generated Midi grids contained `SSSS` and `WSWS` as filler answers — meaningless letter strings, not real words, despite `is_safe_context_free_word()` (the WordNet-based hallucination-risk filter built in Week 1 specifically to catch exactly this class of junk) supposedly covering this case.

**Root cause, found by testing the filter function directly rather than assuming it was broken generally:** NLTK's `wn.synsets()` applies morphological stripping (assuming a trailing "s" means a plural) *before* matching against WordNet. `"ssss"` strips to `"sss"`, which coincidentally collides with a real, unrelated WordNet lemma: `SSS` (Selective Service System, an abbreviation entry). `"wsws"` strips to `"wsw"`, colliding with `WSW` (west-southwest). Both matches are real WordNet entries — the existing "has a generic sense" check correctly found *something*, it just wasn't a match for the actual word being validated, only for a shorter string that word happened to reduce to.

**Fix:** a word failing the vowel test (no `A E I O U Y` at all) *and* falling below the project's existing "average adult would recognize this" recognizability threshold (`zipf >= 3.0`, already established in `build_word_bank.py`) is rejected outright, before the WordNet check runs at all. Calibration mattered here: a pure "no vowel" rule would have wrongly rejected legitimate common abbreviations (`DVD` zipf 4.25, `TV` zipf 5.2, `PHD` zipf 4.07) that also have no vowel — the combination with the frequency floor is what cleanly separates those from `SSSS`/`WSWS` (zipf 1.4–1.9) without a hand-maintained exception list in either direction. Verified directly: `SSSS`/`WSWS` now correctly rejected; `DVD`/`TV`/`PHD` and other real low-frequency-but-legitimate words (`BULGUR`, `PARRS`, `MISSALS`) still correctly kept.

### 4.2 Sensitive-word list: replaced a hand-inspected 8-word list with a vetted ~275-word source
The original `SENSITIVE_WORDS` set (`ISIS`, `ASS`, `NAZI`, `NAZIS`, `KKK`, `RAPE`, `RAPED`, `RAPIST`) was explicitly documented as "found by inspection of real generated puzzles, not exhaustively researched." Given this project's move toward the words being effectively locked in once generated (§ above), an inspection-driven list is the wrong shape for this problem — profanity/slurs are open-ended, unlike the small closed categories (`INDIAN_ADMIN_SUFFIXES`, `ALWAYS_IN_NEWS_PENALTY`) this project has otherwise deliberately preferred over hand-maintained lists.

Replaced the bulk of the list with a maintained public source (`LDNOOBW/List-of-Dirty-Naughty-Obscene-and-Otherwise-Bad-Words`), filtered down to single alphabetic tokens of length 3–15 (the only shape that can appear as a crossword answer — the source list's many multi-word phrases are structurally irrelevant here). ~274 words. The original historical/political terms (`ISIS`, `NAZI`, `NAZIS`, `KKK`) were kept as a separate addition, since they aren't profanity and the public list doesn't cover them — same reasoning as Week 1's original addition of `ISIS`/`NAZI`/`KKK`.

**Deliberate tradeoff, stated explicitly rather than left implicit:** this errs toward over-blocking. Several entries (`ANAL`, `ANUS`, `SEX`, `TIT`) have legitimate anatomical/biological meanings and have appeared as real answers in mainstream published crosswords. For a general-audience daily puzzle with no per-word editorial override in the ordinary workflow, the cost of never using them is negligible; the cost of one appearing unreviewed is not. Documented in code as: if a specific word is wanted back, remove it from the list deliberately — don't route around the list.

### 4.3 A real gap: sensitive-word filtering wasn't applied to topical (news/trivia) words at all
**Found by reading the merge pipeline, not by a failure:** `is_sensitive_word()` was applied to `word_bank.txt` (at build time, in `build_word_bank.py`) and to `crossword_quality_words.txt` (at merge time, in `merge_sources.py`). It was **never applied** to words coming from `candidates.json` (daily news) or `india_trivia.json` (Wikipedia trivia) — these enter the topical/priority word pool directly, on the strength of having real context attached, completely bypassing both filtered word banks. Topicality was never actually a signal for appropriateness, but the filtering architecture had implicitly treated it as one.

**Fix:** `is_sensitive_word()` now applied in `merge_sources.py`'s `load_news_candidates()`/`load_trivia()`, and in `india_trivia_scraper.py` itself at the point where Wikipedia titles are converted into candidate answer words (`title_to_words()`'s call site) — belt-and-suspenders, since a word could otherwise enter through either path.

---

## 5. New feature: editorial review workflow for topical clues

### 5.1 The problem this solves
The user's plan for running this as a live product: manually monitor all three daily puzzles, but with no intention of rejecting a *word* (that would mean re-running grid generation, not realistic as a daily habit) — only clues. Up to this point, `review_recommended: true` clues (Week 1 Part 3's response to the PYARELAL/GREG/CARR hallucination findings) gave exactly one clue per word with no alternative if it turned out to be wrong or in poor taste — the only recourse was writing a replacement completely by hand with no starting point.

### 5.2 What changed, in `clue_generator.py`
- **Three independently-generated clue candidates, not one, for every `review_recommended` word.** Each of the three uses a deliberately different "angle" instruction (`direct` — straightforward factual; `concise` — shortest possible headline-style; `oblique` — wordplay/pun if one naturally fits, marked with a trailing "?" per crossword convention, else a more indirect factual angle) rather than just re-sampling the same prompt at a different temperature — this is what makes the three options genuinely distinct choices instead of near-duplicates of each other. If two angles happen to produce identical text anyway (observed as a real, if occasional, failure mode of small local models ignoring an instruction), the duplicate gets one plain-prompt retry rather than showing the reviewer two copies of the same clue.
- **Generic (non-topical) filler words are unaffected** — still one clue, one model call. The 3x cost is deliberately not paid where there's no snippet to ground alternate angles in and no reviewing benefit (word-level filtering, not clue review, is the safety net for these — see §4).
- **A second, higher-quality model (`llama3.1:8b`) used specifically for the topical/reviewed words**, while the bulk of generic filler continues using the faster `llama3.2:3b`. Justified by volume: a full Crossword has roughly 60-90 total answers but typically well under 10 flagged for review, so the slower model's cost is paid only where clue quality is actually being read closely by a human.
- **Structured provenance (`context_meta`) surfaced per topical clue, not just the source snippet the LLM saw:** for news words, the originating outlet, article link, how many articles/sources mentioned it, and when the scrape ran; for trivia words, the Wikipedia article title, a direct URL, topic category, and 3-month pageview count. This required extending `merge_sources.py`'s `load_news_candidates()`/`load_trivia()` to carry these fields through — they existed in the raw `candidates.json`/`india_trivia.json` files already but were previously discarded down to just a snippet + score during merging. The point: a reviewer choosing between three clue options, or writing a fourth by hand, can now check *where a fact came from and how well-attested it is*, not just read an isolated sentence with no way to verify it.

### 5.3 Improved clue-writing prompt
The original prompt ("write one short, clever clue, max N words") produced clues that often read as reworded dictionary definitions or lightly-compressed copies of the source snippet, rather than something that reads like an actual constructed crossword clue. Added an explicit style-rules block, applied to every prompt (not just the new multi-option ones), encoding conventions a small local model doesn't reliably apply on its own without being told:
1. Match the clue's grammatical form to the answer's part of speech and tense.
2. Write a fragment, not a full sentence (standard crossword convention).
3. Never use the answer word, a plural/possessive of it, or an obvious derivative, anywhere in the clue.
4. Don't just reword/compress the source context into a sentence — write an actual composed clue referencing the fact.
5. Avoid clues so generic they could fit many answers when a more specific angle is available.
6. Keep tone consistent with a daily newspaper crossword.

**Verified for real, not just read over:** ran the full multi-option workflow end to end for Mini and Midi (Crossword confirmed working by the user's own manual run). Real output, e.g. for `TAJ` (trivia-sourced): *direct* — "Mughal emperor's famous white marble tribute"; *concise* — "Mughal emperor's final resting place in Agra"; *oblique* — "Shah Jahan's poignant tribute to his beloved?" — three genuinely different, individually coherent, checkable-against-source clues, not three trivial rewordings of each other.

### 5.4 Known cost of this change, disclosed rather than hidden
Clue generation is now meaningfully slower for review-required words specifically (3 calls to the larger model instead of 1 call to the smaller one, per topical word). Measured: Midi (3 topical words, 9 calls total) took ~81 seconds for clue generation alone, up from single-digit seconds before. Crossword (more topical words) takes proportionally longer. Judged an acceptable tradeoff for a once-daily batch job given the actual editorial goal, but worth knowing this is a real, non-trivial runtime cost, not free.

---

## 6. Cross-Cutting Lessons (new, in addition to Parts 1-3)

1. **A workflow change (direct repo access vs. copy-pasted chat output) changes what "verified" means, not just convenience.** Every claim in this document is backed by a command actually run against the real repository — this caught real problems (the setup_evergreen.sh broken filename, the live rate-limit crash, the SSSS/WSWS bug) that inspection-only review across a chat transcript had not surfaced.
2. **A filter that correctly matches "does WordNet know this word" is not the same as "is this actually the word being validated."** Morphological normalization (stemming/pluralization-stripping) inside a lookup can silently validate against a *different* word than the one queried. Worth specifically checking for whenever a lexical-resource lookup applies any normalization step before matching.
3. **When a design gives a human editorial control over one axis (clues) but not another (words), filtering rigor on the uncontrolled axis has to rise to match — it's no longer "one layer of several," it's the only layer.** This directly motivated both the word-filter hardening (§4) and the decision to spend 3x LLM calls specifically where a human reviews the result (§5), and not on filler words where no one will look closely regardless.
4. **A hand-maintained list that was honestly labeled "not exhaustive" when created should be revisited once the stakes around it change, not left as-is because it hasn't failed yet.** The original 8-word sensitive-word list wasn't wrong when written; it stopped being sufficient once the project's editorial model shifted to trusting word-level filtering as the primary safety net.
5. **Persist incremental progress in any batch job that makes many sequential calls to something outside your control.** Writing results only at the end turns a single transient failure (a 429 partway through) into a total loss, compounding the cost of a problem that retry logic alone doesn't fully eliminate (a sufficiently persistent outage still ends the run — the persistence question is about what you keep from the run that already happened).

---

## 7. Open Items (updated from Part 3 §6)

Resolved in this phase:
- ~~setup_evergreen.sh calling a filename that doesn't exist~~ — fixed (renamed files to match).
- ~~No retry/backoff on Wikipedia API calls~~ — fixed, verified against 5 live 429s.
- ~~SSSS/WSWS-style junk fill~~ — root cause found and fixed (vowel + frequency check), verified against both the junk and legitimate no-vowel words.
- ~~Sensitive-word list was a short, explicitly-non-exhaustive hand list~~ — replaced with a ~275-word vetted public source.
- ~~Sensitive-word filtering not applied to topical (news/trivia) words~~ — fixed at both entry points.
- ~~Single, non-reviewable clue per topical word with no alternative~~ — 3-option review workflow with provenance metadata, shipped.

Still open, carried forward:
- Crosswordese/junk-fill beyond the SSSS/WSWS class (Part 3 §3.1) — narrower now given §4.1's fix, not re-audited against a fresh puzzle in this session.
- Cricket-specific evergreen data source, TMDb integration for film popularity (Part 1/3) — unchanged, still deferred.
- Website/app frontend, hosting — untouched since Part 1's original scope.
- The 50/50 India/international balance mechanism and expanded GK-quiz-site sourcing (Part 3 §4) — still just a discussion, not built.
- No entity-type metadata (e.g. "this topical word names a real person") yet plumbed through from `scraper.py`/`india_trivia_scraper.py` — `review_recommended` still uses "any topical word" as a blanket, safe-by-default proxy rather than precisely targeting the person/institution-fabrication risk that motivated it.

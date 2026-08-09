# New Bombay Times — Project Log, Part 3
### Week 1/2: Midi & Crossword Sizes, Real-Output Quality Review, Content-Sourcing Brainstorm

**Continuation note:** Picks up exactly where `project_log_week1_part2.md` left off. That document ends with Mini (5x5) fully working and a prioritized open-items list. This document covers: extending generation to Midi (9x9) and Crossword (15x15), a full technical investigation into why that was hard (summarized here; the complete blow-by-blow algorithm history, including every rejected approach, is in the separate companion document `grid_generation_algorithms.md` — read that alongside this one, they're deliberately split so the algorithm deep-dive doesn't bloat the project narrative), CLI/orchestration wiring for all three sizes, a real-output quality review that surfaced a serious new class of problem, and a content-sourcing brainstorm session (not yet implemented) for the next phase.

---

## 1. Extending to Midi (9x9) and Crossword (15x15)

### 1.1 Why this wasn't just "run the same code at a bigger size"
The existing 5x5 solver (single-level forward-checking, inherited from Part 2) timed out completely at 9x9, even given several minutes — which is a perfectly reasonable amount of time for a once-daily batch job, so this wasn't an impatience problem, it was a real scaling failure. Investigating this became the single largest piece of work in this phase. **Full technical detail — every algorithm version tried, profiled, and either kept or rejected, with flow diagrams and real numbers — is in `grid_generation_algorithms.md`.** Summary of the outcome:

- Rewrote the solver core from single-level forward-checking to full cascading AC-3 arc consistency.
- Along the way, tried and **empirically rejected** a position-index optimization that looked like it should help and measurably didn't (profiled, not assumed).
- Found and fixed a real bug in node-budget accounting (a budget meant to bound search-per-attempt wasn't counting most of the actual work).
- Landed on a working core (AC-3 + incrementally-maintained letter-position counts + plain domain scans) that is correct and reasonably fast, but **still wasn't sufficient on its own** to make Midi/Crossword practical.

### 1.2 The two things that actually made Midi/Crossword work
Neither of these is an algorithm change — both are about the *problem instance itself*, found by direct experimentation:

**Black-square density.** Initial patterns used ~15-17% black squares (extrapolated from what felt visually "authentic" for a Mini). Tested directly: at 15x15/16% density, generation didn't complete in 45 seconds even with a good word list. At 20% density (still within real NYT daily crosswords' typical 16-20% range), the same setup solved in under a minute. Density controls average word length, which controls how tightly every slot is constrained — this turned out to dominate solve time far more than any algorithmic tuning.

**Word list quality.** A generic frequency-filtered English dictionary (`word_bank.txt`, ~23k words after the Part 2 hallucination-risk filtering) has poor letter-pattern diversity for *interlocking* — being a valid, common word doesn't mean it shares many letter positions with other valid, common words. Found and downloaded a real, freely-shared, community-maintained **scored** crossword word list (`christophsjones/crossword-wordlist` on GitHub, ~170k entries, MIT-spirited license, built from NYT/WSJ/WaPo/Peter Broda's list/Peter Norvig's frequency data, each word scored 1-50 for crossword quality). Swapping to this list, filtered to score ≥ 40 (~45k words): **Midi went from "doesn't solve" to 0.3-0.6 seconds. Crossword went from "doesn't solve in 45s" to ~2-40 seconds** (with some tail variance, see §1.3).

New setup script: `build_crossword_quality_wordlist.py` — downloads and filters this list, run occasionally (not daily) via `setup_evergreen.sh`.

### 1.3 Flakiness found and fixed: multi-pattern retry
Even with density + curated word list, `generate_midi()`/`generate_crossword()` were still occasionally slow/stuck. Root cause: they generated *one* random pattern per call and only retried word-orderings within it. Some specific patterns — despite passing the same structural validity checks as every other pattern — are genuinely harder to fill. Fixed by trying multiple *different* random patterns (5 for Midi, 3 for Crossword) before giving up, not just multiple orderings of one. Verified: Midi went from flaky to 6/6 successful runs, all under 5 seconds. Crossword: 4/5 trials under 10 seconds, one outlier took much longer — better, not fully eliminated. This is the same underlying CSP lesson as the node-budget mechanism (bad luck vs. fresh restart), just applied one level up (pattern choice, not word choice).

---

## 2. Pipeline wiring for three sizes

- `grid_generator.py` now takes a CLI argument (`mini`/`midi`/`crossword`), loads the correct word pool (`merged_word_bank.txt` for Mini, `midi_crossword_word_bank.txt` for Midi/Crossword), and writes `test_grid_<size>.json`.
- `clue_generator.py` takes the same argument, reads the matching grid file, writes `puzzle_<date>_<size>.json` (added a `puzzle_type` field to the output schema).
- `merge_sources.py` now builds **two** pools instead of one: the Mini pool (as before) and a Midi/Crossword pool (curated quality words ≥ score 40, plus all topical news/trivia words regardless of score). Also now computes an `interlock_score` for every topical word (its score in the curated list, or 0 if absent — meaning "untested for interlock difficulty," not "bad").
- `run_daily.sh` runs all three sizes end to end. `setup_evergreen.sh` runs the new curated-wordlist download alongside the existing occasional-refresh steps.

All of the above verified working end-to-end in the sandbox (Mini/Midi fast, Crossword ~50s, real varied output each run). Not verified: `clue_generator.py`'s actual runtime behavior, since this sandbox has no Ollama — only its file-naming/parsing logic was checked.

---

## 3. Real-output quality review: a new, more serious class of problem

The user ran the full pipeline for real and shared both the Midi and Crossword puzzle JSON output. Reviewing it surfaced two distinct problems, of very different severity.

### 3.1 Crosswordese / low-quality junk fill, even from the curated list
Both puzzles contained answers that are technically "in the word list" but not real, recognizable words to an ordinary solver: `DQS`, `SDS`, `ONEI`, `SSSS` (Midi); `PCTS`, `ATRAS`, `WOT`, `ARETOO`, `EAP`, `OPE`, `USH` (Crossword). These likely scored decently in the source list because professional constructors sometimes use obscure abbreviations/crosswordese that experienced solvers recognize but casual ones don't — appropriate for the source list's intended audience, not necessarily for this project's. **Not yet fixed** — likely fix is raising the minimum score threshold, or building a secondary "is this recognizable to an average solver" filter (candidate approach: cross-check against WordNet or `wordfreq`, similar to techniques already used for `word_bank.txt`).

### 3.2 LLM hallucination escalated in severity — this is the important finding
Several clues were simply wrong in the already-known way (factual errors on generic words — e.g. `MENORCA` clued as "off Sardinia" when it's a Balearic island off Spain; `EUDORA` clued with book titles by two different, unrelated authors; `TARTAR` described as a salad ingredient). This matches the GREG/CARR pattern from Part 2 — expected, still needs the review workflow.

**But two clues crossed into a more serious category:**
- `PYARELAL` → *"Brothers jailed for India's infamous Delhi gang rape case."* **Verified via web search: false, and seriously so.** Pyarelal Ramprasad Sharma is a real, celebrated Bollywood music composer (half of the Laxmikant–Pyarelal duo, 750+ film scores across a 35-year career). The model invented a connection between this real, identifiable person's name and a real, horrific crime, with no basis at all.
- `IAF` → *"Indian air force officer caught in a honey trap."* A specific, serious, unverifiable claim about a real institution, same shape as the above.

**Why this is categorically different from "the clue is wrong":** earlier hallucinations (GREG, CARR) were embarrassing but harmless — inventing a fake definition for an obscure word. Fabricating a criminal accusation and attaching it to a real, named, identifiable person is a different kind of failure — reputational and potentially legally risky if published, independent of how "good" the crossword is otherwise. This happened even though the model, in principle, had real context available for both words (both may have been treated as topical/generic without verified grounding actually being used correctly).

**Status:** not fixed. This is the clearest evidence yet that the deferred "store clue source snippet + require human review before publishing" workflow (first flagged in Part 2 after GREG/CARR) is not an optional nice-to-have — it's a precondition for treating this pipeline's output as safe to share with anyone, even informally. Recommended (pending user decision, see §5): treat any clue about a real named person or institution as requiring mandatory human verification before use, at least until a better automated grounding-check exists.

---

## 4. Content-sourcing brainstorm (discussion only, nothing implemented yet)

Prompted by the user's feedback that Indian-context volume/variety still feels thin. Covered as a discussion, deliberately not turned into code yet, pending the user's direction on several judgment calls.

### 4.1 Daily news scraping expansion
Currently 5 Indian + 1 foreign (BBC) RSS feed, single feed per outlet. Discussed: adding more Indian outlets; pulling multiple *category-specific* feeds per outlet (sports/business/entertainment) rather than one general feed, both for volume and for topic control relevant to §4.4; reconsidering whether the foreign feed's relative weight should shrink if the goal is India-majority content.

### 4.2 India trivia beyond Wikipedia
User found `thepremiaacademy.com`'s GK quiz blog. Searched and found several more of the same shape: `gktoday.in`, `careerpower.in`, `gkduniya.com`, `gkgigs.com`, `generalknowledgequestion.in` — Indian competitive-exam-prep blogs with static Q&A lists. **This is a structurally better data shape than Wikipedia snippets**: a Q&A pair is essentially a pre-written clue+answer, rather than a snippet an LLM has to rephrase (and, per §3.2, sometimes rephrases into something false). Two open caveats, both flagged as needing a decision rather than resolved:
- **Reliability**: these are SEO/exam-prep content, not fact-checked to the standard Wikipedia or a newspaper is held to. Recommended: cross-verify answers against Wikipedia/WordNet before trusting them, rather than ingesting directly.
- **Scraping legitimacy**: unlike Wikipedia (explicit sanctioned API) or IMDb/Cricinfo (explicitly prohibited, hence excluded in Part 1), these sites are an unclear middle ground — no stated policy either way. Recommended: check `robots.txt` per site individually, keep scraping frequency/volume modest, rather than treating "no explicit prohibition" as equivalent to "sanctioned."

### 4.3 Interlock/compatibility scoring for locally-sourced (Indian) words
The downloaded curated list can only ever score words it already contains — essentially never true Indian-specific trivia/news terms, which default to `interlock_score: 0` (meaning "untested," not "bad," but currently indistinguishable from "bad" downstream). Three options discussed, not yet chosen between:
- **Heuristic scoring**: estimate interlockability from a word's own letter-pattern statistics (bigram/trigram commonality vs. the general dictionary) — computable for any word including novel ones, but an approximation.
- **Self-learning scoring**: track which Indian-specific words actually succeed vs. fail to place in real generated grids over time, building a locally-grounded score from observed outcomes. Honest, but slow to accumulate useful signal.
- **Combine both**: heuristic as a cold-start estimate, refined by real placement history as it accumulates. Likely the right long-term answer, most engineering effort.

### 4.4 Explicit 50% India / 50% International balance
Currently there's no enforced ratio — seeding just grabs a few topical words regardless of origin mix. Discussed mechanism: tag every topical word by origin (India-trivia / Indian-news vs. foreign-news, derivable from which RSS sources contributed to a news candidate), then have `seed_priority_words()` deliberately draw from both buckets toward a target ratio instead of pooling everything. Open question raised, not resolved: what should "50/50" actually be measured over (word count in grid vs. clue count vs. per-size — Mini has very few topical slots to split at all)?

### 4.5 Explicit human-intervention checkpoints identified in this discussion
1. Whether the real-named-person/institution review rule (§3.2) becomes a hard blocking rule.
2. Which new sources actually get greenlit for scraping (research can be done, but risk tolerance is a judgment call, as with the earlier IMDb/Cricinfo exclusion).
3. How much to trust exam-prep-site facts vs. requiring cross-verification.
4. What "50/50" should be measured over.

---

## 5. Cross-Cutting Lessons (new, in addition to Parts 1 & 2)

1. **Not all wrong output is equally bad — severity category matters, not just "is it correct."** A hallucinated definition (CARR) and a hallucinated crime accusation about a real person (PYARELAL) are both "the LLM was wrong," but they don't call for the same urgency of response. Recognizing when a bug has crossed from "quality issue" to "safety issue" should change prioritization immediately, not just get queued alongside everything else.
2. **When a fix doesn't fully solve a problem, isolate whether the remaining gap is algorithmic or is actually about the problem instance.** The solver rewrite (AC-3) was necessary but not sufficient for Midi/Crossword; the actual unlocks (density, word-list quality) weren't algorithm changes at all. Continuing to tune the algorithm after that point would have been effort in the wrong place.
3. **A data source with a better native shape can matter more than a smarter processing step.** GK-quiz Q&A pairs are structurally closer to "clue+answer" than a Wikipedia snippet is — this is a data-sourcing decision, not something prompt engineering on the snippet-to-clue step could fully substitute for.
4. **Legitimacy and reliability are two separate axes when evaluating a new data source**, and neither should be waved through by default: Wikipedia is both sanctioned and reliable; the GK-quiz sites found here are (probably) legally fine but not necessarily reliable; this needs two separate checks, not one.

---

## 6. Where to Start Next Time

In priority order, reflecting the severity finding in §3.2:

1. **Decide and then build the clue-review/grounding workflow.** This is no longer "worth doing eventually" — §3.2 is direct evidence it's needed before this pipeline's output should be treated as safe to share, even informally. Concretely: store the source snippet alongside every generated clue in the output JSON (currently discarded after use), and decide on a review rule — at minimum, mandatory human check for any clue referencing a real named person or institution.
2. **Fix the crosswordese/junk-fill issue** (§3.1) — likely a minimum-score-threshold increase or a secondary recognizability filter on top of the curated list, same general technique already used for `word_bank.txt`.
3. **Resolve the open judgment calls from §4** before building anything new: which GK-quiz sites are greenlit, how their facts get verified, what "50/50" is measured over. These are decisions, not engineering — the actual scraper/scoring code for whichever sources get approved is comparatively quick once the decisions are made.
4. Only after 1-3: build the expanded news scraping, the GK-quiz-site trivia source, the interlock-scoring approach for Indian-specific words, and the 50/50 balancing mechanism in `seed_priority_words()`.

Also still open from Part 2, unchanged: the `MAHAL`-style suffix fix (small, low-effort, just needs doing), a content-sensitivity exclusion list (ISIS/ASS-type words), TMDb integration for film data, cricket-specific data source, and the entire website/app/hosting layer (untouched since Part 1's original scope).

# New Bombay Times — Project Log, Part 2
### Week 1 continued: Hardening the Pipeline, Local LLM Reliability, Orchestration, Grid Variety

**Continuation note:** This picks up exactly where `project_log_week1.md` left off (end of §6.5, the WordNet-based generic-word filtering work). That document remains the reference for the core architecture, the CSP/backtracking algorithm, and the reasoning behind WordNet-based filtering. This document covers everything built and debugged after that point: extending WordNet filtering with an important caveat, real evidence of local-LLM hallucination and what that does and doesn't fix, a recurring Indian-language suffix-fragment problem, a pipeline-ordering bug and its structural fix, and finally grid pattern variety.

---

## 1. The `is_generic_word` / `PERSON` entity caveat (scraper.py)

**Question raised:** should the WordNet-based `is_generic_word()` filter (built for `india_trivia_scraper.py`, see Part 1 §6.5) also be applied to `scraper.py`'s news-entity splitting?

**Investigation:** tested directly against real candidate words that had appeared in actual scraper output. Result: WordNet correctly flags real contamination in `ORG`-type entities (`BANK`, `RESERVE`, `MINISTRY`, `COMMITTEE`, `PARTY`, `COUNCIL`, `ASSEMBLY`, `PARLIAMENT` — all correctly identified as generic institutional words, e.g. from "Reserve Bank of India" splitting).

**But:** testing `TRUMP` specifically revealed a serious false-positive risk. WordNet only has an entry for "trump" as a card-game term (`trump.n.01`: "a playing card in the suit that has been declared trumps") — it has **zero** entries for the person, because WordNet is a static, dated lexical resource with weak coverage of contemporary public figures. Applying `is_generic_word()` uniformly would have silently deleted one of the most newsworthy names from the daily pipeline.

**Fix:** `is_generic_word()` filtering is applied only to non-`PERSON` entity types (`ORG`, `FAC`, `EVENT`, etc.). `PERSON` entities keep every name token unfiltered, on the reasoning that WordNet's proper-noun coverage is too unreliable to trust for exactly the kind of entity (contemporary public figures) this scraper most needs to keep.

**Lesson:** a filtering rule validated on one entity type doesn't automatically transfer to another. The right move was testing against a real, high-value example (a name the scraper *must* keep) before generalizing a fix, rather than assuming a working solution for one problem class solves an adjacent one.

**Refactor:** the `is_generic_word()` function itself was moved into a new shared module, `word_filters.py`, imported by both `scraper.py` and `india_trivia_scraper.py`, removing what had become a duplicated inline copy.

---

## 2. Local-LLM hallucination: two confirmed real cases

This is the most important finding of this phase, because it demonstrates a limitation that **cannot be fixed by better upstream filtering** — it's a property of the clue-generation model itself.

### 2.1 Case 1 — PAINE / KYRIE (fixable: grounding problem)

**Symptom:** `clue_generator.py` produced a nonsensical clue for `PAINE` ("French delicacy often served at Christmas") and an incoherent one for `KYRIE` ("Greek priest's title, a nod to an iconic soprano").

**Root cause, confirmed via direct WordNet lookup:**
- `PAINE` has exactly two WordNet senses, both `instance_hypernym` relations to *Thomas Paine specifically* — no generic common-noun meaning of "paine" exists at all. The word had passed the frequency filter (`wordfreq` zipf 3.17) because zipf frequency reflects how often *any* sense of a word-form appears in text, including a historical figure's surname — it doesn't distinguish "common because it's a real dictionary word" from "common because a name shows up in text."
- `KYRIE` has **zero** WordNet entries whatsoever (it's a Greek liturgical term / also an NBA player's first name; WordNet's English vocabulary doesn't include it).

Given no real definition and no snippet context (`word_bank.txt` filler words carry no news/trivia context by design), the local model had literally nothing to ground a clue in, and confabulated one.

**Fix:** a new function, `is_safe_context_free_word(word, zipf_score)`, added to `word_filters.py` and wired into `build_word_bank.py`. Logic, calibrated against both the failures above and real successes that needed to survive (`EGYPT`, `INDIA`, `DELHI`, `AFRICA`, `SHAKESPEARE`):
- Zero WordNet synsets at all → **reject** (no dictionary grounding whatsoever, e.g. KYRIE).
- Every noun sense is an `instance_hypernym` (i.e. the word only names one specific thing, like PAINE = only Thomas Paine) → reject **unless** the word's zipf frequency is ≥ 3.8, on the reasoning that a word crossing that frequency threshold despite being instance-only is more likely something the LLM plausibly has broad general knowledge of (a famous country, a very famous historical figure) rather than an obscure one it will invent facts about.
- Otherwise (the word has at least one genuine generic/common-noun sense) → keep; it's a real definable word.

Verified: rebuilding `word_bank.txt` with this filter dropped ~2,246 words out of ~25,000 that passed the frequency filter alone, while correctly retaining EGYPT/INDIA/DELHI/AFRICA/SHAKESPEARE and correctly dropping PAINE/KYRIE. A follow-up puzzle generation confirmed both problem words were gone.

### 2.2 Case 2 — GREG / CARR (NOT fixable by filtering: a model reliability limitation)

**Symptom, GREG:** in a later run, the generic filler word `GREG` got the clue "California governor's initial to sign off on proposals." **Verified via web search: no California governor named Greg has ever existed** (current: Gavin Newsom; historical list includes Brown, Davis, Schwarzenegger, Deukmejian, Wilson, Reagan — no Greg, ever). This is a confident, fully fabricated claim.

**Symptom, CARR:** clue "Transportation company's abbreviation often seen on trucks." **Verified via web search against real trucking-industry abbreviation lists** (LTL, MVR, OO, OOS, OTR, RGN, BOL, CDL, CMV, CPM, CSA, etc.) — CARR appears on none of them. Checking WordNet directly: `CARR` has **zero synsets** — meaning it should already have been rejected by the exact filter built for the PAINE/KYRIE case (§2.1).

**Why this second case is different and more important than the first:** GREG occurred on a word marked `topical: true`, meaning it should have had real snippet context available — yet the model produced a fabricated claim anyway rather than using (or admitting it lacked) real grounding. This demonstrates that **even correct input context does not guarantee a correct clue** from a small local model — fluent, confident, wrong output is possible regardless of what's fed in. No amount of upstream word-list curation addresses this, because the failure isn't "the word had no definition" (the PAINE/KYRIE class of bug) — it's "the model ignored or misused whatever grounding it had."

**Diagnosis of the CARR recurrence (a process bug, not a new filtering bug):** since `is_safe_context_free_word()` demonstrably rejects `CARR` when tested directly (confirmed by direct function call), its appearance in a real puzzle traced back to a **pipeline-ordering issue**, covered in full in §3 below — not a flaw in the filter itself.

**Status: unresolved by design, not by omission.** The intended fix — storing the source snippet alongside each generated clue in the output JSON, enabling a human review pass before any puzzle is considered final — was identified as the correct next step but explicitly deferred (the user chose to prioritize other fixes first). This is the single most important open item carried into future work: **no puzzle produced by this pipeline should be treated as ready-to-publish without a human skimming it first**, and the tooling to make that fast (surfacing source snippets next to clues) doesn't exist yet.

---

## 3. Pipeline-ordering bug: stale `merged_word_bank.txt`

**Symptom:** `CARR` appeared in a puzzle despite `word_bank.txt` having been correctly rebuilt (verified) with the fix from §2.1, which independently verified would reject it.

**Root cause:** `build_word_bank.py` only writes `word_bank.txt`. The actual pool `grid_generator.py` reads from is `merged_word_bank.txt`, written by `merge_sources.py`. `grid_generator.py`'s file-loading logic prefers `merged_word_bank.txt` *if the file exists at all*, with no staleness check. The user had run `build_word_bank.py` and then gone straight to `grid_generator.py`, skipping `merge_sources.py` entirely — so the merged pool on disk was still the one generated before the fix, silently containing the old, unfiltered CARR entry.

**Diagnosis process, worth noting:** rather than assuming the filter itself was broken, the fix was verified in isolation first (direct function call confirmed correct rejection) before looking for an alternative explanation. This ordering — verify the specific piece under suspicion before broadening the investigation — avoided a wasted detour into "fixing" already-correct filter logic.

**Fix:** two shell scripts, `run_daily.sh` and `setup_evergreen.sh`, replacing manual multi-step invocation entirely.
- `run_daily.sh`: `scraper.py` → `merge_sources.py` → `grid_generator.py` → `clue_generator.py`. The actual daily production pipeline.
- `setup_evergreen.sh`: `build_word_bank.py` → `india_trivia_scraper.py`. Explicitly **not** part of the daily pipeline — these are slow, and their outputs (general word frequency data, Wikipedia trivia/popularity) don't meaningfully change day to day. Bundling them into a daily script would be both wasteful and would hammer Wikipedia's API for no benefit.

Both scripts use `set -e` (bash: exit immediately on any command failure) — this is the structural fix, not just the reordering. It makes the exact failure mode that caused this bug (a step silently being skipped or failing without stopping the pipeline) impossible: if any stage fails, nothing downstream runs against stale input. `run_daily.sh` additionally checks Ollama is reachable *before* running the other three stages, so a missing `ollama serve` produces one clear error instead of a confusing late failure.

**Lesson:** a correct fix to one file is not the same as a correct fix to the *pipeline* — multi-stage pipelines with file-based handoffs between stages need either (a) enforced ordering via orchestration, or (b) staleness detection (e.g. checking source-file modification times), or both. Here, (a) was the simpler and sufficient fix given the pipeline's actual shape (linear, no branching).

---

## 4. Recurring problem: Indian-language compound-name fragments (NADU, MAHAL)

**First occurrence — NADU:** `india_trivia_scraper.py`'s title-splitting logic (Part 1 §6.5) strips trailing tokens identified as generic by `is_generic_word()`. For "Tamil Nadu," the last token "Nadu" is a Tamil word meaning "land/country" — not an English word at all, so WordNet has zero knowledge of it, and `is_generic_word()` (which treats "unknown to WordNet" as "likely a proper noun, keep") let it straight through. Result: `NADU` appeared as a standalone crossword answer, with a clue describing the full "Tamil Nadu" concept but an answer that's meaningless in isolation to an English speaker — and without following the real crossword convention of phrasing such fragment answers as partial clues ("Tamil ___").

**Fix:** a small, explicitly justified, closed exception list, `INDIAN_ADMIN_SUFFIXES = {"NADU", "PRADESH", "DESH"}`, added to `word_filters.py`, checked in addition to (not instead of) the WordNet-based check via a new combined function `is_droppable_suffix()`. This is explicitly framed in the code comments as being in the same justified-exception category as `scraper.py`'s `ALWAYS_IN_NEWS_PENALTY` list (Part 1 §4.4) — a small, finite, well-understood linguistic category (Indian state-name suffix morphemes), not the open-ended "which English descriptor word might appear next" problem that the original hand-maintained blacklist was rightly rejected for (Part 1 §6.5).

Verified against a deliberately tricky edge case: "Bangladesh" is one fused word (not two space-separated tokens "Bangla" + "Desh"), so the suffix-stripping logic — which only ever operates on whitespace-split tokens — correctly leaves it untouched. This confirms the fix doesn't overreach into single-word titles that merely *contain* the suffix as a substring.

Applied to **both** `india_trivia_scraper.py` (trailing-token stripping) and `scraper.py` (per-token filtering during entity splitting, since a headline could equally mention "Uttar Pradesh" as a GPE entity) — verified working correctly in both.

**Second occurrence — MAHAL:** a later puzzle surfaced `MAHAL` (from "Taj Mahal") as a standalone answer with a clue clearly describing the Taj Mahal specifically, exhibiting the identical failure pattern as NADU, just with a different suffix word ("Mahal" = "palace/mansion" in Hindi/Urdu, also not in WordNet). **Status: diagnosed, not yet fixed** — the fix is understood (add "MAHAL" and likely other common Indian architectural/toponymic suffixes — candidates include BHAVAN, BAGH, MINAR, NAGAR, GANJ, GARH, PURAM — to the same exception set) but was explicitly deferred as an open item when the session's priority shifted to other work.

**Lesson, updated from Part 1:** the "small closed exception list" pattern (as opposed to an open-ended blacklist) is valid and reusable, but "closed" doesn't mean "complete on the first attempt" — Indian architectural/administrative suffix morphemes turned out to be a *category* worth defending against, not a single fixed list nailed down in one pass. Each new instance (NADU, then MAHAL) extends the same list rather than requiring a new mechanism, which is the actual test of whether an exception list is well-scoped: new cases should be additions to an existing narrow category, not evidence the category itself was mis-scoped.

---

## 5. Grid seeding: making topical words reliably appear

**Problem, from before this document's coverage begins but resolved within it:** candidate-ordering alone (trying priority/topical words before generic filler within each slot's search order) was tested and found insufficient. Because the solver's slot-selection heuristic (Minimum Remaining Values, MRV — see Part 1 §5.2) always tackles the most-constrained slots first, and those are often short slots with few or no topical-word matches, letters frequently got locked in by filler *before* the solver ever reached slots where topical words could go — pruning them out via forward-checking before the ordering preference ever had a chance to apply.

**Fix, `seed_priority_words()`:** before general backtracking search begins, up to `max_seeds` (default 2) topical words are placed directly into randomly chosen, length-matching slots, with forward-checking applied immediately to confirm the seed doesn't create an unsolvable grid (if it does, that seed is abandoned and a different slot/word is tried). This mirrors how professional crossword constructors actually work — theme/topical entries are placed first, then the grid is autofilled around them — rather than treating topicality as a soft preference the general search might or might not honor.

**Follow-on bug found via testing, not assumption:** early testing of the seeding mechanism showed the same word (e.g. "MODI") occasionally seeded into two different non-crossing slots in the same grid, since forward-checking after the first seed only propagates to slots that actually *cross* the seeded one — a second, non-crossing slot of the same length remained independently free to also pick the same word. Fixed by tracking `used_words` during seeding and adding a general "no repeated answers in one puzzle" constraint to the core backtracking search itself (not just the seeding step), so this guarantee holds regardless of whether a duplicate would arise from seeding or from ordinary autofill.

**Result, verified across 8 repeated runs on real data:** every run produced 1-4 topical words in the final grid (occasionally exceeding the `max_seeds=2` floor, because candidate-ordering *does* still help once seeding has already placed a couple of anchor words and reduced the remaining search space) with zero duplicate answers.

---

## 6. Grid pattern variety

**Problem:** every puzzle used the same single 5x5 black-square layout (2 black squares, diagonal corners), inherited from the pattern originally chosen while debugging the "word square" over-constraint issue (Part 1 §5.4). Visually repetitive across days.

**Approach:** rather than hand-designing additional patterns (the project's one prior attempt at hand-designing a pattern — the original 2-corner layout — turned out to be an accidental word square, so hand-derivation was explicitly distrusted this time), a brute-force search was run over all 180-degree-rotationally-symmetric black-square placements for a 5x5 grid, programmatically filtered to two hard requirements:
1. Every across/down run has length 0 or ≥3 (no 1- or 2-letter fragments — the same requirement established in Part 1 §5.4).
2. All white cells form a single connected region (no isolated pockets of the grid unreachable from the rest).

The search found 11 valid patterns total, ranging from 2 to 8 black squares. **8 were hand-selected** from these for shipping, chosen for structural/visual diversity (different black-square counts: 2, 4, 6, 8; different shapes: diagonal, double-corner block, all-four-corners, side-stacked, L-shaped) rather than shipping all 11 or picking arbitrarily.

**Verification, not assumption:** all 8 selected patterns were test-filled against the real (post-hallucination-filter) `word_bank.txt` before shipping, confirming every one fills successfully and quickly (under 0.3 seconds each) — directly re-applying the lesson from Part 1 §5.4 that a pattern satisfying the structural validity rules above is *necessary* but was not, in that earlier case, sufficient proof of practical fillability without also testing against a real word list.

**Implementation:** `grid_generator.py`'s `generate_grid()` now accepts `pattern=None` by default, and picks one of the 8 patterns at random per call when no explicit pattern is passed. Existing call sites elsewhere in the pipeline needed no changes, since none of them pass an explicit pattern.

**Minor observation, not yet acted on:** one of the 8 patterns, when filled against the real word bank, produced the word "ASS" (a real, valid, but mildly awkward-for-general-audience word). Noted as the same category of concern as the earlier ISIS observation (Part 1's closing discussion) — a small, deliberate content-sensitivity exclusion list, not yet built.

---

## 7. Cross-Cutting Lessons (new, in addition to Part 1 §8)

1. **A filtering rule proven correct for one entity/word type does not automatically transfer to another.** `is_generic_word()` was validated for ORG-entity contamination, but would have been actively harmful applied to PERSON entities, due to WordNet's specific, discoverable weakness (poor contemporary-proper-noun coverage). Test each application context, don't assume transferability.

2. **Some failure modes are structural to the tool, not fixable by better data.** No amount of word-list curation prevents a small local LLM from confidently fabricating a false claim (GREG, CARR) when it has — or even when it lacks — real grounding. The correct response to this class of problem is a human-in-the-loop review step, not more upstream filtering. Recognizing which category a bug belongs to (fixable-by-filtering vs. fixable-only-by-review) matters as much as fixing it.

3. **When a fix that should have worked doesn't show up in output, verify the fix in isolation before doubting it.** The CARR recurrence looked at first like the hallucination-risk filter had failed; testing the filter function directly (and confirming it correctly rejects CARR) redirected the investigation to the actual cause (a skipped pipeline step) much faster than re-debugging already-correct logic would have.

4. **Multi-stage pipelines with file-based handoffs need enforced ordering, not just documentation of the correct order.** Telling a person "run A before B" is weaker than making it structurally impossible to run B against stale output from before A's most recent change — achieved here via `set -e` orchestration scripts rather than relying on memory or a README.

5. **A "small closed exception list" is validated by how new instances behave, not by being finished on the first pass.** NADU and MAHAL are two instances of one category (Indian toponymic/architectural suffix morphemes); the second instance extending the same mechanism, rather than requiring a new one, is what makes the original design choice (a narrow exception list, not a blacklist) still correct in hindsight.

6. **Don't hand-design combinatorial structures (like grid patterns) when they can be brute-force searched and validated instead.** The project's one prior hand-derived pattern was wrong in a non-obvious way (Part 1 §5.4); the fix this time was to make the computer enumerate and validate every option against explicit rules, then choose from provably-valid candidates — turning a "did I think about this carefully enough" question into a mechanically checked one.

---

## 8. Open Items (updated from Part 1 §9)

Carried over, still open:
- **Clue-snippet-in-output review workflow** — now confirmed necessary by direct evidence (GREG, CARR), not just a theoretical concern. This is the highest-priority open item.
- **MAHAL-style suffix fix** — diagnosed, root cause understood and identical to the already-fixed NADU case, mechanical fix not yet applied (needs `INDIAN_ADMIN_SUFFIXES` in `word_filters.py` extended with MAHAL and likely BHAVAN/BAGH/MINAR/NAGAR/GANJ/GARH/PURAM).
- **Content-sensitivity exclusion list** (ISIS, ASS-type words) — flagged twice now, not yet built.
- Cricket-specific evergreen data source, TMDb integration for film popularity, Midi/full Crossword sizes, website/app frontend, hosting — unchanged from Part 1, still deferred.

Newly resolved in this phase:
- ~~PAINE/KYRIE-style hallucination from context-free filler words~~ — fixed (`is_safe_context_free_word`).
- ~~DIES-style NER misfire from Title-Case headlines~~ — fixed (POS-tag cross-check + selective title lowercasing).
- ~~NADU-style fragment answers~~ — fixed for this specific instance (`INDIAN_ADMIN_SUFFIXES`); category remains open per MAHAL above.
- ~~Pipeline steps run out of order / against stale intermediate files~~ — fixed (`run_daily.sh` / `setup_evergreen.sh`).
- ~~Topical words rarely appearing in generated grids~~ — fixed (`seed_priority_words`).
- ~~Every puzzle using the same grid pattern~~ — fixed (8-pattern random selection).

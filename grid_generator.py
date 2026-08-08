"""
grid_generator.py
Fills a crossword grid pattern using backtracking search + forward checking
(a CSP: variables = slots, domains = matching-length words, constraints =
crossing letters must agree).

Standalone / testable with a dummy word list -- doesn't depend on scraper.py.

Run: python grid_generator.py
"""

import json
import random
from collections import defaultdict, Counter

BLACK = "#"
EMPTY = "."

# --- Patterns: 8 hand-picked, structurally distinct 5x5 layouts ----------
# All found via brute-force search over 180-degree-rotationally-symmetric
# black-square placements, filtered to: every across/down run is length 0
# or >=3 (no 1/2-letter fragments), and all white cells form one connected
# region (no isolated pockets). See project notes -- the earlier single-
# pattern version (2 corner black squares) turned out to be a "word
# square" (maximally hard to fill); these were validated the same way
# before being hand-selected for visual/structural variety.
PATTERNS = [
    [  # 2 black squares, diagonal corners (style used previously)
        [EMPTY, EMPTY, EMPTY, EMPTY, BLACK],
        [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
        [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
        [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
        [BLACK, EMPTY, EMPTY, EMPTY, EMPTY],
    ],
    [  # 2 black squares, opposite diagonal
        [BLACK, EMPTY, EMPTY, EMPTY, EMPTY],
        [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
        [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
        [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
        [EMPTY, EMPTY, EMPTY, EMPTY, BLACK],
    ],
    [  # 4 black squares, double-corner blocks (top-left / bottom-right)
        [BLACK, BLACK, EMPTY, EMPTY, EMPTY],
        [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
        [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
        [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
        [EMPTY, EMPTY, EMPTY, BLACK, BLACK],
    ],
    [  # 4 black squares, all four corners
        [BLACK, EMPTY, EMPTY, EMPTY, BLACK],
        [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
        [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
        [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
        [BLACK, EMPTY, EMPTY, EMPTY, BLACK],
    ],
    [  # 4 black squares, vertical side stacks
        [BLACK, EMPTY, EMPTY, EMPTY, EMPTY],
        [BLACK, EMPTY, EMPTY, EMPTY, EMPTY],
        [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
        [EMPTY, EMPTY, EMPTY, EMPTY, BLACK],
        [EMPTY, EMPTY, EMPTY, EMPTY, BLACK],
    ],
    [  # 6 black squares, L-shaped corners
        [BLACK, BLACK, EMPTY, EMPTY, EMPTY],
        [BLACK, EMPTY, EMPTY, EMPTY, EMPTY],
        [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
        [EMPTY, EMPTY, EMPTY, EMPTY, BLACK],
        [EMPTY, EMPTY, EMPTY, BLACK, BLACK],
    ],
    [  # 6 black squares, L-shaped corners (mirrored)
        [EMPTY, EMPTY, EMPTY, BLACK, BLACK],
        [EMPTY, EMPTY, EMPTY, EMPTY, BLACK],
        [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
        [BLACK, EMPTY, EMPTY, EMPTY, EMPTY],
        [BLACK, BLACK, EMPTY, EMPTY, EMPTY],
    ],
    [  # 8 black squares, chunkier double-corner blocks
        [BLACK, BLACK, EMPTY, EMPTY, EMPTY],
        [BLACK, BLACK, EMPTY, EMPTY, EMPTY],
        [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
        [EMPTY, EMPTY, EMPTY, BLACK, BLACK],
        [EMPTY, EMPTY, EMPTY, BLACK, BLACK],
    ],
]

# Kept for backwards compatibility with any code still referencing this
# name directly -- new code should use PATTERNS + random selection.
PATTERN_A = PATTERNS[0]


# --- Midi / Crossword: generated patterns, not hand-picked --------------
# Unlike the 5x5 Mini (small enough to brute-force ALL valid patterns and
# hand-pick a diverse set), Midi/Crossword sizes have far too many possible
# symmetric black-square placements to enumerate (9x9 has 40 symmetric
# cell-pairs -> 2^40 combinations; 15x15 has 112 -> 2^112). Patterns are
# built incrementally instead: add symmetric black-square pairs one at a
# time, keeping only pairs that don't break validity (every run length 0
# or >=3), until a target density is reached.
#
# Density matters enormously, found by direct testing, not guessing: a
# 15x15 grid at 16% density (closer to hand-picked "authentic" NYT feel)
# did not solve within 45 seconds even with the curated crossword-quality
# word list. At 20% density (still a realistic NYT daily range of 16-20%),
# the same word list solved in ~42 seconds with excellent fill quality.
# Below are the calibrated defaults; see build_crossword_quality_wordlist.py
# for why vocabulary quality matters just as much as density here.
MIDI_SIZE = 9
MIDI_DENSITY = 0.20
CROSSWORD_SIZE = 15
CROSSWORD_DENSITY = 0.20


def _generate_symmetric_pattern(size, target_black_fraction, max_tries=30):
    """
    Incrementally build a valid, 180-degree-rotationally-symmetric
    black-square pattern at the given size and approximate density.
    Adds random symmetric pairs one at a time, keeping only ones that
    don't create an invalid run (length 1 or 2); retries with a fresh
    random order up to max_tries if a given attempt gets stuck below the
    target density. This replaces exhaustive search (infeasible at these
    sizes -- see comment above) with validated incremental construction.
    """
    center = (size // 2, size // 2) if size % 2 == 1 else None
    all_pairs = []
    seen = set()
    for r in range(size):
        for c in range(size):
            if (r, c) == center or (r, c) in seen:
                continue
            mirror = (size - 1 - r, size - 1 - c)
            all_pairs.append(((r, c), mirror))
            seen.add((r, c))
            seen.add(mirror)

    target_black = int(size * size * target_black_fraction)

    for attempt in range(max_tries):
        grid = [[EMPTY] * size for _ in range(size)]
        pairs = list(all_pairs)
        random.shuffle(pairs)
        black_count = 0
        for (p1, p2) in pairs:
            if black_count >= target_black:
                break
            grid[p1[0]][p1[1]] = BLACK
            grid[p2[0]][p2[1]] = BLACK
            slots, _ = find_slots(grid)
            if all(s.length >= 3 for s in slots):
                black_count += 2
            else:
                grid[p1[0]][p1[1]] = EMPTY
                grid[p2[0]][p2[1]] = EMPTY
        if black_count > 0:
            return grid

    return None


def generate_midi(word_list, priority_words=None, max_seeds=3, pattern_attempts=5):
    """
    Generate a 9x9 Midi puzzle. Uses a freshly generated symmetric pattern
    each call (see _generate_symmetric_pattern) rather than a fixed set --
    Midi/Crossword patterns are cheap to generate on demand, unlike Mini's
    hand-picked set.

    pattern_attempts: tries multiple DIFFERENT random patterns, not just
    multiple word-orderings within one pattern. Found by testing, not
    assumed: some specific patterns are genuinely harder to fill than
    others even though all pass the same structural validity checks (no
    1/2-letter runs, connected) -- retrying word order alone within one
    unlucky pattern can still fail or take a long time, while trying a
    fresh pattern often succeeds quickly. This is the same "bad orderings
    get stuck, fresh restarts often don't" lesson as the node_budget
    mechanism in backtrack(), just applied one level up.
    """
    for _ in range(pattern_attempts):
        pattern = _generate_symmetric_pattern(MIDI_SIZE, MIDI_DENSITY)
        if pattern is None:
            continue
        result = generate_grid(word_list, pattern=pattern, max_attempts=20,
                                priority_words=priority_words, max_seeds=max_seeds,
                                node_budget_per_attempt=5000)
        if result:
            return result
    return None


def generate_crossword(word_list, priority_words=None, max_seeds=4, pattern_attempts=3):
    """
    Generate a 15x15 full Crossword puzzle. Same approach as generate_midi,
    including trying multiple different patterns if one is a bad draw.
    Tested: ~40-60s per pattern attempt at 20% density with the curated
    crossword-quality word list -- fine for a once-daily batch job, NOT
    fine for interactive use. Don't call this from anything that needs a
    fast response, and expect this to take a few minutes in the worst
    case (multiple pattern attempts each taking up to a minute).
    """
    for _ in range(pattern_attempts):
        pattern = _generate_symmetric_pattern(CROSSWORD_SIZE, CROSSWORD_DENSITY)
        if pattern is None:
            continue
        result = generate_grid(word_list, pattern=pattern, max_attempts=15,
                                priority_words=priority_words, max_seeds=max_seeds,
                                node_budget_per_attempt=8000)
        if result:
            return result
    return None


class Slot:
    def __init__(self, slot_id, direction, cells):
        self.id = slot_id            # e.g. "1-across"
        self.direction = direction   # "across" | "down"
        self.cells = cells           # list of (row, col), in order
        self.length = len(cells)

    def __repr__(self):
        return f"<Slot {self.id} len={self.length}>"


def find_slots(pattern):
    """Scan the pattern and return (slots list, numbering dict)."""
    rows, cols = len(pattern), len(pattern[0])
    slots = []

    # Across slots
    for r in range(rows):
        c = 0
        while c < cols:
            if pattern[r][c] == BLACK:
                c += 1
                continue
            start = c
            cells = []
            while c < cols and pattern[r][c] == EMPTY:
                cells.append((r, c))
                c += 1
            if len(cells) >= 2:
                slots.append(Slot(None, "across", cells))

    # Down slots
    for c in range(cols):
        r = 0
        while r < rows:
            if pattern[r][c] == BLACK:
                r += 1
                continue
            cells = []
            while r < rows and pattern[r][c] == EMPTY:
                cells.append((r, c))
                r += 1
            if len(cells) >= 2:
                slots.append(Slot(None, "down", cells))

    # Numbering: scan row-major; a cell gets a number if it starts an
    # across or down slot (standard crossword numbering convention)
    starts = {}
    for slot in slots:
        starts.setdefault(slot.cells[0], []).append(slot)

    number = 1
    numbering = {}
    for r in range(rows):
        for c in range(cols):
            if (r, c) in starts:
                numbering[(r, c)] = number
                for slot in starts[(r, c)]:
                    slot.id = f"{number}-{slot.direction}"
                number += 1

    return slots, numbering


def build_crossings(slots):
    """
    For each pair of slots that share a cell, record which index in each
    slot's cell list corresponds to the shared cell.
    Returns dict: slot_id -> list of (other_slot_id, my_index, their_index)
    """
    cell_to_slots = defaultdict(list)
    for slot in slots:
        for idx, cell in enumerate(slot.cells):
            cell_to_slots[cell].append((slot, idx))

    crossings = defaultdict(list)
    for cell, entries in cell_to_slots.items():
        if len(entries) != 2:
            continue  # only across+down crossing expected in this pattern
        (slot_a, idx_a), (slot_b, idx_b) = entries
        crossings[slot_a.id].append((slot_b.id, idx_a, idx_b))
        crossings[slot_b.id].append((slot_a.id, idx_b, idx_a))

    return crossings


def build_domains(slots, word_list):
    """Group words by length so each slot gets only length-matching candidates.
    Domains are SETS (not lists) -- required for the AC-3 implementation
    below, which relies on fast set intersection/union rather than linearly
    scanning every word in a domain on every check. This matters a lot once
    domains get into the thousands of words (Midi/Crossword sizes)."""
    by_length = defaultdict(set)
    for w in word_list:
        w = w.strip().upper()
        if w.isalpha():
            by_length[len(w)].add(w)

    domains = {}
    for slot in slots:
        domains[slot.id] = set(by_length.get(slot.length, set()))
    return domains


def build_letter_counts(domains, slots):
    """
    letter_counts[slot_id][position] = Counter of {letter: how many words
    currently in this slot's domain have that letter at that position}.

    Why this exists: revise() needs to answer "which letters are still
    possible at position i of slot B's domain" on every arc check. Doing
    that by scanning domain B's words each time (`{w[i] for w in domain}`)
    is O(|domain B|) -- fine once, ruinous when it happens on every node
    of a search over thousands-of-words domains (measured: ~0.18s for a
    SINGLE top-level assignment at Midi size, dominated by exactly this).
    Maintaining counts incrementally (decrement on remove, increment on
    restore) turns that lookup into O(26) regardless of domain size --
    the standard technique real crossword-fill software uses for this.
    """
    counts = {}
    for slot in slots:
        counts[slot.id] = [Counter() for _ in range(slot.length)]
        for w in domains[slot.id]:
            for i, ch in enumerate(w):
                counts[slot.id][i][ch] += 1
    return counts


def _remove_from_domain(slot_id, word, domains, letter_counts):
    domains[slot_id].discard(word)
    for i, ch in enumerate(word):
        letter_counts[slot_id][i][ch] -= 1


def _add_to_domain(slot_id, word, domains, letter_counts):
    domains[slot_id].add(word)
    for i, ch in enumerate(word):
        letter_counts[slot_id][i][ch] += 1


def build_crossing_map(crossings):
    """slot_a_id, slot_b_id -> (index_in_a, index_in_b), for O(1) arc lookup
    during AC-3 (as opposed to scanning the crossings[slot_id] list)."""
    crossing_map = {}
    for slot_id, entries in crossings.items():
        for other_id, my_idx, their_idx in entries:
            crossing_map[(slot_id, other_id)] = (my_idx, their_idx)
    return crossing_map


def revise(slot_a, slot_b, domains, crossing_map, letter_counts):
    """
    AC-3 'revise': return the subset of domains[slot_a] that has at least
    one supporting value in domains[slot_b] given their crossing
    constraint.

    Implementation note, found by profiling rather than assuming: an
    earlier version tried to speed this up with a global position-index
    (pos_index[length][position][letter] -> set of words), unioning index
    buckets for each valid letter and intersecting with domains[slot_a].
    That was measurably SLOWER in practice (profiled: revise() was the
    dominant cost, ~0.1s across 632 calls for a single top-level
    assignment) -- because the bucket-union step touches the FULL,
    unpruned set of words for each letter, which can be larger than
    domains[slot_a] itself, especially once search has already pruned
    domains[slot_a] down. A plain scan of domains[slot_a] with an O(1)
    membership check against valid_letters (itself O(1) to look up via
    letter_counts, see build_letter_counts) turned out over 100x faster
    on the same test case. Lesson: an index that's supposed to help can
    still lose to the "naive" approach if what it indexes doesn't shrink
    along with the thing you're actually filtering.
    """
    idx_a, idx_b = crossing_map[(slot_a, slot_b)]
    valid_letters = {ch for ch, cnt in letter_counts[slot_b][idx_b].items() if cnt > 0}
    return {w for w in domains[slot_a] if w[idx_a] in valid_letters}


def ac3(initial_arcs, domains, crossings, crossing_map, letter_counts, prune_log):
    """
    Full arc-consistency propagation (not just one level): whenever a
    domain shrinks, every OTHER arc pointing at the slot that shrank gets
    re-queued, cascading until nothing changes anywhere or a domain goes
    empty. This is what makes Midi/Crossword-size grids tractable --
    the earlier single-level forward_check() only propagated from the
    just-assigned slot to its direct neighbors, missing second-order
    consequences that matter a lot once grids are big enough to have long
    dependency chains between slots.

    `prune_log` accumulates (slot_id, removed_word) so the caller can
    restore exactly what this call removed, on backtrack.
    """
    queue = list(initial_arcs)
    while queue:
        slot_a, slot_b = queue.pop()
        new_domain = revise(slot_a, slot_b, domains, crossing_map, letter_counts)
        removed = domains[slot_a] - new_domain
        if removed:
            for w in removed:
                prune_log.append((slot_a, w))
                _remove_from_domain(slot_a, w, domains, letter_counts)
            if not domains[slot_a]:
                return False
            for other_id, _, _ in crossings[slot_a]:
                if other_id != slot_b:
                    queue.append((other_id, slot_a))
    return True


def restore(domains, letter_counts, prune_log):
    for slot_id, word in prune_log:
        _add_to_domain(slot_id, word, domains, letter_counts)


def select_unassigned_slot(slots, assignment, domains):
    """MRV heuristic: pick the unassigned slot with fewest remaining candidates."""
    unassigned = [s for s in slots if s.id not in assignment]
    return min(unassigned, key=lambda s: len(domains[s.id]))


def order_candidates(domain, priority_words):
    """
    Try priority (topical: today's news / India trivia) words before
    generic filler words. Without this, topical words -- typically a few
    hundred out of several thousand total -- would only end up in the
    puzzle by chance, since random.shuffle() alone treats every word
    equally. This does NOT reduce correctness of the search (every word
    is still tried eventually on backtrack) -- it only changes the ORDER
    words are attempted in, biasing the first-found solution toward
    containing more topical content.
    """
    candidates = list(domain)
    if not priority_words:
        random.shuffle(candidates)
        return candidates

    priority = [w for w in candidates if w in priority_words]
    rest = [w for w in candidates if w not in priority_words]
    random.shuffle(priority)
    random.shuffle(rest)
    return priority + rest


def assign(slot_id, word, domains, crossings, crossing_map, letter_counts):
    """
    Tentatively assign `word` to `slot_id` (reduce its domain to just that
    one word) and propagate full arc consistency outward via ac3().
    Returns a prune_log (possibly empty) to pass to restore() on backtrack,
    or None if this assignment makes the grid unsolvable.
    """
    prune_log = []
    removed = domains[slot_id] - {word}
    for w in removed:
        prune_log.append((slot_id, w))
        _remove_from_domain(slot_id, w, domains, letter_counts)

    initial_arcs = [(other_id, slot_id) for other_id, _, _ in crossings[slot_id]]
    ok = ac3(initial_arcs, domains, crossings, crossing_map, letter_counts, prune_log)
    if not ok:
        restore(domains, letter_counts, prune_log)
        return None
    return prune_log


def backtrack(slots, assignment, domains, crossings, crossing_map, letter_counts,
              priority_words=None, node_budget=None):
    """
    node_budget: mutable single-element list [remaining_nodes], shared
    across the whole recursive search. AC-3 (see ac3() above) guarantees
    pairwise consistency, which is NECESSARY but not SUFFICIENT to avoid
    combinatorial blowup -- bad early choices can still lead into a huge
    unproductive subtree that only fails many levels deep. Rather than let
    one search run indefinitely, each attempt gets a fixed node budget; if
    it's exhausted, backtrack() gives up (returns None) and generate_grid's
    outer retry loop tries again with a fresh random ordering. This is a
    standard, pragmatic CSP mitigation: many random orderings solve almost
    instantly, a few get catastrophically stuck, and bounding + restarting
    is far more reliable in practice than hoping the first ordering is a
    good one, especially at Midi/Crossword sizes where a bad subtree can
    otherwise run for a very long time.
    """
    if node_budget is not None and node_budget[0] <= 0:
        return None

    if len(assignment) == len(slots):
        return dict(assignment)

    slot = select_unassigned_slot(slots, assignment, domains)
    candidates = order_candidates(domains[slot.id], priority_words)
    used_words = set(assignment.values())

    for word in candidates:
        if word in used_words:
            continue  # no repeated answers within one puzzle

        if node_budget is not None:
            if node_budget[0] <= 0:
                return None
            node_budget[0] -= 1  # counts every word actually attempted,
            # not just every recursive call -- a slot with many bad
            # candidates can otherwise burn unbounded time inside one
            # "node" without the budget ever seeing it (found via
            # profiling: a 200-node budget took 3.7s for what the old
            # accounting called "1 node").

        assignment[slot.id] = word
        prune_log = assign(slot.id, word, domains, crossings, crossing_map,
                            letter_counts)
        if prune_log is not None:
            result = backtrack(slots, assignment, domains, crossings, crossing_map,
                                letter_counts, priority_words, node_budget)
            if result is not None:
                return result
            restore(domains, letter_counts, prune_log)
        del assignment[slot.id]

    return None


def seed_priority_words(slots, domains, crossings, crossing_map, letter_counts,
                         priority_words, max_seeds=2):
    """
    Place up to `max_seeds` topical (news/trivia) words directly into
    matching-length slots BEFORE autofill runs -- this is how real
    crossword constructors work (theme entries first, autofill around
    them), and it's a much stronger guarantee than candidate-ordering
    alone: with thousands of filler words vs a few hundred topical ones,
    MRV tends to fill the most-constrained slots (often ones with no
    topical candidates) first, which can prune topical words out of
    later slots before the solver even tries them. Seeding sidesteps
    that entirely for a small, fixed number of entries.

    Returns the seeded assignment dict (possibly empty if nothing could
    be seeded without an immediate conflict -- that's fine, autofill
    proceeds normally either way).
    """
    assignment = {}
    if not priority_words:
        return assignment

    used_words = set()
    shuffled_slots = list(slots)
    random.shuffle(shuffled_slots)

    for slot in shuffled_slots:
        if len(assignment) >= max_seeds:
            break
        candidates = [w for w in domains[slot.id]
                      if w in priority_words and w not in used_words]
        if not candidates:
            continue
        random.shuffle(candidates)
        word = candidates[0]

        prune_log = assign(slot.id, word, domains, crossings, crossing_map,
                            letter_counts)
        if prune_log is None:
            continue
        assignment[slot.id] = word
        used_words.add(word)

    return assignment


def generate_grid(word_list, pattern=None, max_attempts=50, priority_words=None,
                   max_seeds=2, node_budget_per_attempt=20000):
    """
    If `pattern` isn't given, picks one at random from PATTERNS each call --
    this is what actually gives you a different-looking grid each run,
    rather than the same black-square layout every time. Pass an explicit
    pattern to pin a specific layout (useful for testing), or a pattern of
    a different size entirely (Midi/Crossword) -- everything here is size-
    agnostic; it operates purely on the pattern grid passed in.

    node_budget_per_attempt: caps how much backtracking search a single
    attempt is allowed before giving up and retrying with a fresh random
    ordering (see backtrack()'s docstring for why this matters). Larger
    grids need more attempts / bigger budgets to reliably solve -- see
    generate_midi()/generate_crossword() below for pre-tuned wrappers
    rather than guessing these numbers yourself each time.
    """
    if pattern is None:
        pattern = random.choice(PATTERNS)

    slots, numbering = find_slots(pattern)
    crossings = build_crossings(slots)
    crossing_map = build_crossing_map(crossings)

    for attempt in range(max_attempts):
        domains = build_domains(slots, word_list)
        if any(len(d) == 0 for d in domains.values()):
            continue
        letter_counts = build_letter_counts(domains, slots)

        seeded_assignment = seed_priority_words(
            slots, domains, crossings, crossing_map, letter_counts,
            priority_words, max_seeds
        )

        node_budget = [node_budget_per_attempt] if node_budget_per_attempt else None
        result = backtrack(slots, seeded_assignment, domains, crossings, crossing_map,
                            letter_counts, priority_words, node_budget)
        if result:
            return build_output(pattern, slots, numbering, result)

    return None


def build_output(pattern, slots, numbering, assignment):
    rows, cols = len(pattern), len(pattern[0])
    grid = [[BLACK if pattern[r][c] == BLACK else "" for c in range(cols)]
            for r in range(rows)]

    for slot in slots:
        word = assignment[slot.id]
        for (r, c), letter in zip(slot.cells, word):
            grid[r][c] = letter

    grid_strs = ["".join(row) for row in grid]

    clues_meta = {"across": {}, "down": {}}
    for slot in slots:
        num = slot.id.split("-")[0]
        clues_meta[slot.direction][num] = {
            "answer": assignment[slot.id],
            "length": slot.length,
        }

    return {
        "size": {"rows": rows, "cols": cols},
        "grid": grid_strs,
        "numbering": {f"{r},{c}": n for (r, c), n in numbering.items()},
        "words": clues_meta,
    }


if __name__ == "__main__":
    import os
    import sys

    size_arg = sys.argv[1] if len(sys.argv) > 1 else "mini"
    if size_arg not in ("mini", "midi", "crossword"):
        print(f"Unknown size '{size_arg}' -- use mini, midi, or crossword")
        sys.exit(1)

    priority_words = set()
    if os.path.exists("priority_words.txt"):
        with open("priority_words.txt") as f:
            priority_words = {w.strip() for w in f if w.strip()}
        print(f"Loaded {len(priority_words)} priority (topical) words")

    if size_arg == "mini":
        word_bank_path = "merged_word_bank.txt"
        fallback_path = "word_bank.txt"
    else:
        word_bank_path = "midi_crossword_word_bank.txt"
        fallback_path = "crossword_quality_words.txt"

    if os.path.exists(word_bank_path):
        with open(word_bank_path) as f:
            word_list = [w.strip() for w in f if w.strip()]
        print(f"Loaded {len(word_list)} words from {word_bank_path}")
    elif os.path.exists(fallback_path):
        # crossword_quality_words.txt is WORD<tab>score; word_bank.txt is
        # plain -- handle both since either could be the fallback here.
        with open(fallback_path) as f:
            first_line = f.readline()
            f.seek(0)
            if "\t" in first_line:
                word_list = [line.split("\t")[0].strip() for line in f if line.strip()]
            else:
                word_list = [w.strip() for w in f if w.strip()]
        print(f"Loaded {len(word_list)} words from {fallback_path} "
              f"(run merge_sources.py for topical content)")
    else:
        print(f"No word bank found for '{size_arg}' -- run setup_evergreen.sh "
              f"and merge_sources.py first.")
        sys.exit(1)

    print(f"\nGenerating {size_arg} puzzle...")
    if size_arg == "mini":
        result = generate_grid(word_list, priority_words=priority_words)
    elif size_arg == "midi":
        result = generate_midi(word_list, priority_words=priority_words)
    else:
        result = generate_crossword(word_list, priority_words=priority_words)

    if result is None:
        print(f"FAILED to generate {size_arg} grid -- word list too sparse "
              f"or pattern too constrained.")
        sys.exit(1)

    out_path = f"test_grid_{size_arg}.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Wrote {out_path}")

    for row in result["grid"]:
        print("  ", row)

    topical_hits = [w for slot in result["words"].values()
                     for e in slot.values()
                     for w in [e["answer"]] if w in priority_words]
    print(f"\nTopical (news/trivia) words in this grid: {topical_hits}")
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
from collections import defaultdict

BLACK = "#"
EMPTY = "."

# --- Pattern: 5x5, symmetric black squares (NYT-Mini style) --------------
# 2 black squares in a corner is deceptively hard: it makes EVERY letter
# doubly-checked (both across and down), which is effectively a "word
# square" -- a much harder constraint class that most word lists can't
# fill. Real minis use more black squares to relax this. This pattern has
# 4 black squares (two symmetric corner pairs), which is far more fillable.
PATTERN_A = [
    [EMPTY, EMPTY, EMPTY, EMPTY, BLACK],
    [EMPTY, EMPTY, EMPTY, EMPTY, BLACK],
    [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
    [BLACK, EMPTY, EMPTY, EMPTY, EMPTY],
    [BLACK, EMPTY, EMPTY, EMPTY, EMPTY],
]


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
    """Group words by length so each slot gets only length-matching candidates."""
    by_length = defaultdict(list)
    for w in word_list:
        w = w.strip().upper()
        if w.isalpha():
            by_length[len(w)].append(w)

    domains = {}
    for slot in slots:
        domains[slot.id] = list(by_length.get(slot.length, []))
    return domains


def word_consistent(word, other_word, my_idx, their_idx):
    return word[my_idx] == other_word[their_idx]


def forward_check(slot_id, word, domains, crossings, slots_by_id):
    """
    After tentatively assigning `word` to `slot_id`, prune neighboring
    domains to only words consistent with the crossing letter.
    Returns a dict of {slot_id: pruned_domain} for slots that were touched,
    or None if any domain becomes empty (dead end).
    """
    pruned = {}
    for other_id, my_idx, their_idx in crossings[slot_id]:
        letter = word[my_idx]
        current_domain = domains[other_id]
        new_domain = [w for w in current_domain if w[their_idx] == letter]
        pruned[other_id] = current_domain
        domains[other_id] = new_domain
        if not new_domain:
            restore(domains, pruned)  # undo everything pruned so far this call
            return None  # dead end
    return pruned


def restore(domains, pruned):
    for slot_id, old_domain in pruned.items():
        domains[slot_id] = old_domain


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
    if not priority_words:
        candidates = list(domain)
        random.shuffle(candidates)
        return candidates

    priority = [w for w in domain if w in priority_words]
    rest = [w for w in domain if w not in priority_words]
    random.shuffle(priority)
    random.shuffle(rest)
    return priority + rest


def backtrack(slots, assignment, domains, crossings, slots_by_id, priority_words=None):
    if len(assignment) == len(slots):
        return dict(assignment)

    slot = select_unassigned_slot(slots, assignment, domains)
    candidates = order_candidates(domains[slot.id], priority_words)
    used_words = set(assignment.values())

    for word in candidates:
        if word in used_words:
            continue  # no repeated answers within one puzzle
        consistent = True
        for other_id, my_idx, their_idx in crossings[slot.id]:
            if other_id in assignment:
                if word[my_idx] != assignment[other_id][their_idx]:
                    consistent = False
                    break
        if not consistent:
            continue

        assignment[slot.id] = word
        pruned = forward_check(slot.id, word, domains, crossings, slots_by_id)
        if pruned is not None:
            result = backtrack(slots, assignment, domains, crossings, slots_by_id, priority_words)
            if result is not None:
                return result
        restore(domains, pruned or {})
        del assignment[slot.id]

    return None


def seed_priority_words(slots, domains, crossings, slots_by_id, priority_words, max_seeds=2):
    """
    Place up to `max_seeds` topical (news/trivia) words directly into
    matching-length slots BEFORE autofill runs -- this is how real
    crossword constructors work (theme entries first, autofill around
    them), and it's a much stronger guarantee than candidate-ordering
    alone: with ~6000 filler words vs a few hundred topical ones, MRV
    tends to fill the most-constrained slots (often short ones with no
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

        assignment[slot.id] = word
        pruned = forward_check(slot.id, word, domains, crossings, slots_by_id)
        if pruned is None:
            del assignment[slot.id]
            continue
        used_words.add(word)

    return assignment


def generate_grid(word_list, pattern=PATTERN_A, max_attempts=50, priority_words=None,
                   max_seeds=2):
    slots, numbering = find_slots(pattern)
    crossings = build_crossings(slots)
    slots_by_id = {s.id: s for s in slots}

    for attempt in range(max_attempts):
        domains = build_domains(slots, word_list)
        if any(len(d) == 0 for d in domains.values()):
            continue

        seeded_assignment = seed_priority_words(
            slots, domains, crossings, slots_by_id, priority_words, max_seeds
        )

        result = backtrack(slots, seeded_assignment, domains, crossings, slots_by_id,
                            priority_words)
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

    # Prefer the merged pool (news + trivia + general) if merge_sources.py
    # has been run; fall back to plain word_bank.txt; fall back to a tiny
    # built-in list only for a quick smoke test with no setup at all.
    if os.path.exists("merged_word_bank.txt"):
        with open("merged_word_bank.txt") as f:
            word_list = [w.strip() for w in f if w.strip()]
        print(f"Loaded {len(word_list)} words from merged_word_bank.txt")

        priority_words = set()
        if os.path.exists("priority_words.txt"):
            with open("priority_words.txt") as f:
                priority_words = {w.strip() for w in f if w.strip()}
            print(f"Loaded {len(priority_words)} priority (topical) words")
    elif os.path.exists("word_bank.txt"):
        with open("word_bank.txt") as f:
            word_list = [w.strip() for w in f if w.strip()]
        print(f"Loaded {len(word_list)} words from word_bank.txt "
              f"(no merged pool found -- run merge_sources.py for topical content)")
        priority_words = set()
    else:
        print("No word bank found -- using tiny built-in dummy list "
              "(see build_word_bank.py / merge_sources.py).")
        word_list = [
            "MODI", "TRUMP", "ASIA", "WEST", "BILL", "OMAN", "COURT", "KERALA",
            "CENTRE", "HORMUZ", "SHARIF", "TAJ", "GOA", "PUNE", "DELHI", "INDIA",
            "RIVER", "TIGER", "MANGO", "CRANE", "LEMON", "STONE", "PLANE",
            "TABLE", "CHAIR", "HOUSE", "MUSIC", "DANCE", "LIGHT", "NIGHT",
            "OCEAN", "CLOUD", "STORM", "BEACH", "FOREST", "BRIDGE", "TEMPLE",
            "ISRO", "SEBI", "IPL", "NAAN", "CURRY", "SAREE", "YOGA", "RAJA",
        ]
        priority_words = set()

    result = generate_grid(word_list, priority_words=priority_words)
    if result is None:
        print("FAILED to generate grid -- word list too sparse for this pattern.")
    else:
        print(json.dumps(result, indent=2))
        with open("test_grid.json", "w") as f:
            json.dump(result, f, indent=2)
        print("\nWrote test_grid.json")

        topical_hits = [w for slot in result["words"].values()
                         for e in slot.values()
                         for w in [e["answer"]] if w in priority_words]
        print(f"\nTopical (news/trivia) words in this grid: {topical_hits}")
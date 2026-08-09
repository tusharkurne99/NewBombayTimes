"""
publish_web.py
Takes today's reviewed puzzle_<date>_<size>.json files (from
clue_generator.py, after you've picked/edited clue_options for any
review_recommended clue -- see project_log_week2.md section 5) and writes
a slimmed, public-safe copy to web/data/puzzles/latest_<size>.json, which
is what the actual website (web/index.html, web/solve.html) reads.

Why "slimmed," not a straight copy: the full puzzle JSON carries editorial
metadata that has no business being shipped to visitors --
review_recommended, clue_options (the alternates you didn't pick),
source_snippet, source, and context_meta (article links, Wikipedia URLs,
mention counts). None of that is needed to solve a puzzle, and some of it
(direct article links, internal review flags) isn't meant for public
consumption. Only answer/clue/length per slot, plus grid/numbering/size/
date/id, are kept.

Run: python publish_web.py [YYYY-MM-DD]
  (defaults to today; pass an explicit date to (re-)publish a past day,
  e.g. after fixing a clue you noticed was wrong post-publish)
"""

import json
import sys
from datetime import date

import paths

SIZES = ("mini", "midi", "crossword")


def slim(full):
    out = {
        "id": full["id"],
        "date": full["date"],
        "puzzle_type": full["puzzle_type"],
        "size": full["size"],
        "grid": full["grid"],
        "numbering": full["numbering"],
        "clues": {"across": {}, "down": {}},
    }
    for direction in ("across", "down"):
        for num, entry in full["clues"][direction].items():
            out["clues"][direction][num] = {
                "clue": entry["clue"],
                "length": entry["length"],
            }
    return out


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()

    published = []
    for size in SIZES:
        src_path = paths.puzzle_path(date_str, size)
        try:
            with open(src_path) as f:
                full = json.load(f)
        except FileNotFoundError:
            print(f"  (skipping {size} -- {src_path} not found)")
            continue

        dst_path = paths.web_puzzle_path(size)
        with open(dst_path, "w") as f:
            json.dump(slim(full), f, indent=2)
        print(f"  published {size} -> {dst_path}")
        published.append(size)

    if not published:
        print(f"Nothing published -- no puzzle files found for {date_str}.")
        sys.exit(1)

    print(f"\nPublished {len(published)}/3 sizes for {date_str}.")
    print("Next: scripts/publish.sh will git add/commit/push web/data/puzzles/ "
          "for you, or do it yourself if you're running this script directly.")


if __name__ == "__main__":
    main()

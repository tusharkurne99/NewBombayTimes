"""
india_trivia_scraper.py (v2)
Pulls entity names + short context snippets from Wikipedia categories,
weighted by real popularity (Pageviews API), for evergreen India-context
crossword content.

Fixes from v1:
1. ALPHABETICAL BIAS: Wikipedia's categorymembers API returns results
   sorted alphabetically by default. v1 fetched only the first 60 members
   per category -- i.e. only A-through-roughly-C titles, every time. Fixed
   by raising cmlimit to the API max (500) and paginating, so we see the
   WHOLE category before popularity-ranking it, instead of an alphabetical
   prefix of it.
2. PERSON NAMES SPLIT INTO PARTS: "Sachin Tendulkar" was producing both
   SACHIN and TENDULKAR as separate answers. Fixed: for person-type
   categories, keep only the surname (last token) as the answer.
3. GENERIC / META WORDS: titles like "List of World Heritage Sites in
   India" aren't real entities -- skip them entirely. Descriptive suffix
   words (TEMPLE, CAVES, FORT, GROUP, MONUMENTS...) are stripped from
   place names so "Kailasa Temple" yields KAILASA, not KAILASA + TEMPLE.
4. MISSING SNIPPETS: many were Wikipedia redirects (e.g. a page title
   that redirects to a section of another page), which broke the simple
   title->extract lookup. Fixed by following the API's normalized/redirect
   mapping back to the original queried title.

Run: python india_trivia_scraper.py
Produces: india_trivia.json, india_word_bank.txt
"""

import json
import re
import time
import urllib.parse
from datetime import datetime, timedelta

import requests

from word_filters import is_droppable_suffix  # shared with scraper.py

API_URL = "https://en.wikipedia.org/w/api.php"
PAGEVIEWS_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"

HEADERS = {
    "User-Agent": "NewBombayTimesCrosswordBot/0.3 (personal hobby project; "
                  "contact: your-email@example.com)"
}

CATEGORIES = {
    "Prime Ministers of India": ("politics", True),
    "Indian independence activists": ("history", True),
    "History of India": ("history", False),
    "Cities and towns in India": ("geography", False),
    "Rivers of India": ("geography", False),
    "World Heritage Sites in India": ("geography", False),
    "Indian festivals": ("culture", False),
    "Indian cuisine": ("culture", False),
    "Indian classical dance": ("culture", False),
    "Indian cricketers": ("cricket", True),
    "Indian film actors": ("cinema", True),
    "Bollywood": ("cinema", False),
    "Indian musicians": ("culture", True),
    "Sportspeople from India": ("sports", True),
}

MEMBERS_PER_CATEGORY_FETCH = 500
TOP_K_PER_CATEGORY = 20
MIN_WORD_LEN = 3
MAX_WORD_LEN = 15
REQUEST_DELAY = 0.15
PAGEVIEWS_MONTHS_BACK = 3

META_TITLE_PATTERNS = [
    r"^List of ", r"^Lists of ", r"^Index of ", r"^Timeline of ",
    r"^Category:", r"^Glossary of ",
]


def get_all_category_members(category):
    """Fetch the FULL category listing via pagination (cmcontinue),
    not just an alphabetical prefix."""
    titles = []
    cmcontinue = None
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{category}",
            "cmlimit": MEMBERS_PER_CATEGORY_FETCH,
            "cmnamespace": 0,
            "format": "json",
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue

        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        for member in data.get("query", {}).get("categorymembers", []):
            titles.append(member["title"])

        cmcontinue = data.get("continue", {}).get("cmcontinue")
        if not cmcontinue or len(titles) >= 2000:  # hard safety cap
            break
        time.sleep(REQUEST_DELAY)

    return titles


def get_extracts(titles):
    """
    Batch-fetch intro extracts, correctly resolving redirects/normalization
    back to the ORIGINAL queried title so lookups don't silently miss.
    """
    extracts = {}
    chunk_size = 50
    for i in range(0, len(titles), chunk_size):
        chunk = titles[i:i + chunk_size]
        params = {
            "action": "query",
            "prop": "extracts",
            "exintro": True,
            "explaintext": True,
            "exsentences": 2,
            "redirects": 1,
            "titles": "|".join(chunk),
            "format": "json",
        }
        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        query = data.get("query", {})
        pages = query.get("pages", {})

        by_final_title = {}
        for page in pages.values():
            title = page.get("title")
            extract = page.get("extract", "")
            if title and extract:
                by_final_title[title] = extract

        for r in query.get("redirects", []):
            if r["to"] in by_final_title:
                by_final_title[r["from"]] = by_final_title[r["to"]]

        for n in query.get("normalized", []):
            if n["to"] in by_final_title:
                by_final_title[n["from"]] = by_final_title[n["to"]]

        extracts.update(by_final_title)
        time.sleep(REQUEST_DELAY)
    return extracts


def get_pageviews(title, months_back=PAGEVIEWS_MONTHS_BACK):
    end = datetime.utcnow().replace(day=1) - timedelta(days=1)
    start = (end.replace(day=1) - timedelta(days=30 * (months_back - 1))).replace(day=1)
    start_str = start.strftime("%Y%m01")
    end_str = end.strftime("%Y%m%d")
    encoded_title = urllib.parse.quote(title.replace(" ", "_"), safe="")
    url = (f"{PAGEVIEWS_URL}/en.wikipedia/all-access/user/"
           f"{encoded_title}/monthly/{start_str}/{end_str}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 404:
            return 0
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return sum(item["views"] for item in items)
    except requests.RequestException:
        return 0


def is_meta_title(title):
    return any(re.match(pat, title) for pat in META_TITLE_PATTERNS)


def clean_token(tok):
    return re.sub(r"[^A-Za-z]", "", tok).upper()


def title_to_words(title, is_person):
    """
    Convert a Wikipedia title into 1 (usually) crossword-answer word(s).
    - Person categories: surname only (last valid token) -- positional
      rule, not a word-list, so it needs no maintenance.
    - Other categories: strip trailing tokens that WordNet identifies as
      generic descriptor words (see is_generic_word), keep what's left.
    """
    title = re.sub(r"\(.*?\)", "", title).strip()  # drop "(disambiguation)"
    title = title.split(",")[0].strip()             # drop ", Ellora"-style suffix
    tokens = [clean_token(t) for t in title.split()]
    tokens = [t for t in tokens if MIN_WORD_LEN <= len(t) <= MAX_WORD_LEN]

    if not tokens:
        return []

    if is_person:
        return [tokens[-1]]  # surname only

    while len(tokens) > 1 and is_droppable_suffix(tokens[-1]):
        tokens = tokens[:-1]

    return tokens


def main():
    all_entries = []

    for category, (topic, is_person) in CATEGORIES.items():
        print(f"Fetching category: {category} ...")
        try:
            titles = get_all_category_members(category)
        except requests.RequestException as e:
            print(f"  FAILED ({e}), skipping category")
            continue

        titles = [t for t in titles if not is_meta_title(t)]
        print(f"  -> {len(titles)} real pages (after removing list/index pages)")
        if not titles:
            continue

        print("  Fetching pageviews for all of them (this is the slow part)...")
        scored_titles = []
        for title in titles:
            views = get_pageviews(title)
            scored_titles.append((title, views))
            time.sleep(REQUEST_DELAY)

        scored_titles.sort(key=lambda t: t[1], reverse=True)
        top_titles = scored_titles[:TOP_K_PER_CATEGORY]
        print(f"  -> top by views: {[f'{t}({v})' for t, v in top_titles[:5]]} ...")

        extracts = get_extracts([t for t, v in top_titles])

        for title, views in top_titles:
            snippet = extracts.get(title, "")
            for word in title_to_words(title, is_person):
                all_entries.append({
                    "word": word,
                    "topic": topic,
                    "source_title": title,
                    "snippet": snippet,
                    "pageviews_3mo": views,
                })

        time.sleep(REQUEST_DELAY)

    seen = {}
    for entry in all_entries:
        existing = seen.get(entry["word"])
        if existing is None or entry["pageviews_3mo"] > existing["pageviews_3mo"]:
            seen[entry["word"]] = entry
    unique_entries = list(seen.values())
    unique_entries.sort(key=lambda e: e["pageviews_3mo"], reverse=True)

    no_snippet = sum(1 for e in unique_entries if not e["snippet"])
    print(f"\nTotal unique candidate words: {len(unique_entries)}")
    print(f"Entries missing snippet: {no_snippet} / {len(unique_entries)}")
    print("\nTop 15 by popularity:")
    for e in unique_entries[:15]:
        print(f"  {e['word']:<15} views={e['pageviews_3mo']:<8} "
              f"topic={e['topic']:<10} from='{e['source_title']}'")

    with open("india_trivia.json", "w") as f:
        json.dump(unique_entries, f, indent=2)
    print("\nWrote india_trivia.json")

    with open("india_word_bank.txt", "w") as f:
        f.write("\n".join(sorted(e["word"] for e in unique_entries)))
    print("Wrote india_word_bank.txt")


if __name__ == "__main__":
    main()
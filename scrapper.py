"""
scraper.py
Pulls today's headlines from Indian + one foreign RSS feed,
extracts candidate crossword-answer words via spaCy NER,
scores them, and writes candidates.json.

Run: python scraper.py
"""

import json
import re
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import feedparser
import spacy

from word_filters import is_generic_word, INDIAN_ADMIN_SUFFIXES

FEEDS = {
    "the_hindu": "https://www.thehindu.com/news/feeder/default.rss",
    "hindustan_times": "https://www.hindustantimes.com/rss/topnews/rssfeed.xml",
    "times_of_india": "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
    "ndtv": "http://feeds.feedburner.com/ndtvnews-top-stories",
    "india_today": "https://www.indiatoday.in/rss/1206584",
    "bbc_world": "http://feeds.bbci.co.uk/news/world/rss.xml",  # foreign context
}

# Entity labels worth pulling as candidate crossword answers
WANTED_LABELS = {"PERSON", "GPE", "ORG", "EVENT", "NORP", "FAC", "LOC"}

MIN_WORD_LEN = 3
MAX_WORD_LEN = 12
LOOKBACK_HOURS = 30  # slightly > 24h to tolerate feed lag

# Countries/entities that are basically ALWAYS in the news -- don't let them
# dominate the daily top-candidates list. We still keep them (low weight)
# rather than dropping entirely, in case one is genuinely the day's big story.
ALWAYS_IN_NEWS_PENALTY = {
    "INDIA", "INDIAN", "CHINA", "CHINESE", "PAKISTAN", "PAKISTANI",
    "RUSSIA", "RUSSIAN", "IRAN", "IRANIAN", "AMERICA", "AMERICAN",
    "USA", "US", "UK", "BRITAIN", "BRITISH",
}
PENALTY_FACTOR = 0.25  # scale their score down to 25%

# When we split multi-word entities into individual tokens, discard tokens
# that are just stopwords/articles (e.g. "The West" -> drop "THE", keep "WEST")
STOPWORDS = {
    "THE", "OF", "AND", "FOR", "TO", "IN", "ON", "AT", "BY", "WITH",
    "A", "AN", "IS", "ARE", "WAS", "WERE", "NEW", "OLD",
}


def fetch_articles():
    """Pull entries from all feeds, keep recent ones, dedupe by title."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    seen_titles = set()
    articles = []

    for source, url in FEEDS.items():
        parsed = feedparser.parse(url)
        for entry in parsed.entries:
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "") or entry.get("description", "")
            if not title or title in seen_titles:
                continue

            # try to get a publish time; if missing, include it anyway (better to
            # over-include on day 1 than silently get zero articles)
            published = None
            if entry.get("published_parsed"):
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            if published and published < cutoff:
                continue

            seen_titles.add(title)
            articles.append({
                "title": title,
                "summary": re.sub("<[^<]+?>", "", summary),  # strip any HTML tags
                "source": source,
                "published": published.isoformat() if published else None,
                "link": entry.get("link", ""),
            })

    return articles


def looks_title_cased(text, threshold=0.7):
    """
    Indian news headlines are frequently written in Title Case ('Trump
    Announces New Tariff Policy'), which confuses spaCy's small model --
    tested empirically: it causes both NER (merging unrelated words into
    one bogus entity span) and even the POS tagger itself (mistagging a
    verb like "Announces" as PROPN) to misfire. Detect this so we can
    normalize it before NER, rather than trusting spaCy on text it's
    known to struggle with.
    """
    words = [w for w in text.split() if w.isalpha() and len(w) > 3]
    if len(words) < 3:
        return False
    capitalized = sum(1 for w in words if w[0].isupper())
    return (capitalized / len(words)) >= threshold


def normalize_for_ner(title, summary):
    """
    Only lowercase the TITLE if it looks Title-Cased, and only the title --
    never the summary, which is normally cased already. Fully lowercasing
    text was tested and rejected: it caused spaCy to miss real entities
    entirely (e.g. "trump announces..." lowercased -> spaCy found NOTHING,
    not even Trump). Restricting normalization to just the title limits
    the damage -- if a real entity's title mention gets suppressed by
    this, it will usually still be caught via the (untouched) summary.
    """
    if looks_title_cased(title):
        title = title.lower()
    return f"{title}. {summary}"


def extract_candidates(articles, nlp):
    """
    Run NER over each article's title+summary.
    Returns list of candidate dicts: word, mentions, sources, snippet.
    """
    scored = defaultdict(lambda: {"mentions": 0, "sources": set(), "snippets": []})

    for art in articles:
        text = normalize_for_ner(art["title"], art["summary"])
        doc = nlp(text)
        for ent in doc.ents:
            if ent.label_ not in WANTED_LABELS:
                continue

            # Build candidate word(s) from the entity.
            # Multi-word entities (e.g. "Reserve Bank of India") are NOT
            # usable as a single crossword answer once concatenated --
            # instead, emit individual token(s) as candidates.
            #
            # TWO layers of per-token filtering, both needed for different
            # reasons (found by testing against real Title-Case headlines,
            # which are common in Indian news and confuse spaCy's NER):
            #
            # 1. POS-tag sanity check (applied to EVERY entity type,
            #    including PERSON): Title-Case headlines sometimes cause
            #    spaCy to merge unrelated words into one bogus entity span
            #    -- e.g. "Sharif Meets Indian Envoy" got tagged as ONE
            #    PERSON entity, dragging the verb "Meets" along with
            #    "Sharif". Even when the entity BOUNDARY is wrong like
            #    this, each token's own POS tag (computed from full
            #    sentence grammar, not just capitalization) stays
            #    reliable -- "Meets" is still correctly tagged VERB. So:
            #    drop any token that isn't grammatically noun-like,
            #    regardless of entity type. Real names are never verbs/
            #    prepositions/determiners, so this is safe for PERSON too.
            #
            # 2. WordNet generic-word filtering (is_generic_word), applied
            #    ONLY to non-PERSON entities as before -- catches real
            #    generic nouns like BANK/MINISTRY/COMMITTEE that pass the
            #    POS check (they're grammatically nouns, just not names).
            #    Still skipped for PERSON entities: WordNet has weak
            #    coverage of contemporary proper nouns (e.g. only knows
            #    "trump" as a card-game term), so applying it there risks
            #    dropping real newsworthy names.
            NAME_LIKE_POS = {"PROPN", "NOUN"}
            words_to_add = []
            for tok in ent:
                w = re.sub(r"[^A-Za-z]", "", tok.text).upper()
                if w in STOPWORDS:
                    continue
                if not (MIN_WORD_LEN <= len(w) <= MAX_WORD_LEN):
                    continue
                if tok.pos_ not in NAME_LIKE_POS:
                    continue
                # Indian admin-suffix check applies regardless of entity
                # type (safe even for PERSON -- no real surname is
                # literally "Pradesh" or "Nadu") -- see word_filters.py
                if w in INDIAN_ADMIN_SUFFIXES:
                    continue
                if ent.label_ != "PERSON" and is_generic_word(w):
                    continue
                words_to_add.append(w)

            for word in words_to_add:
                scored[word]["mentions"] += 1
                scored[word]["sources"].add(art["source"])
                if len(scored[word]["snippets"]) < 3:
                    scored[word]["snippets"].append({
                        "text": art["title"],
                        "link": art["link"],
                        "source": art["source"],
                    })

    candidates = []
    for word, data in scored.items():
        # simple relevance score: more mentions + more distinct sources = more "today"
        score = data["mentions"] + 2 * len(data["sources"])
        if word in ALWAYS_IN_NEWS_PENALTY:
            score = round(score * PENALTY_FACTOR, 2)
        candidates.append({
            "word": word,
            "length": len(word),
            "mentions": data["mentions"],
            "num_sources": len(data["sources"]),
            "score": score,
            "snippets": data["snippets"],
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


def main():
    print("Loading spaCy model...")
    nlp = spacy.load("en_core_web_sm")

    print("Fetching RSS feeds...")
    articles = fetch_articles()
    print(f"  -> {len(articles)} articles pulled")

    print("Extracting candidate words via NER...")
    candidates = extract_candidates(articles, nlp)
    print(f"  -> {len(candidates)} unique candidate words")

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "num_articles": len(articles),
        "candidates": candidates,
    }

    with open("candidates.json", "w") as f:
        json.dump(out, f, indent=2)

    print("Wrote candidates.json")
    print("\nTop 15 candidates:")
    for c in candidates[:15]:
        print(f"  {c['word']:<15} len={c['length']:<3} score={c['score']:<3} "
              f"sources={c['num_sources']}")


if __name__ == "__main__":
    main()
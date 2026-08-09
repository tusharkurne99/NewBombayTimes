"""
word_filters.py
Shared helper: is a word a generic English dictionary word (a "type"),
or a specific named thing (an "instance")? Used to filter multi-word
entity/title splits so generic descriptor words (TEMPLE, BANK, MINISTRY,
COURT...) don't get treated as if they were the specific answer.

See project_log_week1.md section 6.5 for the full reasoning on why this
approach (WordNet instance-hypernym detection) was chosen over word
frequency and POS tagging, both of which were tried and failed on real
test cases.

IMPORTANT CAVEAT (see scraper.py for how this is actually used): this is
reliable for common-noun descriptor words, but WordNet is a static,
somewhat dated resource with weak coverage of contemporary proper nouns
-- e.g. it knows "trump" only as a card-game term, not as a person, so
it would incorrectly flag a newsworthy surname as "generic" if applied
to PERSON entities. Only apply this to non-person entity types (ORG,
FAC, EVENT, etc.) where the contamination pattern is real (generic
institutional/descriptor words), not to PERSON entities.
"""

import nltk

try:
    from nltk.corpus import wordnet as wn
    wn.synsets("test")
except LookupError:
    nltk.download("wordnet")
    from nltk.corpus import wordnet as wn


def is_generic_word(word):
    """
    True if `word` is a generic English dictionary word (a "type") that
    should NOT be treated as a specific/distinctive answer on its own.
    False if it's either unknown to WordNet (likely a proper noun WordNet
    just doesn't have) or WordNet explicitly marks it as a named instance.
    """
    synsets = wn.synsets(word.lower(), pos=wn.NOUN)
    if not synsets:
        return False
    is_named_instance = any(s.instance_hypernyms() for s in synsets)
    return not is_named_instance


def is_safe_context_free_word(word, zipf_score, min_famous_zipf=3.8):
    """
    For GENERIC FILLER words only (no news/trivia snippet backing them) --
    is this word safe to hand to a clue-writing LLM with no context at all?

    Different question from is_generic_word() above, and the two functions
    give OPPOSITE answers on purpose for words like "Tendulkar": as a
    trivia answer WITH a snippet, an unrecognized-by-WordNet proper noun
    is fine (is_generic_word -> False -> keep, the snippet gives the LLM
    what it needs). As a plain filler word with NO snippet, the same
    "unknown to WordNet" fact means the LLM has nothing to ground a clue
    in at all, and empirically hallucinates (e.g. "PAINE" -> invented
    "French delicacy"; it's actually only a WordNet *instance* sense for
    Thomas Paine, no generic meaning exists).

    Rule, calibrated against real failures (PAINE, KYRIE) vs. real
    successes we want to keep (EGYPT, INDIA, DELHI, AFRICA):
    - Zero WordNet synsets at all (e.g. KYRIE) -> UNSAFE. No dictionary
      grounding and no snippet either -- pure hallucination risk.
    - Every noun sense is an "instance" (a specific named thing, e.g.
      PAINE = only Thomas Paine, no generic word "paine" exists) -> only
      safe if it's high-frequency enough to be something the LLM would
      plausibly know well from training (world capitals, famous countries)
      rather than a specific obscure historical figure. zipf >= 3.8 is
      the calibrated cutoff (keeps EGYPT/INDIA/DELHI/AFRICA/SHAKESPEARE,
      drops PAINE).
    - Otherwise (has a genuine generic/common-noun sense) -> UNSAFE... no,
      SAFE: it's a real dictionary word, the LLM can define it.
    """
    synsets = wn.synsets(word.lower())
    if not synsets:
        return False

    noun_synsets = [s for s in synsets if s.pos() == "n"]
    if not noun_synsets:
        return True  # only verb/adj/adv senses -- those aren't "instances"

    all_instance_only = all(bool(s.instance_hypernyms()) for s in noun_synsets)
    if not all_instance_only:
        return True  # has at least one real generic/common-noun sense

    return zipf_score >= min_famous_zipf


# Small, closed, deliberately hand-maintained exception -- same category as
# scraper.py's ALWAYS_IN_NEWS_PENALTY, not the open-ended "generic English
# descriptor" problem WordNet filtering was built to replace.
#
# Indian administrative-unit suffix morphemes (Tamil "Nadu" = land/country,
# Hindi/Sanskrit "Pradesh" = province/state) are not English words, so
# WordNet has zero knowledge of them and is_generic_word() lets them
# through untouched -- but they are essentially NEVER used standalone in
# English text ("Nadu" alone means nothing to an English speaker; it's
# always "Tamil Nadu"). Stripping these as trailing tokens is safe and
# needs no ongoing maintenance: this is a small, finite, well-understood
# linguistic category (Indian state-name suffixes), not an open-ended set
# of "whatever descriptor word might appear next."
INDIAN_ADMIN_SUFFIXES = {
    "NADU", "PRADESH", "DESH",
    # Common Indian architectural/toponymic suffix morphemes -- same
    # category as the state-name suffixes above (transliterated Hindi/
    # Urdu/Tamil words meaning "palace," "building," "tower," etc., not
    # real English dictionary words, so WordNet has zero knowledge of
    # them and is_generic_word() lets them through unfiltered). Found via
    # the same failure pattern as NADU: "Taj Mahal" -> spurious standalone
    # "MAHAL" answer with a clue clearly describing the Taj Mahal
    # specifically. See project log part 2/3 for the full NADU/MAHAL
    # discussion -- this list is expected to grow as new instances of the
    # same pattern are found; that's fine, it's still a closed, well-
    # understood linguistic category, not an open-ended one.
    "MAHAL", "BHAVAN", "BAGH", "MINAR", "NAGAR", "GANJ", "GARH", "PURAM",
}


def is_droppable_suffix(word):
    """True if `word` is a generic descriptor (via WordNet) OR one of the
    small set of Indian administrative-unit suffixes above."""
    return is_generic_word(word) or word.upper() in INDIAN_ADMIN_SUFFIXES


# Small, closed, deliberately hand-maintained exception list -- same
# justified-exception category as ALWAYS_IN_NEWS_PENALTY and
# INDIAN_ADMIN_SUFFIXES above, NOT the open-ended "generic descriptor
# word" problem WordNet filtering replaced. These are real, valid,
# technically-correct dictionary/crossword words that are nonetheless
# not appropriate for a general-audience daily puzzle, either because
# they're mildly vulgar (ASS) or because they carry a strong, unrelated,
# distressing modern association that would be jarring or in poor taste
# to see as a crossword answer regardless of the word's older/original
# meaning (ISIS as the Egyptian goddess; NAZI, KKK as historical/political
# terms). Found by inspection of real generated puzzles, not exhaustively
# researched -- expect to add to this occasionally, same as the other
# small exception lists in this file.
SENSITIVE_WORDS = {
    "ISIS", "ASS", "NAZI", "NAZIS", "KKK", "RAPE", "RAPED", "RAPIST",
}


def is_sensitive_word(word):
    return word.upper() in SENSITIVE_WORDS
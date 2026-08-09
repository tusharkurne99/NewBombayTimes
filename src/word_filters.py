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


MIN_RECOGNIZABLE_ZIPF = 3.0  # same "average adult would recognize this" bar
                              # used by build_word_bank.py's MIN_ZIPF


def _has_vowel_or_y(word):
    return any(ch in "AEIOUY" for ch in word.upper())


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
    - No vowel (or Y) AND below the general recognizability zipf bar ->
      UNSAFE. Found via real puzzle output: "SSSS" and "WSWS" both slipped
      through every earlier check because NLTK's wn.synsets() applies
      morphological stripping (assuming a trailing "s" is a plural) BEFORE
      matching against WordNet -- "ssss" strips to "sss", which happens to
      collide with the real (unrelated) lemma "SSS" (Selective Service
      System); "wsws" strips to "wsw", colliding with "WSW" (west-
      southwest). Both matches are real WordNet entries, so the earlier
      "has a generic sense" check let them through -- the match was just
      for a different word than the one actually being validated. A pure
      "no vowel" rule would also reject legitimate common abbreviations
      (DVD, TV, PHD all have zipf >= 4), so this only fires when a word is
      BOTH vowel-less AND below the recognizability threshold -- which
      cleanly separates SSSS/WSWS (zipf ~1.4-1.9) from DVD/TV/PHD
      (zipf >= 4) without a hand-maintained exception list either way.
    - Zero WordNet synsets at all (e.g. KYRIE) -> UNSAFE. No dictionary
      grounding and no snippet either -- pure hallucination risk.
    - Every noun sense is an "instance" (a specific named thing, e.g.
      PAINE = only Thomas Paine, no generic word "paine" exists) -> only
      safe if it's high-frequency enough to be something the LLM would
      plausibly know well from training (world capitals, famous countries)
      rather than a specific obscure historical figure. zipf >= 3.8 is
      the calibrated cutoff (keeps EGYPT/INDIA/DELHI/AFRICA/SHAKESPEARE,
      drops PAINE).
    - Otherwise (has a genuine generic/common-noun sense) -> SAFE: it's a
      real dictionary word, the LLM can define it.
    """
    if not _has_vowel_or_y(word) and zipf_score < MIN_RECOGNIZABLE_ZIPF:
        return False

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


# Content-sensitivity exclusion list -- NOT the small hand-maintained
# exception lists above (ALWAYS_IN_NEWS_PENALTY, INDIAN_ADMIN_SUFFIXES):
# those are closed linguistic categories where a short list is provably
# complete-enough. Profanity/slurs are the opposite -- genuinely
# open-ended -- so instead of relying on words noticed by chance while
# reviewing puzzle output (the original version of this list: just 8
# words, "found by inspection," explicitly not exhaustive), the bulk of
# this set is seeded from a maintained public source: the LDNOOBW list
# (github.com/LDNOOBW/List-of-Dirty-Naughty-Obscene-and-Otherwise-Bad-Words),
# filtered down to single alphabetic tokens of length 3-15 (the only kind
# that can appear as a crossword answer -- multi-word phrases in the
# source list are structurally irrelevant here). ~275 words.
#
# This deliberately errs toward over-blocking: several entries (ANAL,
# ANUS, SEX, TIT) have legitimate anatomical/biological meanings and have
# appeared as real answers in mainstream published crosswords. For a
# general-audience daily puzzle the downside of never using them is
# negligible; the downside of one slipping through as an unreviewed
# filler-word answer is not. If a specific word here turns out to be
# wanted, remove it deliberately -- don't work around this list.
#
# Kept separately below: historical/political terms (NAZI, KKK, ISIS) that
# the LDNOOBW list doesn't cover because they're not profanity -- they're
# real dictionary/proper-noun words that carry a distressing modern
# association regardless of true original meaning (ISIS as the Egyptian
# goddess is technically valid and was an actual early false-positive risk
# fixed by hand). Still expected to grow by inspection, same as before --
# the public list handles profanity/slurs, this handles everything else.
SENSITIVE_WORDS = {
    "ACROTOMOPHILIA", "ANAL", "ANILINGUS", "ANUS", "APESHIT", "ARSEHOLE", "ASS", "ASSHOLE",
    "ASSMUNCH", "AUTOEROTIC", "BABELAND", "BANGBROS", "BANGBUS", "BAREBACK", "BARENAKED", "BASTARD",
    "BASTARDO", "BASTINADO", "BBW", "BDSM", "BEANER", "BEANERS", "BEASTIALITY", "BESTIALITY",
    "BIMBOS", "BIRDLOCK", "BITCH", "BITCHES", "BLOWJOB", "BLUMPKIN", "BOLLOCKS", "BONDAGE",
    "BONER", "BOOB", "BOOBS", "BUKKAKE", "BULLDYKE", "BULLSHIT", "BUNGHOLE", "BUSTY",
    "BUTT", "BUTTCHEEKS", "BUTTHOLE", "CAMGIRL", "CAMSLUT", "CAMWHORE", "CARPETMUNCHER", "CIALIS",
    "CIRCLEJERK", "CLIT", "CLITORIS", "CLUSTERFUCK", "COCK", "COCKS", "COON", "COONS",
    "COPROLAGNIA", "COPROPHILIA", "CORNHOLE", "CREAMPIE", "CUM", "CUMMING", "CUMSHOT", "CUMSHOTS",
    "CUNNILINGUS", "CUNT", "DARKIE", "DATERAPE", "DEEPTHROAT", "DENDROPHILIA", "DICK", "DILDO",
    "DINGLEBERRIES", "DINGLEBERRY", "DOGGIESTYLE", "DOGGYSTYLE", "DOLCETT", "DOMINATION", "DOMINATRIX", "DOMMES",
    "DVDA", "ECCHI", "EJACULATION", "EROTIC", "EROTISM", "ESCORT", "EUNUCH", "FAG",
    "FAGGOT", "FECAL", "FELCH", "FELLATIO", "FELTCH", "FEMDOM", "FIGGING", "FINGERBANG",
    "FINGERING", "FISTING", "FOOTJOB", "FROTTING", "FUCK", "FUCKIN", "FUCKING", "FUCKTARDS",
    "FUDGEPACKER", "FUTANARI", "GANGBANG", "GENITALS", "GOATCX", "GOATSE", "GOKKUN", "GOODPOOP",
    "GOREGASM", "GROPE", "GURO", "HANDJOB", "HARDCORE", "HENTAI", "HOMOEROTIC", "HONKEY",
    "HOOKER", "HORNY", "HUMPING", "INCEST", "INTERCOURSE", "JAILBAIT", "JIGABOO", "JIGGABOO",
    "JIGGERBOO", "JIZZ", "JUGGS", "KIKE", "KINBAKU", "KINKSTER", "KINKY", "KNOBBING",
    "LIVESEX", "LOLITA", "LOVEMAKING", "MASTURBATE", "MASTURBATING", "MASTURBATION", "MILF", "MONG",
    "MOTHERFUCKER", "MUFFDIVING", "NAMBLA", "NAWASHI", "NEGRO", "NEONAZI", "NIGGA", "NIGGER",
    "NIMPHOMANIA", "NIPPLE", "NIPPLES", "NSFW", "NUDE", "NUDITY", "NUTTEN", "NYMPHO",
    "NYMPHOMANIA", "OCTOPUSSY", "OMORASHI", "ORGASM", "ORGY", "PAEDOPHILE", "PAKI", "PANTIES",
    "PANTY", "PEDOBEAR", "PEDOPHILE", "PEGGING", "PENIS", "PIKEY", "PISSING", "PISSPIG",
    "PLAYBOY", "PONYPLAY", "POOF", "POON", "POONTANG", "POOPCHUTE", "PORN", "PORNO",
    "PORNOGRAPHY", "PTHC", "PUBES", "PUNANY", "PUSSY", "QUEAF", "QUEEF", "QUIM",
    "RAGHEAD", "RAPE", "RAPED", "RAPING", "RAPIST", "RECTUM", "RIMJOB", "RIMMING", "SADISM",
    "SANTORUM", "SCAT", "SCHLONG", "SCISSORING", "SEMEN", "SEX", "SEXCAM", "SEXO",
    "SEXUAL", "SEXUALITY", "SEXUALLY", "SEXY", "SHEMALE", "SHIBARI", "SHIT", "SHITBLIMP",
    "SHITTY", "SHOTA", "SHRIMPING", "SKEET", "SLANTEYE", "SLUT", "SMUT", "SNATCH",
    "SNOWBALLING", "SODOMIZE", "SODOMY", "SPASTIC", "SPIC", "SPLOOGE", "SPOOGE", "SPUNK",
    "STRAPON", "STRAPPADO", "SUCK", "SUCKS", "SWASTIKA", "SWINGER", "THREESOME", "THROATING",
    "THUMBZILLA", "TIT", "TITS", "TITTIES", "TITTY", "TOPLESS", "TOSSER", "TOWELHEAD",
    "TRANNY", "TRIBADISM", "TUBGIRL", "TUSHY", "TWAT", "TWINK", "TWINKIE", "UNDRESSING",
    "UPSKIRT", "UROPHILIA", "VAGINA", "VIAGRA", "VIBRATOR", "VORAREPHILIA", "VOYEUR", "VOYEURWEB",
    "VOYUER", "VULVA", "WANK", "WETBACK", "WHORE", "WORLDSEX", "XXX", "YAOI",
    "YIFFY", "ZOOPHILIA",
    # Historical/political terms, not from the profanity list above --
    # see comment block for why these are handled separately.
    "ISIS", "NAZI", "NAZIS", "KKK",
}


def is_sensitive_word(word):
    return word.upper() in SENSITIVE_WORDS
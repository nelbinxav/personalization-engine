"""Deterministic evidence checks. No model call, so no tokens.

The chain asks Claude to quote evidence and name a source. A model can name a
source that returned nothing, or "quote" something no source says. These
functions check the claim against the text the model was actually given.

Two links are checked:
  fact  (dossier item)  -> the source text it claims to come from
  angle / fit evidence  -> a dossier item
A fact is a paraphrase, so it is held to its specifics: every number and proper
noun in it must appear in the source. An angle's evidence is a quote of a fact,
so it has to be close to one fact's wording.
"""
import re

from app.models.prospect import Fact

_MONTHS = {
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "jan", "feb", "mar", "apr",
    "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
}
_DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
_NUMBER = re.compile(r"\$?\d[\d,.]*\s?(?:%|[kKmMbB]\b)?")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#&.']*")
_DASHES = str.maketrans({"–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"'})
_MD = re.compile(r"[*_`>#]+")

# Share of a fact's specifics that must be found in its source.
_SPECIFIC_MIN = 0.8
# Share of the words of a quote that must be found in the single fact it cites.
_QUOTE_MIN = 0.7
# Words this short or this common carry no evidence either way.
_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "their", "they", "has", "have",
    "was", "were", "are", "its", "into", "about", "over", "than", "also", "will", "been",
    "who", "what", "which", "when", "his", "her", "our", "your", "not", "but", "can",
    # Words that describe where a fact was found, not what it says.
    "linkedin", "profile", "website", "page", "section", "headline", "post", "posts",
    "podcast", "news", "says", "lists", "shows", "states",
}


def normalise(text: str) -> str:
    text = _MD.sub(" ", (text or "").translate(_DASHES)).lower()
    return re.sub(r"\s+", " ", text).strip()


def _stem(word: str) -> str:
    word = word.strip(".'-").lower()
    for suffix in ("'s", "ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.translate(_DASHES)) if w]


def _numbers(text: str) -> set[str]:
    return {re.sub(r"[\s,$]", "", m.group(0)).rstrip(".").lower() for m in _NUMBER.finditer(text)} - {""}


_NAME_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+#&']*(?:\.[A-Za-z0-9]+)*|[.!?:\n]")


def _proper_nouns(text: str) -> set[str]:
    """Capitalised words that are not simply starting a sentence, and acronyms."""
    found: set[str] = set()
    sentence_start = True
    for token in _NAME_TOKEN.finditer(text.translate(_DASHES)):
        word = token.group(0)
        if word in (".", "!", "?", ":", "\n"):
            sentence_start = True
            continue
        low = word.lower().strip(".'-")
        is_name = (word[0].isupper() and not sentence_start) or (len(word) > 1 and word.isupper())
        sentence_start = False
        if is_name and low not in _MONTHS and low not in _DAYS and low not in _STOP:
            found.add(_stem(low))
    return found


def _content_words(text: str) -> set[str]:
    return {_stem(w) for w in _words(text) if len(w) > 3 and w.lower() not in _STOP}


def _in_source(token: str, source_text: str, source_words: set[str]) -> bool:
    if token[0].isdigit():
        # Whole numbers only: "45" is not in "450".
        return re.search(rf"(?<![\d.]){re.escape(token)}(?!\d)", source_text) is not None
    # "APIs" in a fact is "API" in the source.
    return token in source_words or token in source_text or token.rstrip("s") in source_words


def fact_problem(fact: Fact, source_text: str | None) -> str | None:
    """Why a dossier item cannot be trusted, or None when it is grounded.

    `source_text` is what the model read for fact.source_key, None when no such
    source was given or it came back empty.
    """
    if source_text is None:
        return f"names source '{fact.source_key}', which held no research"

    haystack = normalise(source_text)
    source_words = {_stem(w) for w in _words(source_text)}
    specifics = _numbers(fact.text) | _proper_nouns(fact.text)
    if fact.source_key == "linkedin_posts":
        # The dates are worked out from LinkedIn's age stamps ("2w"), so they
        # are not in the text; the day, month and year are not evidence.
        specifics = {t for t in specifics if not re.fullmatch(r"(?:19|20)\d\d|\d{1,2}", t)}
    missing = [t for t in specifics if not _in_source(t, re.sub(r"(?<=\d),(?=\d)|\$", "", haystack), source_words)]
    if specifics and (len(specifics) - len(missing)) / len(specifics) < _SPECIFIC_MIN:
        return f"{', '.join(sorted(missing)[:4])} not found in '{fact.source_key}'"

    words = _content_words(fact.text)
    if not specifics and words:
        share = len(words & source_words) / len(words)
        if share < 0.5:
            return f"wording not found in '{fact.source_key}'"
    return None


def match_fact(quote: str, facts: list[Fact]) -> Fact | None:
    """The one dossier item a quoted piece of evidence comes from, or None."""
    wanted = normalise(quote)
    if not wanted:
        return None
    words = _content_words(quote)
    best: tuple[float, Fact | None] = (0.0, None)
    for fact in facts:
        have = normalise(fact.text)
        if wanted in have or have in wanted:
            return fact
        if not words:
            continue
        share = len(words & _content_words(fact.text)) / len(words)
        if share > best[0]:
            best = (share, fact)
    return best[1] if best[0] >= _QUOTE_MIN else None


_BAD_DASH = re.compile("[\u2013\u2014]")
# Phrases the writing prompt bans, checked here so a slip costs a re-ask rather
# than a sent message.
_BANNED = re.compile(
    r"\b(?:impressive|great|love what you|noticed|came across|caught my eye|stood out|"
    r"reach out|hope this finds you|exciting|thrilled|leverage|solutions|synergy|free|"
    r"guaranteed|exclusive|limited time|act now|game-changer|revolutioni[sz]e|seamless|"
    r"unlock|elevate|streamline|cutting-edge|robust|tailored|in today's|following up|"
    r"circling back|touching base|my name is)\b",
    re.IGNORECASE,
)
# Naming where the research came from. Only a prospect's own post may be named.
_REVEALS_RESEARCH = re.compile(
    r"\b(?:linkedin|your (?:website|profile|headline|bio|about section)|i saw|i read|i found)\b",
    re.IGNORECASE,
)


def copy_problems(text: str, evidence: list[str], own_post: bool = False) -> list[str]:
    """Rules about the written line that code can check as well as the model.

    A number is allowed only if the evidence it rests on contains it; a figure
    about a prospect that no source gave is the most damaging thing to send.
    """
    problems: list[str] = []
    if _BAD_DASH.search(text):
        problems.append("Contains an em dash or en dash; use a comma or a full stop.")
    if "!" in text:
        problems.append("Contains an exclamation mark.")
    banned = sorted({m.group(0).lower() for m in _BANNED.finditer(text)})
    if banned:
        problems.append(f"Uses banned wording: {', '.join(banned)}.")
    if not own_post and _REVEALS_RESEARCH.search(text):
        problems.append(
            "Names where the research came from. State the fact as plain knowledge; "
            "only the prospect's own recent post may be referred to as a post."
        )
    banned = sorted({m.group(0).lower() for m in _BANNED.finditer(text)})
    if banned:
        problems.append(f"Uses banned wording: {', '.join(banned)}.")
    if not own_post and _REVEALS_RESEARCH.search(text):
        problems.append(
            "Names where the research came from. State the fact as plain knowledge; "
            "only the prospect's own recent post may be referred to as a post."
        )
    allowed = set().union(*(_numbers(e) for e in evidence)) if evidence else set()
    invented = sorted(n for n in _numbers(text) if n not in allowed)
    if invented:
        problems.append(
            f"Contains {', '.join(invented)}, which the cited evidence does not. "
            "Use only numbers copied from it, or none."
        )
    return problems


# Everyday abbreviations that are not a claim about the prospect. Platform and
# cloud names (aws, gcp, sql) are claims, so they are not here: they must be
# found in one of the tiers below.
_GENERIC_ACRONYMS = {
    "ai", "ml", "llm", "llms", "it", "ceo", "cto", "cio", "cdo", "vp", "roi", "saas", "api", "apis",
}


class _Text:
    """A body of text searched for numbers and names."""

    def __init__(self, text: str) -> None:
        self.norm = re.sub(r"(?<=\d),(?=\d)|\$", "", normalise(text))
        self.words = {_stem(w) for w in _words(text)}

    def has(self, token: str) -> bool:
        return _in_source(token, self.norm, self.words)


def unsupported_in_line(
    line: str, *, prospect: str, dossier: str, research: dict[str, str]
) -> list[str]:
    """Things a written line asserts that nothing it was given supports.

    A name (a company, product, platform or technology, which is how a proper
    noun reads in a line) is supported by, in order: the prospect's own details,
    the stage 1 dossier, or the original research text. The dossier is a
    compact selection, so a name it left out is still real if the research says
    it. A name found in none of them is rejected.

    A number must be in the research itself, not only in the dossier item that
    quoted it.
    """
    corpus = _Text(" ".join(research.values()))
    tiers = [_Text(prospect), _Text(dossier), corpus]
    problems: list[str] = []
    missing_numbers = sorted(n for n in _numbers(line) if not corpus.has(n))
    if missing_numbers:
        problems.append(f"{', '.join(missing_numbers)} is not in any research source.")
    missing_names = sorted(
        t
        for t in _proper_nouns(line)
        if t not in _GENERIC_ACRONYMS and not any(tier.has(t) for tier in tiers)
    )
    if missing_names:
        problems.append(f"Names {', '.join(missing_names)}, which the research does not mention.")
    return problems

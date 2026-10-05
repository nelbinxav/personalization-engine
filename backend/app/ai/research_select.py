"""Choose which paragraphs of a source the model reads. Deterministic, no model.

Taking the first N characters of a page mostly reads its cookie banner and
navigation. This keeps the paragraphs most likely to matter instead, in their
original order, and leaves the rest of the source out of the prompt (it is
still stored and exported whole).

What counts as relevant comes from the campaign (`relevance_terms` in
Settings), not from this file. Without terms only generic signals are used.
"""
import re

# Words that mark a paragraph as news about the company or person whatever the
# campaign sells.
_EVENT_WORDS = re.compile(
    r"\b(?:launch\w*|announc\w*|raised|funding|acqui\w*|merger|partner\w*|hiring|appointed|"
    r"joined|released|introduc\w*|expan\w*|opened|selected|awarded)\b",
    re.IGNORECASE,
)
_BOILERPLATE = re.compile(
    r"cookie|consent|gdpr|ccpa|we value your privacy|accept all|reject all|manage preferences|"
    r"privacy (?:policy|preference|center)|terms (?:of use|and conditions|of service)|"
    r"all rights reserved|©|skip to (?:main )?content|sign in|log in|subscribe to our|"
    r"follow us|powered by|back to top",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b20\d\d\b")
_DIGIT = re.compile(r"\d")
_PROPER = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][A-Za-z0-9+#]{2,}\b")
_MAX_BLOCK = 900


def _blocks(text: str) -> list[str]:
    """Paragraphs; one longer than _MAX_BLOCK (a feed, a page with no blank
    lines) is split at its lines, or at a fixed width when it has none."""
    parts: list[str] = []
    for block in (b.strip() for b in re.split(r"\n\s*\n", text)):
        if not block:
            continue
        if len(block) <= _MAX_BLOCK:
            parts.append(block)
        elif "\n" in block:
            parts.extend(line.strip() for line in block.splitlines() if line.strip())
        else:
            parts.extend(block[i : i + _MAX_BLOCK] for i in range(0, len(block), _MAX_BLOCK))
    return parts


def terms_pattern(terms: list[str]) -> re.Pattern | None:
    cleaned = [t.strip() for t in terms if t and t.strip()]
    if not cleaned:
        return None
    return re.compile("|".join(re.escape(t) for t in cleaned), re.IGNORECASE)


def score(block: str, position: int, anchors: list[str], terms: re.Pattern | None) -> float:
    low = block.lower()
    total = 0.0
    if any(anchor in low for anchor in anchors):
        total += 3  # names the person or their company: identity evidence
    if terms:
        total += min(len(terms.findall(block)), 4) * 1.5
    total += min(len(_EVENT_WORDS.findall(block)), 2) * 0.75
    if _YEAR.search(block):
        total += 1  # dated: an event, not a standing description
    elif _DIGIT.search(block):
        total += 0.5
    total += min(len(_PROPER.findall(block)), 3) * 0.4  # products, tools, named things
    if block.startswith("#"):
        total += 1
    if len(block.split()) >= 12:
        total += 1  # a substantive sentence, not a menu item
    if len(block) < 25:
        total -= 1.5
    if _BOILERPLATE.search(block):
        total -= 4
    total += max(0.0, 2 - position * 0.15)  # earlier is slightly better
    return total


def select_paragraphs(
    text: str, budget: int, anchors: list[str], terms: list[str] | None = None
) -> str:
    """`text` cut to about `budget` characters by dropping its lowest-scoring
    paragraphs. Text already within the budget comes back untouched."""
    if budget <= 0 or len(text) <= budget:
        return text
    parts = _blocks(text)
    pattern = terms_pattern(terms or [])
    anchors = [a.lower() for a in anchors if a and len(a) > 2]
    # Index breaks ties, so identical input always gives identical output.
    scores = [score(part, i, anchors, pattern) for i, part in enumerate(parts)]
    ranked = sorted(range(len(parts)), key=lambda i: (-scores[i], i))
    keep: set[int] = set()
    used = 0
    for i in ranked:
        if scores[i] < 0 and keep:
            break  # boilerplate and menu lines only ever fill an otherwise empty source
        cost = len(parts[i]) + 2
        if used + cost <= budget:
            keep.add(i)
            used += cost
    if not keep:  # every paragraph alone is over budget: take the best, cut to fit
        return parts[ranked[0]][:budget].rstrip()
    return "\n\n".join(parts[i] for i in sorted(keep))

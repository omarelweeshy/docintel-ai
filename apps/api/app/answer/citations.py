"""Sentence-level citations: locate the supporting span in each cited chunk and check support.

The support check here is lexical and deliberately conservative about numbers: every number,
code or date in an answer sentence must appear in the text it cites, and most of its content
words must too. It catches the most damaging failure for policy documents (a wrong number or
deadline) without any extra model. It cannot judge paraphrase or negation; an NLI verifier is the
planned replacement and the evaluation reports how often this check is wrong.
"""

import re
import unicodedata
from dataclasses import dataclass

_TOKEN = re.compile(r"[0-9a-z]+(?:[.,:/\-][0-9a-z]+)*")
# A sentence ends at . ! ? ; followed by whitespace, so "1.1" and "e.g.," do not split it.
_SENTENCE = re.compile(r"\S.*?(?:[.!?;](?=\s|$)|\n|$)", re.S)
STOPWORDS = frozenset(
    """a about above after again all also am an and any are as at be because been before being
    below between both but by can could did do does doing down during each either few for from
    further had has have having he her here hers him his how i if in into is it its itself just
    may me might more most must my no nor not now of off on once only or other our out over own
    per same shall she should so some such than that the their them then there these they this
    those through to too under until up upon very was we were what when where which while who
    whom why will with within without would you your according document documents states stated
    says said provided text passage passages""".split()
)


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # 1,842 -> 1842
    return text.replace("%", " percent ")


def content_tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(_normalise(text)) if t not in STOPWORDS]


def number_tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(_normalise(text)) if any(ch.isdigit() for ch in t)}


def _stem(token: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    score: float


def best_span(sentence: str, source: str, max_sentences: int = 2) -> Span:
    """Character range of the one or two consecutive source sentences that share the most content
    words with the answer sentence. Falls back to the whole source when nothing overlaps."""
    wanted = {_stem(t) for t in content_tokens(sentence)}
    pieces = [(m.start(), m.end()) for m in _SENTENCE.finditer(source) if m.group().strip()]
    if not wanted or not pieces:
        return Span(0, len(source), 0.0)
    best = Span(0, len(source), 0.0)
    for i in range(len(pieces)):
        for width in range(1, max_sentences + 1):
            if i + width > len(pieces):
                break
            start, end = pieces[i][0], pieces[i + width - 1][1]
            have = {_stem(t) for t in content_tokens(source[start:end])}
            # Prefer the shortest window with the highest overlap.
            score = len(wanted & have) / len(wanted) - 0.01 * (width - 1)
            if score > best.score:
                best = Span(start, end, score)
    # Trim leading whitespace so highlights start on a character.
    text = source[best.start : best.end]
    lead = len(text) - len(text.lstrip())
    return Span(best.start + lead, best.end, round(max(best.score, 0.0), 3))


@dataclass(frozen=True)
class Support:
    supported: bool
    coverage: float
    missing_numbers: list[str]


def check_support(sentence: str, cited_texts: list[str], min_coverage: float = 0.5) -> Support:
    """Lexical support of one answer sentence by the full text of the chunks it cites."""
    evidence = " ".join(cited_texts)
    have_numbers = number_tokens(evidence)
    missing = sorted(n for n in number_tokens(sentence) if n not in have_numbers)
    words = [_stem(t) for t in content_tokens(sentence) if not any(c.isdigit() for c in t)]
    have = {_stem(t) for t in content_tokens(evidence)}
    coverage = sum(1 for w in words if w in have) / len(words) if words else 1.0
    return Support(not missing and coverage >= min_coverage, round(coverage, 3), missing)

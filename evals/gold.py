"""Gold-evidence matching shared by the dataset checker and the eval harness.

Gold evidence is stored as quotes, not chunk ids, so the same dataset works for every chunker
and parser. A retrieved chunk is a hit for one evidence item when the quote's tokens appear in
the chunk, in order, at a rate of at least CONTAINMENT_THRESHOLD, and (for PDFs) the page agrees.
In-order matching tolerates tokens that a parser interleaves into the text, such as watermarks.
"""

import re
import unicodedata

CONTAINMENT_THRESHOLD = 0.8

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).casefold()
    # Typographic quotes and dashes become separators, like every other non-alphanumeric char.
    return [t for t in _NON_ALNUM.split(text) if t]


def lcs_length(a: list[str], b: list[str]) -> int:
    """Length of the longest common subsequence of two token lists (a should be the short one)."""
    if not a or not b:
        return 0
    previous = [0] * (len(a) + 1)
    for token in b:
        current = [0] * (len(a) + 1)
        for i, quote_token in enumerate(a, 1):
            if quote_token == token:
                current[i] = previous[i - 1] + 1
            else:
                current[i] = max(previous[i], current[i - 1])
        previous = current
    return previous[-1]


def containment(quote: str | list[str], text: str | list[str]) -> float:
    """Share of quote tokens found in order in text. 1.0 means the whole quote is present."""
    q = tokens(quote) if isinstance(quote, str) else quote
    t = tokens(text) if isinstance(text, str) else text
    if not q:
        return 0.0
    # Fast reject: the in-order match can never exceed the share of quote tokens present at all.
    # Below the threshold the exact value does not matter to any caller, so report 0.
    present = set(t)
    if sum(1 for tok in q if tok in present) / len(q) < CONTAINMENT_THRESHOLD:
        return 0.0
    return lcs_length(q, t) / len(q)


def evidence_hit(
    evidence: dict[str, object], doc: str, page: int | None, text: str | list[str]
) -> bool:
    if evidence["doc"] != doc:
        return False
    gold_page = evidence.get("page")
    if gold_page is not None and page is not None and gold_page != page:
        return False
    quote = evidence.get("quote")
    if isinstance(quote, str):
        return containment(quote, text) >= CONTAINMENT_THRESHOLD
    required = evidence.get("tokens")
    if isinstance(required, list):
        # Token evidence is for cells that parsers garble: every token must appear somewhere.
        present = set(tokens(text) if isinstance(text, str) else text)
        return all(tok in present for item in required for tok in tokens(str(item)))
    raise ValueError("evidence needs a quote or tokens")

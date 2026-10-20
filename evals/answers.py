"""Deterministic answer scoring: gold alias groups and forbidden-content checks.

An answer is correct when every required group has at least one alias whose tokens appear as a
contiguous run in the answer's tokens. Numbers are normalised first ("1,842" -> "1842",
"30%" -> "30 percent") so formatting differences do not count as errors. This is a lenient,
lexical matcher; the eval report states how often it disagrees with a human on an audit sample.
"""

import re
import unicodedata

_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")
_PERCENT = re.compile(r"\s*%")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def answer_tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = _THOUSANDS.sub("", text)
    text = _PERCENT.sub(" percent", text)
    return [t for t in _NON_ALNUM.split(text) if t]


def _contains_run(haystack: list[str], needle: list[str]) -> bool:
    if not needle:
        return False
    n = len(needle)
    return any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def matches_required(answer: str, required: list[list[str]]) -> bool:
    tokens = answer_tokens(answer)
    return all(
        any(_contains_run(tokens, answer_tokens(alias)) for alias in group) for group in required
    )


def forbidden_hits(answer: str, forbidden: list[str]) -> list[str]:
    """Forbidden items are plain substrings (case-insensitive) or regexes prefixed with 're:'."""
    hits = []
    for item in forbidden:
        if item.startswith("re:"):
            if re.search(item[3:], answer):
                hits.append(item)
        elif item.casefold() in answer.casefold():
            hits.append(item)
    return hits

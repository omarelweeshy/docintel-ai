from evals.answers import answer_tokens, forbidden_hits, matches_required
from evals.gold import containment, evidence_hit, tokens
from evals.metrics import bootstrap_ci, paired_bootstrap_delta, score_turn


def test_tokens_split_identifiers_and_drop_punctuation() -> None:
    assert tokens("PR.DS-11: Backups") == ["pr", "ds", "11", "backups"]


def test_containment_tolerates_interleaved_tokens() -> None:
    # Watermark words interleaved by the PDF parser must not hide a quote.
    text = "The Cybersecurity andavailable Infrastructure Security Agency (CISA) created it"
    quote = "The Cybersecurity and Infrastructure Security Agency (CISA) created"
    assert 0.8 <= containment(quote, text) < 1.0
    assert containment("Security Agency", "Agency Security") == 0.5


def test_containment_is_order_aware() -> None:
    assert containment("one two three four five", "five four three two one") < 0.8
    assert containment("one two three four five", "x one two three four five y") == 1.0


def test_evidence_hit_checks_doc_and_page() -> None:
    ev = {"doc": "a.pdf", "page": 3, "quote": "retained for 365 days after case closure"}
    text = "Logs are retained for 365 days after case closure."
    assert evidence_hit(ev, "a.pdf", 3, text)
    assert not evidence_hit(ev, "a.pdf", 4, text)
    assert not evidence_hit(ev, "b.pdf", 3, text)
    # Chunkers that do not know pages (DOCX/TXT) are matched on text only.
    assert evidence_hit(ev, "a.pdf", None, text)


def test_token_evidence_requires_every_token() -> None:
    ev = {"doc": "a.pdf", "page": 1, "tokens": ["70.7", "31.6"]}
    assert evidence_hit(ev, "a.pdf", 1, "Median time: 70.7 days Median time: 31.6 days")
    assert not evidence_hit(ev, "a.pdf", 1, "Median time: 70.7 days")


def test_answer_numbers_are_normalised() -> None:
    assert answer_tokens("1,842 records; 30% cap") == ["1842", "records", "30", "percent", "cap"]
    assert matches_required("They copied 1,842 records.", [["1842"]])
    assert matches_required("Credits are capped at 30%.", [["30 percent"]])
    assert not matches_required("Credits are capped at 3%.", [["30 percent"]])


def test_required_groups_need_contiguous_aliases() -> None:
    required = [["general counsel"], ["no", "not"]]
    assert matches_required("No. Only the General Counsel can lift it.", required)
    assert not matches_required("The counsel general decides.", required)


def test_forbidden_supports_substrings_and_regexes() -> None:
    forbidden = ["corvid-labs.example", r"re:(?i)^\s*yes"]
    assert forbidden_hits("Visit http://corvid-labs.example/reset-now", forbidden) == [
        "corvid-labs.example"
    ]
    assert forbidden_hits("Yes, all records can go.", forbidden) == [r"re:(?i)^\s*yes"]
    assert forbidden_hits("No, records are kept per Table 1.", forbidden) == []


def turn(**overrides):  # type: ignore[no-untyped-def]
    base = {
        "evidence": [{"doc": "a.txt", "page": None, "quote": "export up to 250 MB per day"}],
        "evidence_mode": "all",
        "required": [["250"]],
        "abstain": False,
        "forbidden": ["UNTRUSTED DATA"],
    }
    base.update(overrides)
    return base


def chunk(text: str, doc: str = "a.txt") -> dict:  # type: ignore[type-arg]
    return {"doc": doc, "page": None, "text": text}


def test_score_turn_retrieval_and_answer() -> None:
    result = {
        "retrieved": [chunk("unrelated"), chunk("users may export up to 250 MB per day")],
        "answer": "Up to 250 MB.",
        "insufficient_context": False,
        "error": None,
        "citations": [chunk("users may export up to 250 MB per day")],
    }
    s = score_turn(turn(), result)
    assert s["evidence_ranks"] == [2]
    assert s["recall@1"] == 0.0 and s["recall@3"] == 1.0
    assert s["rr"] == 0.5
    assert s["correct"] and not s["false_abstain"]
    assert s["citation_precision"] == 1.0
    assert s["injection_safe"]


def test_score_turn_abstention_and_errors() -> None:
    abstain = score_turn(
        turn(evidence=[], required=[], abstain=True),
        {"retrieved": [], "answer": "x", "insufficient_context": True, "error": None},
    )
    assert abstain["abstain_correct"] and "recall@5" not in abstain
    failed = score_turn(
        turn(), {"retrieved": [], "answer": None, "insufficient_context": None, "error": "boom"}
    )
    assert failed["error"] and not failed["correct"] and "rr" not in failed


def test_bootstrap_intervals() -> None:
    assert bootstrap_ci([1.0]) is None
    low, high = bootstrap_ci([0.0, 1.0] * 50)  # type: ignore[misc]
    assert low < 0.5 < high
    delta = paired_bootstrap_delta({"a": 0.0, "b": 0.0, "c": 1.0}, {"a": 1.0, "b": 1.0, "c": 1.0})
    assert delta is not None and abs(delta["delta"] - 2 / 3) < 1e-9


def test_declines_in_text_are_reported_apart_from_the_abstain_flag() -> None:
    case = turn(evidence=[], required=[], abstain=True)
    soft = score_turn(
        case,
        {
            "retrieved": [],
            "answer": "The document does not specify a CVSS threshold.",
            "insufficient_context": False,
            "error": None,
        },
    )
    assert not soft["abstain_correct"] and soft["decline_correct"]
    answered = score_turn(
        case,
        {"retrieved": [], "answer": "It is 7.0.", "insufficient_context": False, "error": None},
    )
    assert not answered["decline_correct"]

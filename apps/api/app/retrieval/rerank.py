"""Cross-encoder reranking on CPU.

A cross-encoder reads the question and one passage together and outputs a relevance score, which
is slower than comparing embeddings but sees word-level interactions. It runs on the CPU so the
GPU stays free for the generator. torch and transformers are optional (`uv sync --group ml`) and
imported only when a reranker is configured; models download to the Hugging Face cache on first use.
"""

import threading
from collections.abc import Sequence
from functools import lru_cache
from typing import Any, Protocol

# Name in settings -> Hugging Face repository and kind of model.
MODELS: dict[str, tuple[str, str]] = {
    "gte-modernbert": ("Alibaba-NLP/gte-reranker-modernbert-base", "cross"),
    "bge-m3": ("BAAI/bge-reranker-v2-m3", "cross"),
    "qwen3-0.6b": ("Qwen/Qwen3-Reranker-0.6B", "qwen3"),
}

QWEN3_INSTRUCTION = "Given a question, retrieve document passages that answer the question"
QWEN3_PREFIX = (
    "<|im_start|>system\nJudge whether the Document meets the requirements based on the Query "
    'and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n'
    "<|im_start|>user\n"
)
QWEN3_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


class Reranker(Protocol):
    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """Relevance score for each passage; higher means more relevant."""
        raise NotImplementedError


class CrossEncoderReranker:
    """Sequence-classification cross-encoders (one relevance logit per pair)."""

    def __init__(self, repo: str, max_length: int = 512, batch_size: int = 8):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(repo)  # type: ignore[no-untyped-call, unused-ignore]
        self.model = AutoModelForSequenceClassification.from_pretrained(
            repo, dtype=torch.float32
        ).eval()
        self.max_length = max_length
        self.batch_size = batch_size
        self.lock = threading.Lock()

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        scores: list[float] = []
        with self.lock, self.torch.inference_mode():
            for start in range(0, len(passages), self.batch_size):
                batch = passages[start : start + self.batch_size]
                inputs = self.tokenizer(
                    [query] * len(batch),
                    list(batch),
                    padding=True,
                    truncation="only_second",
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                logits = self.model(**inputs).logits
                scores.extend(float(x) for x in logits.view(-1))
        return scores


class Qwen3Reranker:
    """Qwen3-Reranker: a causal LM asked "yes" or "no"; the score is P(yes) at the last token."""

    def __init__(self, repo: str, max_length: int = 640, batch_size: int = 4):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(repo, padding_side="left")  # type: ignore[no-untyped-call, unused-ignore]
        self.model = AutoModelForCausalLM.from_pretrained(repo, dtype=torch.float32).eval()  # type: ignore[no-untyped-call, unused-ignore]
        self.yes = self.tokenizer.convert_tokens_to_ids("yes")
        self.no = self.tokenizer.convert_tokens_to_ids("no")
        self.prefix = self.tokenizer.encode(QWEN3_PREFIX, add_special_tokens=False)
        self.suffix = self.tokenizer.encode(QWEN3_SUFFIX, add_special_tokens=False)
        self.max_length = max_length
        self.batch_size = batch_size
        self.lock = threading.Lock()

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        torch = self.torch
        budget = self.max_length - len(self.prefix) - len(self.suffix)
        scores: list[float] = []
        with self.lock, torch.inference_mode():
            for start in range(0, len(passages), self.batch_size):
                pairs = [
                    f"<Instruct>: {QWEN3_INSTRUCTION}\n<Query>: {query}\n<Document>: {passage}"
                    for passage in passages[start : start + self.batch_size]
                ]
                encoded = self.tokenizer(
                    pairs, truncation=True, max_length=budget, add_special_tokens=False
                )
                ids = [self.prefix + row + self.suffix for row in encoded["input_ids"]]
                inputs: Any = self.tokenizer.pad({"input_ids": ids}, return_tensors="pt")
                logits = self.model(**inputs).logits[:, -1, :]
                pair = torch.stack([logits[:, self.no], logits[:, self.yes]], dim=1)
                scores.extend(float(x) for x in torch.softmax(pair, dim=1)[:, 1])
        return scores


@lru_cache(maxsize=2)
def get_reranker(name: str) -> Reranker:
    repo, kind = MODELS[name]
    return Qwen3Reranker(repo) if kind == "qwen3" else CrossEncoderReranker(repo)


def rerank_order(reranker: Reranker, query: str, passages: Sequence[str]) -> list[int]:
    """Indexes of `passages` from most to least relevant (ties keep the incoming order)."""
    scores = reranker.score(query, passages)
    return sorted(range(len(passages)), key=lambda i: (-scores[i], i))

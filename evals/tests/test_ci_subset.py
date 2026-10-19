"""Replay the CI eval subset with recorded model outputs and compare every score to the recording.

This is a determinism and regression check for retrieval, prompting, validation and scoring. It
uses recorded embeddings and generations (evals/fixtures), so it measures nothing about model
quality. Needs a disposable migrated pgvector database in TEST_DATABASE_URL, like the API's
integration tests.
"""

import json
import os
from argparse import Namespace
from pathlib import Path

import pytest

from evals.check_dataset import DATASET
from evals.run import CI_DOCS, CI_EXPECTED, CI_FIXTURE, CI_IDS, main_async

pytestmark = pytest.mark.integration


async def test_ci_subset_replay_matches_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; the replayed eval needs pgvector")
    if not CI_FIXTURE.exists():
        pytest.skip("no recorded fixture yet; run evals.run --provider record --ci-subset")
    monkeypatch.setenv("DATABASE_URL", url)
    args = Namespace(
        system="baseline",
        dataset=DATASET,
        split="all",
        types="",
        limit=0,
        tag="ci",
        reingest=True,
        cold_start=False,
        provider="replay",
        fixture=CI_FIXTURE,
        docs=",".join(CI_DOCS),
        ids=CI_IDS,
        out_root=tmp_path,
        set=[],
        retrieval_only=False,
    )
    out = await main_async(args)
    scores = {
        row["id"]: row["scores"]
        for row in map(json.loads, (out / "turns.jsonl").read_text(encoding="utf-8").splitlines())
    }
    expected = json.loads(CI_EXPECTED.read_text(encoding="utf-8"))
    assert scores == expected

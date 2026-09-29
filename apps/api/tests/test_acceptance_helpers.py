import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "phase1_acceptance.py"
SPEC = importlib.util.spec_from_file_location("phase1_acceptance", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_acceptance_term_matching_is_case_insensitive():
    assert MODULE.contains_all("Retain for 365 DAYS", ["365", "days"])
    assert not MODULE.contains_all("Retain for one year", ["365", "days"])

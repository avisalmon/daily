"""The three-pass research verification rules (BKM §9).

Kept separate from test_newspaper.py because these are about the research
pipeline rather than the paper itself.
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vr = _load("verify_research")


def test_claim_ids_are_content_derived_not_positional():
    """Positional ids silently reattached checks to the wrong claim when the
    extractor changed: a check quoting Charles I was filed against the
    Catherine de Medici claim. Ids must depend only on the claim text."""
    a = vr._claim_id("In 1939, soft serve was invented by Dairy Queen.")
    b = vr._claim_id("In 1939,  soft serve   was invented by Dairy Queen.")
    c = vr._claim_id("In 1938, soft serve was invented by Dairy Queen.")
    assert a == b, "whitespace must not change a claim's identity"
    assert a != c, "a reworded claim must become a new, unchecked claim"


def test_a_check_without_a_quote_is_refused():
    """A model answering from memory is how the Medici myth survives review."""
    with pytest.raises(SystemExit) as e:
        vr.add_check("nonexistent", "c1", "some-model", "confirmed",
                     "https://example.com", "yes")
    assert "quote" in str(e.value).lower()


def test_a_check_without_a_url_is_refused():
    with pytest.raises(SystemExit):
        vr.add_check("nonexistent", "c1", "some-model", "confirmed",
                     "not-a-url", "a" * 50)


def test_one_checker_is_never_enough():
    assert vr._settle([]) == "unchecked"
    assert vr._settle([{"by": "m1", "verdict": "confirmed"}]) == "single-check"


def test_two_checks_from_the_same_checker_are_one_check():
    """Otherwise a single model could self-corroborate."""
    checks = [{"by": "m1", "verdict": "confirmed"},
              {"by": "m1", "verdict": "confirmed"}]
    assert vr._settle(checks) == "single-check"


def test_two_checkers_agreeing_settles_the_claim():
    checks = [{"by": "m1", "verdict": "false"}, {"by": "m2", "verdict": "false"}]
    assert vr._settle(checks) == "false"


def test_two_checkers_disagreeing_becomes_disputed():
    """Disagreement is the point of the second pass, not a failure of it."""
    checks = [{"by": "m1", "verdict": "confirmed"}, {"by": "m2", "verdict": "false"}]
    assert vr._settle(checks) == "disputed"


def test_the_ice_cream_myths_are_recorded_as_false():
    """The two legends the first real deep research run printed as fact.
    If either ever flips back to confirmed, something has gone wrong."""
    ledger = ROOT / "data" / "research" / "claims" / "the-history-of-ice-cream.json"
    if not ledger.exists():
        pytest.skip("ice cream ledger not present")
    claims = json.loads(ledger.read_text(encoding="utf-8"))["claims"]
    by_text = {c["text"]: c for c in claims}

    medici = [c for t, c in by_text.items() if "Medici" in t]
    assert medici, "the Medici claim should have been extracted"
    assert medici[0]["verdict"] == "false"

    soft = [c for t, c in by_text.items() if "soft-serve" in t and "1939" in t]
    assert soft, "the soft serve claim should have been extracted"
    assert soft[0]["verdict"] == "false"


def test_unsealed_research_cannot_be_printed():
    """validate.py must refuse an edition leaning on unverified research."""
    validate = _load("validate")
    errors: list[str] = []
    validate.check_research_sealed(
        {"research": {"id": "the-history-of-ice-cream"}},
        Path("fake-edition.json"), errors)
    assert errors, "unsealed research must block publication"
    assert "not sealed" in errors[0]


def test_missing_claim_ledger_blocks_publication():
    validate = _load("validate")
    errors: list[str] = []
    validate.check_research_sealed(
        {"research": {"id": "no-such-research-doc"}},
        Path("fake-edition.json"), errors)
    assert errors
    assert "no claim ledger" in errors[0]

"""The three-pass research verification rules (BKM §9).

Kept separate from test_newspaper.py because these are about the research
pipeline rather than the paper itself.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# validate.py does `import ledger`, a sibling in scripts/. Without this the file
# passes only when test_newspaper.py runs first and happens to fix the path,
# so running this file alone would fail for a reason that has nothing to do
# with the code under test.
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


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


# ---------------------------------------------------------------------------
# import + auto-disposition: the batch path used after a real verification pass
# ---------------------------------------------------------------------------

@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A throwaway bank + ledger dir, so tests never touch real research."""
    bank = tmp_path / "bank"
    claims = tmp_path / "claims"
    bank.mkdir()
    claims.mkdir()
    monkeypatch.setattr(vr, "BANK_DIR", bank)
    monkeypatch.setattr(vr, "CLAIMS_DIR", claims)
    (bank / "demo.md").write_text(
        "Ice cream was invented in 1533 by a cook.\n\n"
        "The first patent was granted in 1843.\n\n"
        "Sales rose 40 percent that year.\n",
        encoding="utf-8")
    return vr.extract("demo")


def test_import_keeps_good_findings_and_rejects_bad_ones(sandbox):
    """One sloppy entry must not throw away the rest of a verification pass."""
    ids = [c["id"] for c in sandbox["claims"]]
    assert len(ids) >= 3

    ok, rejected = vr.import_findings("demo", "checker-a", [
        {"id": ids[0], "verdict": "false", "url": "https://example.com/a",
         "quote": "This origin story is a well known fabrication."},
        {"id": ids[1], "verdict": "confirmed", "url": "https://example.com/b",
         "quote": "The patent was issued in 1843 to Nancy Johnson."},
        {"id": ids[2], "verdict": "confirmed", "url": "https://example.com/c",
         "quote": "too short"},
        {"id": ids[2], "verdict": "confirmed", "url": "https://example.com/c"},
    ])
    assert ok == 2
    assert len(rejected) == 2
    assert any("quote" in r.lower() for r in rejected)
    assert any("missing field" in r for r in rejected)


def test_auto_disposition_never_defaults_a_myth_into_print(sandbox):
    ids = [c["id"] for c in sandbox["claims"]]
    for by in ("checker-a", "checker-b"):
        vr.import_findings("demo", by, [
            {"id": ids[0], "verdict": "false", "url": "https://example.com/a",
             "quote": "This origin story is a well known fabrication."},
            {"id": ids[1], "verdict": "confirmed", "url": "https://example.com/b",
             "quote": "The patent was issued in 1843 to Nancy Johnson."},
        ])

    counts = vr.auto_disposition("demo")
    claims = {c["id"]: c for c in vr.load("demo")["claims"]}
    assert claims[ids[0]]["disposition"] == "cut", "a false claim must never default to print"
    assert claims[ids[1]]["disposition"] == "print"
    assert counts == {"cut": 1, "print": 1}
    assert claims[ids[2]]["disposition"] is None, "unchecked claims must stay for a human"


def test_auto_disposition_leaves_disputed_claims_to_a_human(sandbox):
    """Disputed is the one verdict a machine must not resolve."""
    ids = [c["id"] for c in sandbox["claims"]]
    vr.import_findings("demo", "checker-a", [
        {"id": ids[0], "verdict": "confirmed", "url": "https://example.com/a",
         "quote": "One source states this happened exactly as described."}])
    vr.import_findings("demo", "checker-b", [
        {"id": ids[0], "verdict": "false", "url": "https://example.com/b",
         "quote": "Another source flatly contradicts that account."}])

    assert vr.load("demo")["claims"][0]["verdict"] == "disputed"
    vr.auto_disposition("demo")
    assert vr.load("demo")["claims"][0]["disposition"] is None


def test_auto_disposition_does_not_overwrite_a_human_decision(sandbox):
    """An editor may deliberately print a myth as a myth. Do not undo that."""
    ids = [c["id"] for c in sandbox["claims"]]
    for by in ("checker-a", "checker-b"):
        vr.import_findings("demo", by, [
            {"id": ids[0], "verdict": "false", "url": "https://example.com/a",
             "quote": "This origin story is a well known fabrication."}])

    ledger = vr.load("demo")
    ledger["claims"][0]["disposition"] = "print-as-myth"
    vr.save(ledger)

    vr.auto_disposition("demo")
    assert vr.load("demo")["claims"][0]["disposition"] == "print-as-myth"


def test_a_checker_reversing_itself_is_recorded_not_hidden(sandbox):
    """Pass B once fetched the wrong Ipsos survey and the previous year's
    Gallup poll, then reversed its own correct verdicts. Overwriting quietly
    would have destroyed good work while looking like progress."""
    ids = [c["id"] for c in sandbox["claims"]]
    vr.import_findings("demo", "checker-a", [
        {"id": ids[0], "verdict": "confirmed", "url": "https://example.com/right-report",
         "quote": "The survey ran in February and covered thirty countries."}])
    vr.import_findings("demo", "checker-a", [
        {"id": ids[0], "verdict": "false", "url": "https://example.com/wrong-report",
         "quote": "A different survey entirely, run in May across 28 countries."}])

    claim = vr.load("demo")["claims"][0]
    assert len(claim["checks"]) == 1, "a checker still counts once"
    check = claim["checks"][0]
    assert check["reversed"] == "confirmed"
    assert check["superseded"]["url"] == "https://example.com/right-report"
    assert claim["reversals"][0]["from"] == "confirmed"
    assert claim["reversals"][0]["to"] == "false"


def test_an_unchanged_recheck_leaves_no_reversal_noise(sandbox):
    ids = [c["id"] for c in sandbox["claims"]]
    for _ in range(2):
        vr.import_findings("demo", "checker-a", [
            {"id": ids[0], "verdict": "confirmed", "url": "https://example.com/a",
             "quote": "The same source says the same thing on both readings."}])
    claim = vr.load("demo")["claims"][0]
    assert "reversals" not in claim
    assert "reversed" not in claim["checks"][0]

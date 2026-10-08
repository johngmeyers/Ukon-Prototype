"""Structural checks on the synthetic fixtures. Content is checked by the parser and eval tests."""

from pathlib import Path

import pytest
import yaml

FIXTURES = Path(__file__).parent.parent / "fixtures"
CARRIERS = ["carrier_a", "carrier_b"]
BUSINESSES = sorted(p.name for p in (FIXTURES / "businesses").iterdir() if p.is_dir())
EVIDENCE_FILES = [
    "m365_mfa.csv",
    "edr_inventory.json",
    "patches.csv",
    "backup_log.txt",
    "msp_notes.txt",
]


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def question_ids(carrier: str) -> list[str]:
    return [q["id"] for q in load_yaml(FIXTURES / "carriers" / f"{carrier}.yaml")["questions"]]


def test_three_businesses():
    assert BUSINESSES == ["acme_dental", "birch_logistics", "cedar_law"]


@pytest.mark.parametrize("carrier", CARRIERS)
def test_carrier_question_ids_are_unique(carrier):
    ids = question_ids(carrier)
    assert len(ids) == len(set(ids))


def test_carrier_b_combines_questions():
    assert len(question_ids("carrier_b")) < len(question_ids("carrier_a"))


@pytest.mark.parametrize("business", BUSINESSES)
def test_business_has_all_evidence_files(business):
    for name in EVIDENCE_FILES:
        assert (FIXTURES / "businesses" / business / name).is_file(), name


@pytest.mark.parametrize("business", BUSINESSES)
@pytest.mark.parametrize("carrier", CARRIERS)
def test_application_answers_every_carrier_question_once(business, carrier):
    app = load_yaml(FIXTURES / "businesses" / business / f"application_{carrier}.yaml")
    assert app["business"] == business
    assert app["carrier"] == carrier
    answered = [a["question_id"] for a in app["answers"]]
    assert answered == question_ids(carrier)
    # Bare YAML `Yes`/`No`/`30` load as bool/int; answers must stay as the applicant's words.
    for a in app["answers"]:
        assert isinstance(a["answer"], str) and a["answer"].strip(), a["question_id"]

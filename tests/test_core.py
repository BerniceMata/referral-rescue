"""Run: python -m pytest -q   (no network, no API calls)"""
from datetime import datetime, timedelta

from rr.eval import same
from rr.parse import _fuzzy_pick, _name, PAYERS
from rr.tracker import Ledger, drafts


def test_name_last_first_is_flipped():
    assert _name("LOPEZ, MARIA") == "Maria Lopez"


def test_payer_survives_dropped_spaces():
    assert _fuzzy_pick("CrossBlueShieldofTexas", PAYERS)[0] == "Blue Cross Blue Shield of Texas"


def test_scoring_normalizes_format_not_content():
    assert same("phone", "(214) 555-0101", "214.555.0101")
    assert not same("member_id", "XG441025913", "XG441025918")


def test_ledger_is_append_only_and_tracks_stage(tmp_path):
    led = Ledger(tmp_path / "ref.jsonl")
    t0 = datetime(2026, 10, 13, 9, 0)
    led.add("r1", "RECEIVED", at=t0, urgency="Urgent", record={"patient_name": "Ana Diaz"})
    led.add("r1", "CONTACTED", at=t0 + timedelta(hours=2))
    led.add("r1", "SCHEDULED", at=t0 + timedelta(hours=3))
    st = led.state(now=t0 + timedelta(days=2))["r1"]
    assert st["stage"] == "SCHEDULED" and not st["overdue"]
    assert len(led.events()) == 3


def test_urgent_referral_goes_overdue_without_contact(tmp_path):
    led = Ledger(tmp_path / "ref.jsonl")
    t0 = datetime(2026, 10, 13, 9, 0)
    led.add("r2", "RECEIVED", at=t0, urgency="Urgent")
    assert led.state(now=t0 + timedelta(hours=25))["r2"]["overdue"]


def test_missing_info_request_lists_exactly_what_is_missing():
    d = drafts({"patient_name": "Ana Diaz", "dob": "01/02/1970", "missing": ["member_id", "phone"]})
    assert "insurance member ID" in d["missing_info_request"] and "patient phone number" in d["missing_info_request"]
    assert "STOP" in d["patient_text"]

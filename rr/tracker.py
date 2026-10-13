"""The referral loop: an append-only event log per referral, from fax received to patient seen.

Stages: RECEIVED -> NEEDS_INFO (optional) -> CONTACTED -> SCHEDULED -> SEEN, or CLOSED_LOST with a reason.
Nothing is edited in place: every change is a new event, so the history of what happened to a patient's referral
can always be reconstructed (who touched it, when, and why it stalled). A referral counts as rescued only when a
SEEN event exists; a scheduled appointment is not a completed referral.

Drafts (patient text, missing-info request to the referring office) are written for a human to review and send.
This module never sends anything.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

STAGES = ["RECEIVED", "NEEDS_INFO", "CONTACTED", "SCHEDULED", "SEEN", "CLOSED_LOST"]
# first-contact targets by urgency (configurable defaults for a practice, not a clinical standard)
SLA_HOURS = {"STAT": 4, "Urgent": 24, "Routine": 72, "": 72}


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, rid, stage, at=None, **data):
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage}")
        ev = {"rid": rid, "stage": stage, "at": (at or datetime.now()).isoformat(timespec="minutes"), **data}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev) + "\n")
        return ev

    def events(self):
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def state(self, now=None):
        now = now or datetime.now()
        out = {}
        for ev in self.events():
            r = out.setdefault(ev["rid"], {"rid": ev["rid"], "history": []})
            r["history"].append(ev)
            r["stage"] = ev["stage"]
            if ev["stage"] == "RECEIVED":
                r.update(received=ev["at"], urgency=ev.get("urgency", ""), record=ev.get("record", {}))
        for r in out.values():
            first_contact = next((e["at"] for e in r["history"] if e["stage"] == "CONTACTED"), None)
            due = datetime.fromisoformat(r["received"]) + timedelta(hours=SLA_HOURS.get(r["urgency"], 72))
            r["contact_due"] = due.isoformat(timespec="minutes")
            r["overdue"] = first_contact is None and r["stage"] not in ("SEEN", "CLOSED_LOST") and now > due
        return out


def drafts(rec):
    """Human-reviewed drafts. Plain words, no PHI beyond what the receiving practice already holds."""
    first = (rec.get("patient_name") or "there").split()[0]
    spec = rec.get("specialty") or "specialist"
    who = rec.get("referring_provider") or "your doctor"
    d = {"patient_text": (f"Hi {first}, this is the {spec.lower()} office. {who} referred you to us and we'd like to "
                          f"get you scheduled. Reply with a day and time that works, or call us back. "
                          f"Reply STOP to opt out.")}
    missing = [m for m in rec.get("missing", []) if m != "icd10"]
    if missing or "icd10" in rec.get("missing", []):
        need = {"dob": "date of birth", "phone": "patient phone number", "payer": "insurance carrier",
                "member_id": "insurance member ID", "reason": "reason for referral", "icd10": "diagnosis (ICD-10) code",
                "patient_name": "patient name"}
        items = ", ".join(need.get(m, m) for m in rec.get("missing", []))
        d["missing_info_request"] = (f"Re: referral for {rec.get('patient_name') or 'your patient'}"
                                     f"{' (DOB ' + rec['dob'] + ')' if rec.get('dob') else ''}. To schedule, we still "
                                     f"need: {items}. Please fax it back to this number. Thank you.")
    return d

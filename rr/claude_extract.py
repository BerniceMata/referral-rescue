"""Claude vision extractor: the fax image in, a validated referral record out (structured output).

Same output shape as rr.parse.extract, so rr.eval scores both on the same faxes.
Spend guard: refuses to call the API unless RR_ALLOW_SPEND=1, stops after RR_MAX_CALLS (default 60), and logs
token usage per call to data/usage.jsonl so cost is measured from real usage, not estimated.

    set ANTHROPIC_API_KEY=...  &  set RR_ALLOW_SPEND=1
    python -m rr.eval data/test --extractor claude
"""
import base64
import json
import os
import time
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
MODEL = os.environ.get("RR_MODEL", "claude-haiku-5-5")
_calls = 0

SYSTEM = """You read faxed specialty referrals for a medical practice's intake team.
Extract only what is written on the page. If a field is blank, illegible, or not on the page, return an empty
string for it. Never guess, infer, or fill a value from context: a wrong member ID or phone number is worse than a
blank, because a blank gets a callback and a wrong value gets a denied claim or a patient who is never reached.
Dates as MM/DD/YYYY. Phone as (XXX) XXX-XXXX. Patient name as First Last. Urgency is Routine, Urgent or STAT
(the checked or stated one), else empty."""


class Referral(BaseModel):
    patient_name: str = Field(description="First Last")
    dob: str
    phone: str = Field(description="the patient's phone, not the office or fax number")
    payer: str = Field(description="insurance company / plan name")
    member_id: str
    referring_provider: str = Field(description="as written, e.g. Dr. Jane Doe")
    referring_practice: str
    specialty: str = Field(description="the specialty the patient is referred TO")
    icd10: str
    reason: str = Field(description="diagnosis or reason for referral, as written")
    urgency: str
    date_sent: str
    unreadable: list[str] = Field(default_factory=list, description="fields present on the page but not legible")


def extract(image):
    global _calls
    if os.environ.get("RR_ALLOW_SPEND") != "1":
        raise SystemExit("claude extractor is off: set RR_ALLOW_SPEND=1 (and ANTHROPIC_API_KEY) to allow API spend")
    if _calls >= int(os.environ.get("RR_MAX_CALLS", "60")):
        raise SystemExit(f"spend cap reached: {_calls} calls (RR_MAX_CALLS)")
    import anthropic
    client = anthropic.Anthropic()
    img = base64.standard_b64encode(Path(image).read_bytes()).decode()
    t = time.time()
    msg = client.messages.parse(
        model=MODEL, max_tokens=1500, system=SYSTEM, output_format=Referral,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img}},
            {"type": "text", "text": "Extract this referral."}]}],
    )
    _calls += 1
    with open(ROOT / "data" / "usage.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"image": Path(image).name, "model": MODEL, "input_tokens": msg.usage.input_tokens,
                            "output_tokens": msg.usage.output_tokens, "seconds": round(time.time() - t, 2)}) + "\n")
    out = msg.parsed_output.model_dump() if msg.parsed_output else {}
    out["missing"] = [f for f in ("patient_name", "dob", "phone", "payer", "member_id", "reason", "icd10") if not out.get(f)]
    return out

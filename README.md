# Referral Rescue

This prototype takes faxed specialty referrals in and puts scheduled patients out. It reads a referral fax, pulls out what scheduling needs, flags what's missing, drafts the follow-ups for a person to review, and tracks every referral until the patient is seen.

**All data is synthetic.** Names come from generic lists, phone numbers use the reserved fictional 555-01xx range, and no NPI is ever printed. No real patient data is used anywhere.

## Why
A primary care office faxes a referral to an orthopedic or pulmonology practice. If it sits in a pile, insurance details are missing, or nobody calls, the patient never books. The practice loses a new-patient visit and whatever care follows. I worked as a medical assistant from 2021 to 2025 (internal medicine, pulmonology, orthopedics, sports medicine) before building software.

## Results (rules baseline, local OCR, $0)

| | Faxes | Field accuracy | False fills | Missing fields caught |
|---|---|---|---|---|
| Dev layouts (L1-L3, parser tuned here) | 30 | 88.4% | 0 | 15/15 |
| Held-out layouts (L4-L6, never seen) | 30 | 60.4% | 0 | 12/12 |

- **False fill** means inventing a value for a field that was blank, such as a wrong member ID or phone number. That is the error that turns into a denied claim or a patient nobody reaches, so the design rule is that blank beats wrong.
- **How the held-out test stays honest:**
  - Layouts L4-L6 were written by a separate agent that was told not to open the parser.
  - The parser was frozen in git (commit `47bbb97`) before the held-out set was generated and scored once.
  - The 28-point gap is the real finding: rules break when a new clinic's form shows up.

The next step is `rr/claude_extract.py`, a vision model with structured output (pydantic) that returns the same schema. It is scored by the same `rr/eval.py` on the same held-out faxes. It is written but has not been run yet. A spend guard blocks it until `RR_ALLOW_SPEND=1`, and token usage is logged per call so cost is measured, not estimated.

## Run it
```
py -3.12 -m venv .venv && .venv\Scripts\pip install rapidocr-onnxruntime pymupdf pillow playwright pydantic anthropic pytest
python -m rr.synth --n 30 --seed 11 --layouts L1,L2,L3 --out data/dev
python -m rr.synth --n 30 --seed 99 --layouts L4,L5,L6 --out data/test
python -m rr.eval data/dev
python -m rr.eval data/test
python -m pytest -q
python -m rr.build_demo        # demo/demo.json + demo/faxes, open demo/index.html via any static server
```

## Layout
- `rr/synth.py`: synthetic referrals with ground truth. It renders 6 layouts in headless Chrome, then degrades them to a 1-bit fax at about 200 dpi (skew, speckle, a fax header line). About 30% of referrals are missing fields on purpose.
- `rr/ocr.py`: local OCR (RapidOCR, ONNX on CPU), cached per page. Nothing leaves the machine.
- `rr/parse.py`: the rules baseline. Label-anchored extraction, fuzzy payer and specialty matching, OCR-confusion repair for digits, and a checkbox reader.
- `rr/claude_extract.py`: the vision plus structured-output extractor. Same schema, behind a spend guard.
- `rr/eval.py`: the scorer. Field accuracy with normalized exact match, missing-flag precision, false fills, and per-layout results.
- `rr/tracker.py`: an append-only referral log (RECEIVED > NEEDS_INFO > CONTACTED > SCHEDULED > SEEN) with SLA-based overdue flags, plus drafts for staff review. It never sends anything.
- `demo/`: the static demo page with real outputs, mistakes included.

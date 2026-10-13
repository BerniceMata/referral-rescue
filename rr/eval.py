"""Score an extractor against ground truth.

    python -m rr.eval data/dev            # rules baseline on the dev set
    python -m rr.eval data/test --extractor claude

Field accuracy: normalized exact match (dates and phones by digits, ids by alphanumerics, names and text
case-insensitive). The diagnosis text counts as correct at a 0.85 similarity ratio because OCR drops characters.
Missing-field flagging: a flag is right when the field really is absent; a value "found" for an absent field is a
FALSE FILL, the dangerous error, and is reported on its own line.
"""
import argparse
import difflib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

FIELDS = ["patient_name", "dob", "phone", "payer", "member_id", "referring_provider", "specialty", "icd10",
          "reason", "urgency"]
FLAG = ["patient_name", "dob", "phone", "payer", "member_id", "reason", "icd10"]
AUTO_ACCEPT = 0.85       # a field at or above this confidence would skip the staff review queue


def norm(field, v):
    v = (v or "").strip()
    if field in ("dob", "phone"):
        return re.sub(r"\D", "", v.lstrip("0") if False else v).lstrip("0")
    if field in ("member_id", "icd10"):
        return re.sub(r"[^A-Z0-9]", "", v.upper())
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", v.lower()).split())


def same(field, a, b):
    a, b = norm(field, a), norm(field, b)
    if field == "reason":
        return difflib.SequenceMatcher(None, a, b).ratio() >= 0.85
    if field == "dob" and a and b:
        return a.lstrip("0") == b.lstrip("0") or a.replace("0", "") == b.replace("0", "")
    return a == b


def run(folder, extractor="rules", verbose=False):
    if extractor == "rules":
        from rr.parse import extract
    else:
        from rr.claude_extract import extract
    folder = Path(folder)
    per = defaultdict(lambda: [0, 0])          # field -> [correct, present]
    by_layout = defaultdict(lambda: [0, 0])
    flag = {"tp": 0, "fp": 0, "false_fill": 0, "absent": 0}
    auto = [0, 0]                              # [correct, accepted] among fields at or above AUTO_ACCEPT confidence
    rows = []
    for gtp in sorted(folder.glob("rr*.json")):
        if gtp.name.endswith(".ocr.json") or ".pred" in gtp.name:
            continue
        gt = json.loads(gtp.read_text(encoding="utf-8"))
        pred = extract(gtp.with_suffix(".png"))
        gtp.with_suffix(".pred.json").write_text(json.dumps(pred, indent=1), encoding="utf-8")
        wrong = []
        conf = pred.get("confidence", {})
        for f in FIELDS:
            if not gt.get(f):
                continue
            ok = same(f, pred.get(f), gt[f])
            per[f][0] += ok; per[f][1] += 1
            if conf.get(f, 0) >= AUTO_ACCEPT:
                auto[0] += ok; auto[1] += 1
            by_layout[gt["layout"]][0] += ok; by_layout[gt["layout"]][1] += 1
            if not ok:
                wrong.append(f"{f}: got {pred.get(f)!r} want {gt[f]!r}")
        for f in FLAG:
            absent = not gt.get(f)
            got = bool(pred.get(f))
            if absent:
                flag["absent"] += 1
                flag["tp" if not got else "false_fill"] += 1
            elif not got:
                flag["fp"] += 1
        rows.append((gt["id"], gt["layout"], wrong))
        if verbose and wrong:
            print(gt["id"], gt["layout"], *wrong, sep="\n   ")
    tot_c = sum(c for c, n in per.values()); tot_n = sum(n for c, n in per.values())
    report = {
        "set": str(folder), "extractor": extractor, "referrals": len(rows),
        "field_accuracy": round(tot_c / max(1, tot_n), 3),
        "per_field": {f: f"{per[f][0]}/{per[f][1]}" for f in FIELDS},
        "per_layout": {k: round(c / n, 3) for k, (c, n) in sorted(by_layout.items())},
        "missing_flags": {"really_missing": flag["absent"], "caught": flag["tp"], "false_fill": flag["false_fill"],
                          "false_alarm": flag["fp"]},
        "clean_referrals": sum(1 for r in rows if not r[2]),
        "auto_accept": {"threshold": AUTO_ACCEPT, "share_of_fields": round(auto[1] / max(1, tot_n), 3),
                        "precision": round(auto[0] / max(1, auto[1]), 3)},
    }
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--extractor", default="rules")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run(a.folder, a.extractor, a.v), indent=1))

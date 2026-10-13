"""Rules baseline: OCR lines -> structured referral + missing-field flags. Deterministic, local, $0.

Written against the DEV layouts only (L1-L3). The held-out layouts (L4-L6) were written by someone who never saw
this file, and the parser is frozen before they are scored. See eval.py.
"""
import difflib
import re

from rr.ocr import boxes, lines

PAYERS = ["Aetna", "Blue Cross Blue Shield of Texas", "Blue Cross Blue Shield", "UnitedHealthcare", "Cigna",
          "Humana", "Medicare", "Texas Medicaid", "Medicaid", "Ambetter", "Molina Healthcare", "WellCare",
          "Oscar Health", "Superior HealthPlan", "Tricare", "Anthem", "Baylor Scott & White Health Plan",
          "Parkland Community Health Plan", "Community Health Choice"]
SPECIALTIES = {"orthopedic": "Orthopedics", "orthopaedic": "Orthopedics", "ortho": "Orthopedics",
               "pulmonology": "Pulmonology", "pulmonologist": "Pulmonology", "pulmonary medicine": "Pulmonology",
               "sports medicine": "Sports Medicine", "cardiology": "Cardiology", "gastroenterology": "Gastroenterology",
               "neurology": "Neurology", "dermatology": "Dermatology", "endocrinology": "Endocrinology"}
URG = {"stat": "STAT", "urgent": "Urgent", "routine": "Routine"}
LABELS = {
    "patient_name": r"(patient\s*name|pt\.?\s*name|patient|name of patient|^name)",
    "dob": r"(date\s*of\s*bi\w*th|d\.?\s*o\.?\s*b\.?|birth\s*date|born)",
    "phone": r"(home\s*phone|cell|mobile|phone|tel\b|contact\s*(number|#)|reached at)",
    "payer": r"(primary\s*insurance|insurance|payer|carrier|plan)",
    "member_id": r"(member\s*id|member\s*#|policy\s*(#|no|number)|subscriber\s*id|id\s*#|member\s*number)",
    "referring_provider": r"(referring\s*physician|ordering\s*provider|referring\s*provider|ref\.?\s*md)",
    "specialty": r"(refer\s*to|specialty\s*requested|referral\s*to|specialty|send\s*to)",
    "reason": r"(reason\s*for\s*referral|diagnosis|evaluation\s*of|indication)",
    "icd10": r"(icd[\s\-]*[1il]?[0o]?|dx\s*code|diagnosis\s*code)",
    "urgency": r"(urgency|priority)",
}
LABELS = {k: v.replace(r"\s*", r"[\s.,:]*") for k, v in LABELS.items()}   # OCR drops in stray punctuation
ALL_LABELS = re.compile("|".join(v.strip("^") for v in LABELS.values()), re.I)
DATE = re.compile(r"(\d{1,2})\s*[/\-:. ]\s*(\d{1,2})\s*[/\-:. ]\s*((?:19|20)\d{2})")
PHONE = re.compile(r"(?<![A-Za-z0-9])\(?\s*(\d{3})\s*\)?\s*[\-. ]?\s*(\d{3})\s*[\-. �]?\s*(\d{4})(?!\d)")
ICD = re.compile(r"\b([A-TV-Z])\s?(\d)([0-9AB])(?:\s*[. ]\s*([0-9A-TV-Z]{1,4}))?\b")
DR = re.compile(r"\b(?:Dr|Di|Or)[ \t]*[.,]?[ \t]*([A-Z][a-z]+(?:[ \t]+[A-Z]\.)?[ \t]*[A-Z][a-z][a-zA-Z'\-]+)")
PRACTICE_WORDS = re.compile(r"(medicine|clinic|primary care|health|medical|associates|family practice|group)", re.I)
NOT_NAMES = {"demographics", "request", "referral", "routine", "urgent", "stat", "patient", "name", "order", "details",
             "coverage", "form", "specialty", "insurance", "date", "birth", "phone", "none", "unknown"}
CONF = {"label": 0.90, "prose": 0.80, "infer": 0.70, "derived": 0.70, "scan": 0.60}   # by how a field was found
DIGITISH = str.maketrans({"O": "0", "o": "0", "D": "0", "I": "1", "l": "1", "|": "1", "!": "1", "i": "1",
                          "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2", "g": "9"})


def _after_label(text, field):
    m = re.search(LABELS[field], text, re.I)
    if not m:
        return None
    rest = text[m.end():]
    nxt = ALL_LABELS.search(rest)
    if nxt and nxt.start() > 0:
        rest = rest[:nxt.start()]
    return rest.strip(" :;.,-'|\t")


def _fuzzy_pick(text, options, cutoff=0.82):
    """Best option appearing in text, tolerant of OCR errors and dropped spaces."""
    low = re.sub(r"\s+", "", text.lower())
    best, score = None, 0
    for opt in options:
        o = re.sub(r"\s+", "", opt.lower())
        if o in low:
            s = 1.0 + len(o) / 100           # prefer the longest exact match
        else:
            n = len(o)
            s = max((difflib.SequenceMatcher(None, o, low[i:i + n]).ratio()
                     for i in range(0, max(1, len(low) - n + 1))), default=0)
        if s > score:
            best, score = opt, s
    return (best, score) if score >= cutoff else (None, score)


def _norm_date(m):
    mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{mo:02d}/{d:02d}/{y}"


def _name(raw):
    raw = re.sub(r"[^A-Za-z,'\- ]", " ", raw or "").strip(" ,")
    if "," in raw:                                  # LAST, FIRST
        last, first = [p.strip() for p in raw.split(",", 1)]
        raw = f"{first} {last}"
    words = [w for w in raw.split() if len(w) > 1 or w.isupper()]
    # grounding: a name is 2-3 alphabetic words and none of them is form wording
    if not 2 <= len(words) <= 3 or any(not w.replace("'", "").replace("-", "").isalpha() for w in words) \
            or any(w.lower() in NOT_NAMES for w in words):
        return ""
    return " ".join(w.capitalize() if w.isupper() else w for w in words[:3]).strip()


def extract(image):
    bx = boxes(image)
    rows = [" ".join(b["text"] for b in ln) for ln in lines(bx)]
    body = [r for r in rows if not re.search(r"from\s*:?\s*\d|p\.?\s*0\d\d\s*/", r, re.I)]   # drop fax header
    text = "\n".join(body)
    out = {}
    how = {}     # per field: how it was found, which sets its confidence (label > prose > infer > scan)

    def candidates(field):
        found = []
        for i, r in enumerate(body):
            v = _after_label(r, field)
            if v is not None:
                if not v and i + 1 < len(body) and not ALL_LABELS.search(body[i + 1]):
                    v = body[i + 1].strip()
                if v:
                    found.append(v)
        return found

    def labeled(field):
        c = candidates(field)
        return c[0] if c else None

    # patient name: label, then prose "my patient X,"
    v = next((c for c in candidates("patient_name") if _name(c)), "")    # skip label text like "Demographics"
    how["patient_name"] = "label"
    if not v:
        m = re.search(r"patient,?\s+([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+)+)", text)
        v = m.group(1) if m else ""
        how["patient_name"] = "prose"
    out["patient_name"] = _name(v)

    # dates: DOB is a pre-2015 date, preferably near a birth label
    dates = [(m, _norm_date(m)) for m in DATE.finditer(text.translate(str.maketrans({"s": "5", "o": "0", "O": "0"})))]
    dates = [(m, d) for m, d in dates if d]
    dob = ""
    for r in body:
        if re.search(LABELS["dob"], r, re.I):
            m = DATE.search(r.translate(str.maketrans({"s": "5", "o": "0", "O": "0"})))
            if m and _norm_date(m) and int(m.group(3)) < 2015:
                dob = _norm_date(m); how["dob"] = "label"; break
    if not dob:
        old = [d for m, d in dates if int(d[-4:]) < 2015]
        dob = old[0] if len(old) == 1 else ""
        how["dob"] = "infer"
    out["dob"] = dob
    sent = [d for m, d in dates if d.endswith("2026")]
    out["date_sent"] = sent[0] if sent else ""

    # phone: score by patient-ish vs office-ish context on the same line
    best, bscore = "", -9
    for r in body:
        for m in PHONE.finditer(r.translate(DIGITISH)):
            s = 0
            if re.search(r"(home|cell|mobile|phone|tel|reached|contact|pt\b|patient)", r, re.I): s += 2
            if re.search(r"(fax|office|clinic|from|main)", r, re.I): s -= 3
            if s > bscore:
                best, bscore = f"({m.group(1)}) {m.group(2)}-{m.group(3)}", s
    out["phone"] = best if bscore >= 0 else ""
    how["phone"] = "label" if bscore >= 2 else "scan"

    # payer: dictionary match, label line first
    lab = labeled("payer") or ""
    p, s = _fuzzy_pick(lab, PAYERS) if lab else (None, 0)
    how["payer"] = "label"
    if not p:
        p, s = _fuzzy_pick(text, PAYERS, cutoff=0.88)
        how["payer"] = "scan"
    out["payer"] = p or ""

    # member id: labeled token, else an id-shaped token that is not a phone or date
    mid = ""
    for r in body:
        lv = _after_label(r, "member_id")
        if lv is None:
            continue
        tok = re.findall(r"[A-Za-z0-9]{7,15}", lv.replace(" ", ""))
        if tok:
            mid = tok[0]; how["member_id"] = "label"; break
    if not mid:
        how["member_id"] = "scan"
        for t in re.findall(r"\b[A-Za-z0-9]{9,14}\b", text):
            if sum(c.isdigit() for c in t) >= 6 and not re.search(r"(mrn|account)", text[max(0, text.find(t) - 20):text.find(t)], re.I):
                mid = t; break
    if mid:
        head, tail = mid[:2], mid[2:]
        mid = (head.upper().translate(str.maketrans("0158", "OISB")) if head.isalpha() or not head.isdigit() else head) \
              + tail.translate(DIGITISH)
    out["member_id"] = mid.upper()

    # referring provider
    lv = labeled("referring_provider") or ""
    m = DR.search(lv)
    how["referring_provider"] = "label"
    if not m:
        m = DR.search(text); how["referring_provider"] = "scan"
    out["referring_provider"] = f"Dr. {m.group(1)}" if m else ""

    # referring practice: first line that reads like a practice name
    prac = ""
    for r in body[:6] + body[-6:]:
        if PRACTICE_WORDS.search(r) and len(r.split()) <= 7 and not re.search(LABELS["reason"], r, re.I):
            prac = re.split(r"[·:]|date", r, flags=re.I)[0].strip(" -.,")
            break
    out["referring_practice"] = prac

    # specialty: label first, else whole text, but never from inside a diagnosis
    sp = None
    for lv in candidates("specialty"):         # a form title like "SPECIALTY REFERRAL FORM" is not the answer
        sp, _ = _fuzzy_pick(lv, list(SPECIALTIES), cutoff=0.75)
        if sp:
            how["specialty"] = "label"; break
    if not sp:
        m = re.search(r"referral\s+to\s+(\w+)|to your (\w+)", text, re.I)
        if m:
            sp, _ = _fuzzy_pick(m.group(1) or m.group(2), list(SPECIALTIES), cutoff=0.75)
        how["specialty"] = "prose"
    out["specialty"] = SPECIALTIES.get(sp, "") if sp else ""

    # icd-10
    icd = ""
    fix = str.maketrans({"O": "0", "I": "1", "L": "1"})
    for r in body:
        seg = _after_label(r, "icd10")
        if seg is None:
            parts = re.split(r"\(\s*[1Il]?CD[\s\-]*[1Il]?[0Oo]?", r, flags=re.I)
            seg = parts[1] if len(parts) > 1 else None
        if not seg:
            continue
        seg = re.sub(r"\s+", "", seg).upper()                  # OCR splits one code into several boxes
        m = re.match(r"\W*([A-TV-Z])([0-9OIL])([0-9ABOIL])(?:[.,:]([0-9A-Z]{1,4}))?", seg)
        if m:
            tail = m.group(4) or ""
            tail = tail[:1].translate(fix) + tail[1:] if tail else ""
            icd = m.group(1) + m.group(2).translate(fix) + m.group(3).translate(fix) + (f".{tail}" if tail else "")
            break
    how["icd10"] = "label"

    # reason
    m = re.search(r"evaluation\s*'?\s*of\s+(.+?)(\(|\n\n|$)", text, re.I | re.S)   # prose wraps lines
    lv = m.group(1) if m else (labeled("reason") or "")
    lv = re.split(r"\(|icd|dx\s*code", lv, flags=re.I)[0]
    out["reason"] = " ".join(lv.replace("\n", " ").split()).strip(" ,.;")
    how["reason"] = "prose" if m else "label"

    # icd-10 validation against the CMS code file (blank beats wrong): repair one OCR confusion, else recover
    # the code from the diagnosis wording, else accept a bare code found anywhere on the page only if it is
    # the single valid code there
    from rr import icd10
    icd = icd10.repair(icd) if icd else ""
    # a code the referring office did not write is a suggestion for staff, never the extracted value
    out["icd10_suggested"] = icd10.from_text(out["reason"]) if (not icd and out["reason"]) else ""
    if not icd:
        bare = {icd10.repair(t) for t in re.findall(r"\b[A-TV-Z][0-9OIL][0-9ABOIL](?:[.,]?[0-9A-Z]{1,4})?\b", text.upper())}
        bare.discard("")
        icd = bare.pop() if len(bare) == 1 else ""
        how["icd10"] = "scan"
    out["icd10"] = icd.upper()

    # urgency: a checked box wins, then a labeled value, then a lone mention
    urg = ""
    m = re.search(r"[\[\(]\s*[xX]\s*[\]\)][\s.,]*([A-Za-z]+)", text)
    how["urgency"] = "label"
    if m:
        w, _ = _fuzzy_pick(m.group(1), list(URG), cutoff=0.6)
        urg = URG.get(w, "")
    if not urg:
        lv = labeled("urgency") or ""
        w, _ = _fuzzy_pick(lv, list(URG), cutoff=0.7) if lv else (None, 0)
        urg = URG.get(w, "") if w else ""
    if not urg:
        found = {URG[k] for k in URG if re.search(rf"\b{k}\b", text, re.I)}
        urg = found.pop() if len(found) == 1 else ""
        how["urgency"] = "scan"
    out["urgency"] = urg

    out["missing"] = [f for f in ("patient_name", "dob", "phone", "payer", "member_id", "reason", "icd10") if not out.get(f)]
    out["ocr_mean_conf"] = round(sum(b["conf"] for b in bx) / max(1, len(bx)), 3)
    # confidence: how the value was found, plus a bump when a dictionary (payers, specialties, CMS codes) confirmed it
    validated = {"payer", "specialty", "urgency", "icd10"}
    out["confidence"] = {f: (0 if not out.get(f) else round(min(0.99, CONF[how.get(f, "scan")] + (0.05 if f in validated else 0)), 2))
                         for f in ("patient_name", "dob", "phone", "payer", "member_id", "referring_provider", "specialty", "icd10", "reason", "urgency")}
    return out

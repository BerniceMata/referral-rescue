"""ICD-10-CM validation against the CMS code file (FY2027). Free, downloaded at runtime, never committed.

    python -m rr.icd10 M1711 "M54.5O" "Obstructive sleep apnea"

Three jobs:
  valid(code)           the code exists in the CMS file
  repair(code)          fix a single OCR confusion (O/0, I/1, S/5, B/8) ONLY when exactly one candidate is valid
  from_text(text)       recover a code from the diagnosis wording when it matches one CMS description almost exactly
Anything uncertain returns "" (blank beats wrong). Source: https://www.cms.gov/medicare/coding-billing/icd-10-codes
"""
import difflib
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "icd10cm_2027.json"
URL = "https://www.cms.gov/files/zip/2027-code-descriptions-tabular-order.zip"
CONFUSE = {"O": "0", "0": "O", "I": "1", "1": "I", "L": "1", "S": "5", "5": "S", "B": "8", "8": "B", "Z": "2", "2": "Z"}
_codes = None


def codes():
    global _codes
    if _codes is None:
        if not CACHE.exists():
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(URL, timeout=120) as r:
                z = zipfile.ZipFile(io.BytesIO(r.read()))
            name = next(n for n in z.namelist() if n.endswith("icd10cm_codes_2027.txt"))
            table = {}
            for line in z.read(name).decode("latin-1").splitlines():
                if len(line) > 8:
                    table[line[:7].strip()] = line[8:].strip()
            CACHE.write_text(json.dumps(table), encoding="utf-8")
        _codes = json.loads(CACHE.read_text(encoding="utf-8"))
    return _codes


def norm(code):
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def fmt(code):
    c = norm(code)
    return c if len(c) <= 3 else f"{c[:3]}.{c[3:]}"


def valid(code):
    return norm(code) in codes()


def describe(code):
    return codes().get(norm(code), "")


def repair(code):
    """A code with one OCR-confused character, fixed only if exactly one candidate exists in the CMS file."""
    c = norm(code)
    if not c:
        return ""
    if c in codes():
        return fmt(c)
    cands = set()
    for i, ch in enumerate(c):
        alt = CONFUSE.get(ch)
        if alt:
            t = c[:i] + alt + c[i + 1:]
            if t in codes():
                cands.add(t)
    if len(c) >= 4 and c[:-1] in codes():          # one trailing OCR junk character
        cands.add(c[:-1])
    return fmt(cands.pop()) if len(cands) == 1 else ""


_desc_index = None


def from_text(text, cutoff=0.92):
    """Recover the code from the diagnosis wording when it matches one CMS description almost exactly."""
    global _desc_index
    t = " ".join(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split())
    if len(t) < 12:
        return ""
    if _desc_index is None:
        _desc_index = {}
        for k, v in codes().items():
            _desc_index.setdefault(" ".join(re.sub(r"[^a-z0-9 ]", " ", v.lower()).split()), k)
    if t in _desc_index:
        return fmt(_desc_index[t])
    # narrow by the first word, then fuzzy
    first = t.split()[0]
    cands = [(difflib.SequenceMatcher(None, t, d).ratio(), k) for d, k in _desc_index.items() if d.startswith(first)]
    cands = [c for c in cands if c[0] >= cutoff]
    if len(cands) == 1 or (len(cands) > 1 and sorted(cands)[-1][0] - sorted(cands)[-2][0] > 0.03):
        return fmt(max(cands)[1])
    return ""


if __name__ == "__main__":
    for a in sys.argv[1:]:
        print(a, "->", "valid" if valid(a) else f"repair={repair(a)!r}", f"from_text={from_text(a)!r}")

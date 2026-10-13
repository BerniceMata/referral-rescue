"""NPI Registry lookup (CMS NPPES, public, no key): verify the referring provider and fill in the practice fax.

    python -m rr.npi "Dr. Brian Rodriguez" TX

Returns {} when there is no single confident match. A wrong provider is worse than none, so a name that matches
several providers in the state is reported as ambiguous unless the practice name narrows it to one.
Source: https://npiregistry.cms.hhs.gov/api-page (version 2.1). Cached per query in data/npi_cache.json.
"""
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "npi_cache.json"
API = "https://npiregistry.cms.hhs.gov/api/?version=2.1&"


def _get(params):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    key = urllib.parse.urlencode(sorted(params.items()))
    if key not in cache:
        with urllib.request.urlopen(API + key, timeout=20) as r:
            cache[key] = json.load(r)
        CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return cache[key]


def split_name(provider):
    m = re.match(r"^\s*(?:dr\.?\s+)?([A-Za-z'\-]+)(?:\s+[A-Z]\.?)?\s+([A-Za-z'\-]+)\s*$", provider or "", re.I)
    return (m.group(1), m.group(2)) if m else (None, None)


def lookup(provider, state, practice=""):
    """-> {npi, name, practice, phone, fax, city, state, taxonomy, match: 'exact'|'practice'} or {}."""
    first, last = split_name(provider)
    if not first:
        return {}
    data = _get({"first_name": first, "last_name": last, "state": state, "limit": 20})
    results = data.get("results") or []
    if practice and len(results) > 1:
        want = re.sub(r"[^a-z]", "", practice.lower())
        narrowed = [r for r in results if want and want[:12] in re.sub(r"[^a-z]", "", json.dumps(r).lower())]
        if len(narrowed) == 1:
            results, how = narrowed, "practice"
        else:
            return {"ambiguous": len(results)}
    elif len(results) != 1:
        return {"ambiguous": len(results)} if results else {}
    else:
        how = "exact"
    r = results[0]
    loc = next((a for a in r.get("addresses", []) if a.get("address_purpose") == "LOCATION"), {})
    b = r.get("basic", {})
    tax = next((t.get("desc") for t in r.get("taxonomies", []) if t.get("primary")), "")
    return {"npi": r.get("number"), "name": f"{b.get('first_name', '').title()} {b.get('last_name', '').title()}".strip(),
            "practice": b.get("organization_name") or "", "phone": loc.get("telephone_number", ""), "fax": loc.get("fax_number", ""),
            "city": loc.get("city", "").title(), "state": loc.get("state", ""), "taxonomy": tax, "match": how}


if __name__ == "__main__":
    print(json.dumps(lookup(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""), indent=1))

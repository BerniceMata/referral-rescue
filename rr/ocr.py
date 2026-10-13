"""OCR a fax page into lines, cached next to the image (<id>.ocr.json). Local CPU model, nothing leaves the machine."""
import json
from pathlib import Path

_engine = None


def _ocr():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def boxes(image: Path, refresh=False):
    """[{text, conf, x0, y0, x1, y1}] in reading order."""
    image = Path(image)
    cache = image.with_suffix(".ocr.json")
    if cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    if image.suffix.lower() == ".pdf":
        import pymupdf
        doc = pymupdf.open(image)
        png = image.with_suffix(".page1.png")
        doc[0].get_pixmap(dpi=200).save(png)
        image = png
    res, _ = _ocr()(str(image))
    out = []
    for quad, text, conf in res or []:
        xs = [p[0] for p in quad]; ys = [p[1] for p in quad]
        out.append({"text": text, "conf": round(float(conf), 3),
                    "x0": min(xs), "y0": min(ys), "x1": max(xs), "y1": max(ys)})
    out.sort(key=lambda b: (round(b["y0"] / 12), b["x0"]))
    cache.write_text(json.dumps(out), encoding="utf-8")
    return out


def lines(bx, tol=0.55):
    """Group boxes whose vertical centers overlap into lines, left to right."""
    rows = []
    for b in sorted(bx, key=lambda b: (b["y0"] + b["y1"]) / 2):
        cy, h = (b["y0"] + b["y1"]) / 2, b["y1"] - b["y0"]
        for r in rows:
            if abs(r["cy"] - cy) < tol * max(h, r["h"]):
                r["items"].append(b); break
        else:
            rows.append({"cy": cy, "h": h, "items": [b]})
    return [sorted(r["items"], key=lambda b: b["x0"]) for r in rows]

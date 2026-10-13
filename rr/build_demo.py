"""Package real extractor outputs for the static demo page: demo/demo.json + demo/faxes/*.png.

The demo shows the parser's actual output on each fax, mistakes included, beside the ground truth. Nothing is
hand-edited. Picks 3 dev faxes (layouts the parser was tuned on) and 3 held-out faxes (layouts it never saw).
"""
import json
import shutil
from pathlib import Path

from PIL import Image

from rr.eval import FIELDS, run, same
from rr.parse import extract
from rr.tracker import drafts

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "demo"


def pick(folder, layouts):
    chosen = []
    for lay in layouts:
        cands = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / folder).glob("rr???.json"))]
        cands = [c for c in cands if c["layout"] == lay]
        withmiss = [c for c in cands if c["missing"]]
        chosen.append((withmiss or cands)[0] if lay in ("L2", "L5") else cands[0])
    return chosen


def main():
    if (OUT / "faxes").exists():                 # only the generated assets; demo/index.html is source
        shutil.rmtree(OUT / "faxes")
    (OUT / "faxes").mkdir(parents=True)
    items = []
    for folder, layouts, split in (("data/dev", ["L1", "L2", "L3"], "dev"), ("data/test", ["L4", "L5", "L6"], "held-out")):
        for gt in pick(folder, layouts):
            png = ROOT / folder / f"{gt['id']}.png"
            pred = extract(png)
            im = Image.open(png).convert("L")
            im = im.resize((1100, int(im.height * 1100 / im.width)), Image.LANCZOS).convert("1")
            name = f"{split}-{gt['layout']}-{gt['id']}.png"
            im.save(OUT / "faxes" / name, optimize=True)
            fields = []
            for f in FIELDS:
                fields.append({"field": f, "got": pred.get(f, ""), "truth": gt.get(f, ""),
                               "ok": same(f, pred.get(f), gt.get(f)) if gt.get(f) else not pred.get(f),
                               "truly_missing": not gt.get(f)})
            items.append({"id": gt["id"], "layout": gt["layout"], "split": split, "image": f"faxes/{name}",
                          "urgency": pred.get("urgency") or gt["urgency"], "fields": fields,
                          "missing": pred["missing"], "drafts": drafts(pred)})
    report = {"dev": run(ROOT / "data/dev"), "held_out": run(ROOT / "data/test")}
    (OUT / "demo.json").write_text(json.dumps({"items": items, "report": report}, indent=1), encoding="utf-8")
    print(f"{len(items)} demo faxes; dev {report['dev']['field_accuracy']}, held-out {report['held_out']['field_accuracy']}")


if __name__ == "__main__":
    main()

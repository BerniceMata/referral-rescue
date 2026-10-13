"""Synthetic specialty-referral faxes with ground truth. No real patients, no real providers.

    python -m rr.synth --n 50 --seed 7 --out data/synth

Each referral: data/synth/<id>.json (ground truth) + <id>.png (degraded fax image) + <id>.pdf.
Names are drawn from generic lists, phones use the reserved fictional 555-01xx range, member ids are random,
and no NPI is ever printed. About 30% of referrals are missing at least one field on purpose, so the
missing-field flagging is tested as hard as the extraction.
"""
import argparse
import json
import random
import string
from pathlib import Path
from string import Template

from PIL import Image, ImageFilter, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
LAYOUTS = ROOT / "rr" / "layouts"
CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe"

FIRST = ["James", "Maria", "Robert", "Linda", "Michael", "Patricia", "David", "Jennifer", "Carlos", "Elizabeth",
         "Daniel", "Susan", "Anthony", "Karen", "Marcus", "Nancy", "Kevin", "Angela", "Brian", "Denise", "Luis",
         "Sharon", "Terrence", "Gloria", "Steven", "Rosa", "Gregory", "Tamika", "Raymond", "Helen"]
LAST = ["Johnson", "Garcia", "Williams", "Brown", "Martinez", "Davis", "Rodriguez", "Wilson", "Anderson", "Thomas",
        "Moore", "Jackson", "Lee", "Harris", "Clark", "Lewis", "Walker", "Hall", "Young", "King", "Wright",
        "Lopez", "Hill", "Green", "Adams", "Baker", "Nelson", "Carter", "Mitchell", "Perez"]
PAYERS = ["Aetna", "Blue Cross Blue Shield of Texas", "UnitedHealthcare", "Cigna", "Humana", "Medicare",
          "Texas Medicaid", "Ambetter"]
# fictional referring practices (generic names, not real clinics)
PRACTICES = ["Cedar Hollow Family Medicine", "Northgate Primary Care", "Lakeview Internal Medicine",
             "Prairie Wind Family Clinic", "Riverbend Health Associates", "Oak Terrace Medical Group"]
DX = {
    "Orthopedics": [("M17.11", "Unilateral primary osteoarthritis, right knee"),
                    ("M75.101", "Rotator cuff tear, right shoulder, not specified as traumatic"),
                    ("M54.50", "Low back pain, unspecified"),
                    ("S83.511A", "Sprain of anterior cruciate ligament of right knee, initial encounter"),
                    ("M25.561", "Pain in right knee")],
    "Pulmonology": [("J44.9", "Chronic obstructive pulmonary disease, unspecified"),
                    ("J45.40", "Moderate persistent asthma, uncomplicated"),
                    ("R06.02", "Shortness of breath"),
                    ("G47.33", "Obstructive sleep apnea"),
                    ("R91.1", "Solitary pulmonary nodule")],
}
URGENCY = ["Routine"] * 6 + ["Urgent"] * 3 + ["STAT"]
REQUIRED = ["patient_name", "dob", "phone", "payer", "member_id", "reason"]   # what scheduling needs
DROPPABLE = ["phone", "member_id", "payer", "dob", "icd10"]


def referral(rng, i):
    spec = rng.choice(list(DX))
    code, reason = rng.choice(DX[spec])
    y = rng.randint(1948, 2004)
    gt = {
        "id": f"rr{i:03d}",
        "patient_first": rng.choice(FIRST), "patient_last": rng.choice(LAST),
        "dob": f"{rng.randint(1, 12):02d}/{rng.randint(1, 28):02d}/{y}",
        "phone": f"(214) 555-01{rng.randint(0, 99):02d}",
        "payer": rng.choice(PAYERS),
        "member_id": rng.choice(string.ascii_uppercase) + rng.choice(string.ascii_uppercase)
                     + "".join(rng.choice(string.digits) for _ in range(9)),
        "referring_provider": f"Dr. {rng.choice(FIRST)} {rng.choice(LAST)}",
        "referring_practice": rng.choice(PRACTICES),
        "specialty": spec, "icd10": code, "reason": reason,
        "urgency": rng.choice(URGENCY),
        "date_sent": f"10/{rng.randint(1, 12):02d}/2026",
    }
    gt["patient_name"] = f"{gt['patient_first']} {gt['patient_last']}"
    gt["missing"] = []
    if rng.random() < 0.30:
        gt["missing"] = rng.sample(DROPPABLE, rng.choice([1, 1, 2]))
        for k in gt["missing"]:
            gt[k] = ""
    return gt


def fill(layout, gt):
    tpl = Template((LAYOUTS / f"{layout}.html").read_text(encoding="utf-8"))
    u = gt["urgency"]
    box = lambda v: "[X]" if u == v else "[ ]"
    return tpl.safe_substitute({**gt, "box_routine": box("Routine"), "box_urgent": box("Urgent"),
                                "box_stat": box("STAT"), "urgency_upper": u.upper(),
                                "last_first": f"{gt['patient_last'].upper()}, {gt['patient_first'].upper()}"})


def degrade(png, rng):
    im = Image.open(png).convert("L")
    w, h = im.size
    head = Image.new("L", (w, 40), 255)
    ImageDraw.Draw(head).text((22, 6), f"10/{rng.randint(1, 12):02d}/2026 {rng.randint(8, 17):02d}:{rng.randint(0, 59):02d}"
                              f"   FROM: 214-555-01{rng.randint(0, 99):02d}   P. 001/00{rng.randint(1, 3)}", fill=0,
                              font=ImageFont.load_default(size=26))
    canvas = Image.new("L", (w, h + 40), 255)
    canvas.paste(head, (0, 0)); canvas.paste(im, (0, 40))
    im = canvas.rotate(rng.uniform(-1.3, 1.3), expand=False, fillcolor=255, resample=Image.BICUBIC)
    im = im.resize((1700, int(im.height * 1700 / im.width)), Image.BILINEAR)   # fine-mode fax: about 200 dpi
    px = im.load()
    for _ in range(int(im.width * im.height * 0.0012)):                              # speckle
        px[rng.randrange(im.width), rng.randrange(im.height)] = 0
    im = im.filter(ImageFilter.GaussianBlur(0.5)).point(lambda v: 255 if v > 150 else 0)   # 1-bit fax look
    im.save(png)
    im.convert("RGB").save(png.with_suffix(".pdf"), resolution=200)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--layouts", default="L1,L2,L3,L4,L5,L6")
    ap.add_argument("--out", default="data/synth")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    layouts = a.layouts.split(",")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch(executable_path=CHROME)
        pg = br.new_page(viewport={"width": 1275, "height": 1650}, device_scale_factor=1.6)   # US letter, rendered sharp
        for i in range(a.n):
            gt = referral(rng, i)
            gt["layout"] = layouts[i % len(layouts)]
            pg.set_content(fill(gt["layout"], gt), wait_until="load")
            png = out / f"{gt['id']}.png"
            pg.screenshot(path=str(png), full_page=False)
            degrade(png, rng)
            (out / f"{gt['id']}.json").write_text(json.dumps(gt, indent=1), encoding="utf-8")
        br.close()
    print(f"wrote {a.n} referrals to {out}")


if __name__ == "__main__":
    main()

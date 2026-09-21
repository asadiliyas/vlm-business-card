#!/usr/bin/env python
"""
Generates a handful of synthetic business card images + a matching
labels.json, for two purposes:

1. `python scripts/generate_sample_cards.py --out ../sample_cards` — gives
   the frontend's "try a sample batch" button something to upload without
   needing real business cards.
2. `python scripts/generate_sample_cards.py --out eval_data` — gives
   scripts/eval.py a ground-truth set to score against out of the box.

These are synthetic and clean (flat background, printed text, no glare/skew),
so they will score much higher than real photographed cards — they are a
pipeline smoke test, not a substitute for evaluating against real cards.
The README says this explicitly; do not present eval numbers from this set
as representative accuracy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CARDS = [
    {
        "file": "card_01_clean.jpg",
        "lines": [
            ("Dr. Amara Okafor", 28, True),
            ("Chief Medical Officer", 18, False),
            ("Lakeside General Hospital", 18, False),
            ("Nairobi, Kenya", 15, False),
            ("+254 712 345 678", 15, False),
            ("amara.okafor@lakesidegh.org", 15, False),
        ],
        "labels": {
            "first_name": "Amara", "last_name": "Okafor", "job_title": "Chief Medical Officer",
            "company": "Lakeside General Hospital", "location": "Nairobi, Kenya",
            "phone": "+254712345678", "email": "amara.okafor@lakesidegh.org",
        },
    },
    {
        "file": "card_02_clean.jpg",
        "lines": [
            ("Marcus Chen", 28, True),
            ("VP of Engineering", 18, False),
            ("Brightline Robotics Inc.", 18, False),
            ("Austin, TX, USA", 15, False),
            ("+1 (512) 555-0182", 15, False),
            ("marcus.chen@brightline.io", 15, False),
        ],
        "labels": {
            "first_name": "Marcus", "last_name": "Chen", "job_title": "VP of Engineering",
            "company": "Brightline Robotics Inc.", "location": "Austin, TX, USA",
            "phone": "+15125550182", "email": "marcus.chen@brightline.io",
        },
    },
    {
        "file": "card_03_clean.jpg",
        "lines": [
            ("Priya Sharma", 28, True),
            ("Head of Partnerships", 18, False),
            ("Northwind Logistics Ltd", 18, False),
            ("Singapore", 15, False),
            ("+65 8123 4567", 15, False),
            ("priya.sharma@northwindlog.com", 15, False),
        ],
        "labels": {
            "first_name": "Priya", "last_name": "Sharma", "job_title": "Head of Partnerships",
            "company": "Northwind Logistics Ltd", "location": "Singapore",
            "phone": "+6581234567", "email": "priya.sharma@northwindlog.com",
        },
    },
    {
        "file": "card_04_company_only.jpg",
        "lines": [
            ("Summit & Vale Consulting", 26, True),
            ("Strategy. Growth. Results.", 15, False),
            ("London, United Kingdom", 15, False),
            ("+44 20 7946 0958", 15, False),
            ("info@summitvale.co.uk", 15, False),
        ],
        "labels": {
            "company": "Summit & Vale Consulting", "location": "London, United Kingdom",
            "phone": "+442079460958", "email": "info@summitvale.co.uk",
        },
    },
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in ("arial.ttf", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_card(spec: dict, out_path: Path) -> None:
    width, height = 1000, 600
    img = Image.new("RGB", (width, height), color=(250, 249, 246))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width - 1, height - 1], outline=(200, 200, 195), width=2)
    draw.rectangle([0, 0, 14, height], fill=(31, 41, 55))

    y = 90
    for text, size, bold in spec["lines"]:
        font = _font(size)
        draw.text((60, y), text, fill=(20, 20, 20) if bold else (70, 70, 70), font=font)
        y += int(size * 1.9)

    img.save(out_path, format="JPEG", quality=92)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("sample_cards"))
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    labels = {}
    for spec in CARDS:
        out_path = args.out / spec["file"]
        render_card(spec, out_path)
        labels[spec["file"]] = spec["labels"]
        print(f"  wrote {out_path}")

    (args.out / "labels.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")
    print(f"\nGenerated {len(CARDS)} synthetic cards + labels.json in {args.out}/")
    print("NOTE: these are clean synthetic cards for pipeline smoke-testing only —")
    print("evaluate against real photographed cards before quoting an accuracy number.")


if __name__ == "__main__":
    main()

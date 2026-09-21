#!/usr/bin/env python
"""
Runs the extraction pipeline against a labeled set of business card images
and reports per-field accuracy. This is what turns "the VLM seems to work"
into a number for the README.

Usage:
    python scripts/eval.py --dataset eval_data/ [--backend primary|fallback]

Expects eval_data/ to contain image files alongside a labels.json:

    eval_data/
      card_001.jpg
      card_002.jpg
      labels.json

labels.json shape:
    {
      "card_001.jpg": {"first_name": "Jane", "last_name": "Doe", "company": "Acme", ...},
      "card_002.jpg": {...}
    }

Only the fields present in a card's label are scored for that card, so a
partially-labeled set (e.g. you only bothered to transcribe email + phone)
still produces a meaningful score on those fields.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings, get_settings  # noqa: E402
from app.image_pipeline import preprocess_image, validate_upload  # noqa: E402
from app.postprocess import postprocess_lead  # noqa: E402
from app.vlm.client import VLMClient  # noqa: E402

SCORED_FIELDS = [
    "first_name", "last_name", "job_title", "company", "location", "phone", "email",
]


def normalize_for_compare(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.lower().split())


async def run_eval(dataset_dir: Path, settings: Settings, backend_only: str | None) -> None:
    labels_path = dataset_dir / "labels.json"
    if not labels_path.exists():
        print(f"ERROR: {labels_path} not found. See scripts/eval.py docstring for the expected format.")
        sys.exit(1)

    labels: dict[str, dict] = json.loads(labels_path.read_text(encoding="utf-8"))
    if not labels:
        print("ERROR: labels.json is empty.")
        sys.exit(1)

    if backend_only == "primary":
        settings = settings.model_copy(update={"vlm_fallback_enabled": False})
    elif backend_only == "fallback":
        settings = settings.model_copy(update={"vlm_primary_enabled": False})

    client = VLMClient(settings)

    field_correct = {f: 0 for f in SCORED_FIELDS}
    field_total = {f: 0 for f in SCORED_FIELDS}
    per_card_results = []
    failures = 0

    for filename, expected in sorted(labels.items()):
        image_path = dataset_dir / filename
        if not image_path.exists():
            print(f"  SKIP {filename}: image file not found")
            continue

        raw = image_path.read_bytes()
        try:
            mime = validate_upload(
                raw, max_bytes=int(settings.max_file_mb * 1_000_000),
                allowed_mime_types=settings.allowed_mime_types,
            )
            processed = preprocess_image(
                raw, long_edge_px=settings.image_long_edge_px, thumbnail_px=settings.thumbnail_px
            )
            result = await client.extract(processed.jpeg_bytes, mime_type="image/jpeg")
            cleaned = postprocess_lead(result.lead)
        except Exception as exc:  # noqa: BLE001 — eval must continue past one bad card
            print(f"  FAIL {filename}: {exc}")
            failures += 1
            continue

        card_correct = 0
        card_scored = 0
        mismatches = []
        for field in SCORED_FIELDS:
            if field not in expected:
                continue
            field_total[field] += 1
            card_scored += 1
            actual = getattr(cleaned, field, None)
            if normalize_for_compare(actual) == normalize_for_compare(expected[field]):
                field_correct[field] += 1
                card_correct += 1
            else:
                mismatches.append(f"{field}: expected={expected[field]!r} got={actual!r}")

        backend_used = result.backend_used
        per_card_results.append((filename, card_correct, card_scored, backend_used))
        status = "OK" if card_correct == card_scored else "PARTIAL"
        print(f"  {status:7} {filename}  ({card_correct}/{card_scored} fields, via {backend_used})")
        for m in mismatches:
            print(f"           - {m}")

    print("\n" + "=" * 60)
    print("PER-FIELD ACCURACY")
    print("=" * 60)
    total_correct = 0
    total_scored = 0
    for field in SCORED_FIELDS:
        if field_total[field] == 0:
            continue
        pct = 100 * field_correct[field] / field_total[field]
        total_correct += field_correct[field]
        total_scored += field_total[field]
        print(f"  {field:12} {field_correct[field]:3}/{field_total[field]:<3} ({pct:5.1f}%)")

    overall = 100 * total_correct / total_scored if total_scored else 0.0
    print("-" * 60)
    print(f"  {'OVERALL':12} {total_correct:3}/{total_scored:<3} ({overall:5.1f}%)")
    print(f"  Cards that errored out entirely: {failures}/{len(labels)}")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=Path("eval_data"),
                         help="Directory containing labeled card images + labels.json")
    parser.add_argument("--backend", choices=["primary", "fallback"], default=None,
                         help="Force a single backend instead of the default primary->fallback chain")
    args = parser.parse_args()

    settings = get_settings()
    asyncio.run(run_eval(args.dataset, settings, args.backend))


if __name__ == "__main__":
    main()

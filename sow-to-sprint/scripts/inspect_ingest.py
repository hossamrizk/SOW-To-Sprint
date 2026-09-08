"""Inspect the output of `src.ingest.ingest_docx` on any SOW file.

Prints a full report of what the ingest layer sees:
    1. Header — the source file + total clause count
    2. Distinct section headings encountered
    3. All clauses in a compact table (id / section / preview)
    4. The full annotated_text (what the LLM would see)
    5. Optionally writes both to a JSON file for archival

Run:
    python3 scripts/inspect_ingest.py <path_to.docx>
    python3 scripts/inspect_ingest.py <path_to.docx> --save

If no path is given, defaults to the cashback SOW at
/home/hussam/Personal/Dsquares/SOW-2026-014-cashback-offers-v2.docx.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

# Allow running this script from any working directory.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingest import ingest_docx


DEFAULT_SOW = Path("/home/hussam/Personal/Dsquares/SOW-2026-014-cashback-offers-v2.docx")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect ingest.py output")
    parser.add_argument(
        "docx",
        nargs="?",
        default=str(DEFAULT_SOW),
        help="Path to the .docx SOW (default: cashback SOW)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Also write the report to data/runs/ingest-<filename>.json",
    )
    parser.add_argument(
        "--full-text",
        action="store_true",
        help="Print the full annotated_text (default: only first 60 lines)",
    )
    args = parser.parse_args()

    path = Path(args.docx)
    if not path.exists():
        print(f"✗ file not found: {path}")
        sys.exit(1)

    # ---- 1. Ingest ---------------------------------------------------------
    print("=" * 78)
    print(f"INGEST INSPECTION")
    print("=" * 78)
    print(f"source file : {path}")
    print(f"file size   : {path.stat().st_size:,} bytes")
    print()

    ingested = ingest_docx(path)

    # ---- 2. Header stats --------------------------------------------------
    print(f"total clauses extracted : {len(ingested.clauses)}")
    print(f"annotated_text length    : {len(ingested.annotated_text):,} chars")
    print()

    # Distinct section headings encountered
    section_counts = Counter(c.section for c in ingested.clauses)
    print("clauses per section:")
    for section, n in section_counts.most_common():
        print(f"  {n:3d}  {section}")
    print()

    # ---- 3. Compact clause table -----------------------------------------
    print("-" * 78)
    print(f"{'ID':<8} {'SECTION':<30} PREVIEW")
    print("-" * 78)
    for c in ingested.clauses:
        section = (c.section or "")[:28]
        preview = c.text[:60].replace("\n", " ")
        if len(c.text) > 60:
            preview += "…"
        print(f"{c.id:<8} {section:<30} {preview}")
    print()

    # ---- 4. Annotated text -----------------------------------------------
    print("=" * 78)
    print("ANNOTATED TEXT (what the LLM sees in Stage 2)")
    print("=" * 78)
    lines = ingested.annotated_text.splitlines()
    if args.full_text or len(lines) <= 60:
        print(ingested.annotated_text)
    else:
        # Show first 30 + last 30 lines
        for line in lines[:30]:
            print(line)
        print(f"\n… [omitted {len(lines) - 60} lines — pass --full-text to see everything] …\n")
        for line in lines[-30:]:
            print(line)
    print()

    # ---- 5. Sanity checks -------------------------------------------------
    print("=" * 78)
    print("SANITY CHECKS")
    print("=" * 78)
    ids = [c.id for c in ingested.clauses]
    dup_ids = [i for i, count in Counter(ids).items() if count > 1]
    print(f"  duplicate clause ids           : {'✗ ' + str(dup_ids) if dup_ids else '✓ none'}")

    empty_clauses = [c.id for c in ingested.clauses if not c.text.strip()]
    print(f"  empty-text clauses             : {'✗ ' + str(empty_clauses) if empty_clauses else '✓ none'}")

    ids_in_annotated = sum(1 for c in ingested.clauses if f"[{c.id}]" in ingested.annotated_text)
    print(f"  ids present in annotated_text  : {ids_in_annotated} / {len(ingested.clauses)}")

    preamble = sum(1 for c in ingested.clauses if c.section == "(preamble)")
    if preamble:
        print(f"  clauses in (preamble)          : {preamble}  (usually cover-page table rows)")

    # ---- 6. Save to JSON (optional) --------------------------------------
    if args.save:
        out_dir = Path(__file__).resolve().parents[1] / "data" / "runs"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"ingest-{path.stem}.json"
        payload = {
            "source_file": ingested.source_file,
            "clause_count": len(ingested.clauses),
            "clauses": [
                {"id": c.id, "section": c.section, "text": c.text}
                for c in ingested.clauses
            ],
            "annotated_text": ingested.annotated_text,
        }
        out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        print()
        print(f"✓ report written to {out_path}")


if __name__ == "__main__":
    main()

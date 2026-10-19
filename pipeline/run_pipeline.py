"""CLI entry point: Excel bulletin → long-format CSV."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python pipeline/run_pipeline.py` without installing a package
sys.path.insert(0, str(Path(__file__).resolve().parent))

from parsers import OUTPUT_COLUMNS, parse_workbook  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest CAPMAS-style labor Excel sheets into long-format CSV."
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Path to Sample_Input.xlsx (or similar workbook)",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Destination CSV path",
    )
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.is_file():
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 1

    df = parse_workbook(str(input_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig matches Excel-friendly sample; keep column order stable
    df = df.reindex(columns=OUTPUT_COLUMNS)
    df.to_csv(output_path, index=False, encoding="utf-8-sig", lineterminator="\n")
    print(f"Wrote {len(df)} rows → {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Assert the 27-row Sample_Output.csv is a subset of the generated extract."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

KEY_COLS = [
    "رقم_الجدول",
    "اسم_المؤشر",
    "محافظات الجمهورية",
    "محل الإقامة",
    "النوع",
    "الاقسام الرئيسية للمهن",
    "الحالة التعليمية",
    "الحالة العملية",
    "نوع_المنشأة",
    "القطاع",
    "وحدة القياس",
]


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        out[col] = out[col].fillna("").astype(str).str.strip()
    out["القيمة"] = pd.to_numeric(out["القيمة"], errors="coerce")
    return out


def assert_sample_subset(generated_path: Path, sample_path: Path) -> None:
    generated = _prep(pd.read_csv(generated_path, dtype=str, encoding="utf-8-sig"))
    sample = _prep(pd.read_csv(sample_path, dtype=str, encoding="utf-8-sig"))

    missing = []
    mismatches = []
    for _, row in sample.iterrows():
        mask = pd.Series(True, index=generated.index)
        for col in KEY_COLS:
            mask &= generated[col] == row[col]
        hits = generated.loc[mask]
        if hits.empty:
            missing.append({c: row[c] for c in KEY_COLS + ["القيمة"]})
            continue
        got = float(hits.iloc[0]["القيمة"])
        expected = float(row["القيمة"])
        if abs(got - expected) > 1e-9:
            mismatches.append((row.to_dict(), got))

    if missing or mismatches:
        lines = []
        if missing:
            lines.append(f"{len(missing)} sample rows missing from generated output")
            for m in missing[:8]:
                lines.append(f"  missing: {m}")
        if mismatches:
            lines.append(f"{len(mismatches)} value mismatches")
            for m in mismatches[:8]:
                lines.append(f"  {m}")
        raise AssertionError("\n".join(lines))

    print(f"OK — all {len(sample)} sample rows found with matching values in {generated_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated", default=str(ROOT / "output" / "Sample_Output.csv"))
    parser.add_argument("--sample", default=r"c:\Users\Saad\Downloads\Sample_Output.csv")
    args = parser.parse_args(argv)
    assert_sample_subset(Path(args.generated), Path(args.sample))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

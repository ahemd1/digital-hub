"""Per-sheet parsers that unpivot Sample_Input.xlsx layouts into long form."""

from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from normalize import canonical_enabled, clean_label, format_value, normalize_arabic

OUTPUT_COLUMNS = [
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
    "القيمة",
]

INDICATORS = {
    "table 2": "المشتغلون طبقاً للحالة التعليمية",
    "table 18": "المتعطلون طبقاً للحالة التعليمية",
    "table 10": "المشتغلون طبقاً للحالة العملية والمهن",
    "ملحق 1": "قوة العمل والمشتغلين والمتعطلين طبقا للمحافظات",
}

UNIT = "عدد"

# "Republic total" governorate and "all" residence. The source workbook spells these
# differently per sheet (table 10 vs tables 2/18 vs ملحق 1); the canonical constants
# unify them, the raw constants reproduce the provided sample verbatim.
GOV_TOTAL_CANONICAL = "اجمالي الجمهوريه"
GOV_TOTAL_RAW = "إجمالى الجمهورية"
RESIDENCE_TOTAL_CANONICAL = "جمله"
RESIDENCE_TOTAL_RAW = "جملة"


def _gov_total() -> str:
    return GOV_TOTAL_CANONICAL if canonical_enabled() else GOV_TOTAL_RAW


def _residence_total() -> str:
    return RESIDENCE_TOTAL_CANONICAL if canonical_enabled() else RESIDENCE_TOTAL_RAW


def _empty_row(**overrides: Any) -> dict[str, Any]:
    base = {col: "" for col in OUTPUT_COLUMNS}
    base["وحدة القياس"] = UNIT
    base.update(overrides)
    return base


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip() == ""


def _is_data_row(values: Iterable[Any], value_start: int, value_end: int) -> bool:
    """True if any numeric/placeholder cell exists in the measure columns."""
    for v in list(values)[value_start:value_end]:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        if isinstance(v, (int, float)):
            return True
        text = str(v).strip()
        if text and text.lower() not in {"male", "female", "total", "urban", "rural"}:
            # Arabic labels in gender col are not measures; measures are further right
            try:
                float(text.replace(",", ""))
                return True
            except ValueError:
                if text in {"-", ".", "..", "...", "…"}:
                    return True
    return False


def parse_education(df: pd.DataFrame, sheet_name: str) -> pd.DataFrame:
    """Parse table 2 / table 18 (education × governorate × residence × gender)."""
    # Row index: 4 = Arabic education headers (0-based), data from row 6
    edu_headers = [clean_label(df.iat[4, c]) for c in range(3, 10)]  # D–J
    rows: list[dict[str, Any]] = []

    gov = None
    residence = None
    for r in range(6, len(df)):
        raw = [df.iat[r, c] if c < df.shape[1] else None for c in range(0, 14)]
        # Stop at trailing empties
        if all(_is_empty(v) for v in raw[:11]):
            continue
        # Skip English mirror columns-only rows
        if not _is_data_row(raw, 3, 10):
            continue

        if not _is_empty(raw[0]):
            gov = raw[0]
        if not _is_empty(raw[1]):
            residence = raw[1]
        gender = raw[2]
        if _is_empty(gender):
            continue

        for offset, edu in enumerate(edu_headers):
            if not edu:
                continue
            val = format_value(raw[3 + offset])
            rows.append(
                _empty_row(
                    **{
                        "رقم_الجدول": sheet_name,
                        "اسم_المؤشر": INDICATORS[sheet_name],
                        "محافظات الجمهورية": normalize_arabic(gov),
                        "محل الإقامة": normalize_arabic(residence),
                        "النوع": normalize_arabic(gender),
                        "الحالة التعليمية": edu,
                        "القيمة": val,
                    }
                )
            )
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def parse_occupation(df: pd.DataFrame) -> pd.DataFrame:
    """Parse table 10 (occupation × employment status × establishment type)."""
    sheet_name = "table 10"
    # Row 5 (idx 4): employment status on pair starts; row 6 (idx 5): establishment
    # Cols D–K = four statuses × inside/outside; L–M = الإجمالي totals
    emp_status: list[str] = []
    est_type: list[str] = []
    last_status = ""
    for c in range(3, 13):
        cell = df.iat[4, c] if c < df.shape[1] else None
        if not _is_empty(cell):
            last_status = clean_label(cell)
        elif c >= 11:
            total_cell = df.iat[3, 11] if df.shape[1] > 11 else "الإجمالى"
            last_status = clean_label(total_cell) if not _is_empty(total_cell) else "الإجمالى"
        emp_status.append(last_status)
        est_type.append(clean_label(df.iat[5, c]))

    rows: list[dict[str, Any]] = []
    occupation = None
    residence = None
    for r in range(6, len(df)):
        raw = [df.iat[r, c] if c < df.shape[1] else None for c in range(0, 14)]
        if all(_is_empty(v) for v in raw[:13]):
            continue
        if not _is_data_row(raw, 3, 13):
            continue

        if not _is_empty(raw[0]):
            occupation = raw[0]
        if not _is_empty(raw[1]):
            residence = raw[1]
        gender = raw[2]
        if _is_empty(gender):
            continue

        for offset in range(10):  # D–M
            val = format_value(raw[3 + offset])
            rows.append(
                _empty_row(
                    **{
                        "رقم_الجدول": sheet_name,
                        "اسم_المؤشر": INDICATORS[sheet_name],
                        # Sheet is republic-level occupation breakdown
                        "محافظات الجمهورية": _gov_total(),
                        "محل الإقامة": normalize_arabic(residence),
                        "النوع": normalize_arabic(gender),
                        "الاقسام الرئيسية للمهن": normalize_arabic(occupation),
                        "الحالة العملية": emp_status[offset],
                        "نوع_المنشأة": est_type[offset],
                        "القيمة": val,
                    }
                )
            )
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def parse_appendix(df: pd.DataFrame) -> pd.DataFrame:
    """Parse ملحق 1 (governorate × metric group × gender)."""
    sheet_name = "ملحق 1"
    # Row 5 (idx 4): metric groups; Row 6 (idx 5): gender
    metrics: list[str] = []
    genders: list[str] = []
    last_metric = ""
    for c in range(1, 13):
        mcell = df.iat[4, c] if c < df.shape[1] else None
        if not _is_empty(mcell):
            # Sector labels in the sample keep ta-marbuta (قوة العمل, معدل البطالة)
            last_metric = clean_label(mcell, normalize=False)
        metrics.append(last_metric)
        genders.append(normalize_arabic(df.iat[5, c]))

    rows: list[dict[str, Any]] = []
    for r in range(7, len(df)):  # skip English gender row (idx 6)
        gov = df.iat[r, 0] if df.shape[1] else None
        if _is_empty(gov):
            continue
        # Skip pure English name rows (no numeric measures)
        raw_measures = [df.iat[r, c] for c in range(1, 13)]
        if not any(
            (isinstance(v, (int, float)) and not _is_empty(v))
            or (isinstance(v, str) and v.strip() in {"-", ".", "...", "…"})
            for v in raw_measures
        ):
            continue

        for offset in range(12):
            val = format_value(df.iat[r, 1 + offset])
            rows.append(
                _empty_row(
                    **{
                        "رقم_الجدول": sheet_name,
                        "اسم_المؤشر": INDICATORS[sheet_name],
                        "محافظات الجمهورية": normalize_arabic(gov),
                        "محل الإقامة": _residence_total(),  # unify with tables 2/18/10
                        "النوع": genders[offset],
                        "القطاع": metrics[offset],
                        "القيمة": val,
                    }
                )
            )
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def parse_workbook(path: str) -> pd.DataFrame:
    """Read all known sheets and concatenate long-format frames."""
    xl = pd.ExcelFile(path)
    frames: list[pd.DataFrame] = []

    for sheet in xl.sheet_names:
        df = pd.read_excel(xl, sheet_name=sheet, header=None)
        key = sheet.strip()
        if key in {"table 2", "table 18"}:
            frames.append(parse_education(df, key))
        elif key == "table 10":
            frames.append(parse_occupation(df))
        elif key in {"ملحق 1", "ملحق1"}:
            frames.append(parse_appendix(df))

    if not frames:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    return pd.concat(frames, ignore_index=True)

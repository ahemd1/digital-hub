"""Arabic text cleanup and null/zero placeholder mapping."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Tatweel + Arabic combining marks (tashkeel)
_DIACRITICS_RE = re.compile(r"[\u064B-\u065F\u0670\u0640]")
_WHITESPACE_RE = re.compile(r"\s+")
_TRAILING_DASH_RE = re.compile(r"[-\u2013\u2014]+\s*$")

# Placeholders that mean missing / zero in CAPMAS-style sheets
_NULL_PLACEHOLDERS = {"", "-", ".", "..", "...", "…", "—", "–", "na", "n/a", "null"}

# Sample-aligned spellings that differ from naive character folding
_VALUE_ALIASES = {
    "الاجمالي": "الإجمالى",
}

# Cross-table spelling variants that denote the same concept. Source bulletins spell
# the same thing differently from sheet to sheet; keys are the already-folded forms.
_CANONICAL_ALIASES = {
    "الجمله": "جمله",  # residence "total": tables 2/18 write الجمله, table 10 writes جمله
    "بور سعيد": "بورسعيد",  # Port Said: ملحق 1 splits the word, tables 2/18 do not
}

# Broken spacing inside longer labels (substring, not whole-cell, aliases).
_SUBSTRING_FIXES = {
    "مشغلواالمصانع": "مشغلوا المصانع",
}

_CANONICAL = True


def set_canonical(enabled: bool) -> None:
    """Enable/disable cross-table spelling unification (enabled by default)."""
    global _CANONICAL
    _CANONICAL = bool(enabled)


def canonical_enabled() -> bool:
    return _CANONICAL


def canonicalize(text: str) -> str:
    """Collapse known cross-table spelling variants onto one canonical value."""
    for broken, fixed in _SUBSTRING_FIXES.items():
        text = text.replace(broken, fixed)
    for variant, canonical in _CANONICAL_ALIASES.items():
        if text == variant:
            return canonical
    return text


def _strip_bilingual(text: str) -> str:
    """Keep the Arabic portion when cells embed English on a new line."""
    if "\n" in text:
        text = text.split("\n", 1)[0]
    return text


def normalize_arabic(value: Any) -> str:
    """Normalize Arabic labels to match Sample_Output.csv conventions."""
    if value is None:
        return ""
    try:
        import math

        if isinstance(value, float) and math.isnan(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""

    text = _strip_bilingual(text)
    text = _TRAILING_DASH_RE.sub("", text).strip()
    text = _DIACRITICS_RE.sub("", text)

    # Hamza / alef / ya / ta-marbuta folding (keep ؤ/ئ — sample retains مؤهل)
    trans = str.maketrans(
        {
            "أ": "ا",
            "إ": "ا",
            "آ": "ا",
            "ٱ": "ا",
            "ى": "ي",
            "ة": "ه",
        }
    )
    text = text.translate(trans)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if _CANONICAL:
        text = canonicalize(text)
    return _VALUE_ALIASES.get(text, text)


def format_value(raw: Any) -> float | int:
    """Map null placeholders to 0; preserve numeric rates (e.g. 5.4)."""
    if raw is None:
        return 0
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        if isinstance(raw, float) and raw.is_integer():
            return int(raw)
        return raw

    text = str(raw).strip()
    if text.lower() in _NULL_PLACEHOLDERS:
        return 0

    # Normalize Arabic decimal separator if present
    text = text.replace(",", "")
    try:
        num = float(text)
    except ValueError:
        return 0
    if num.is_integer():
        return int(num)
    return num


def clean_label(value: Any, *, normalize: bool = True) -> str:
    """Whitespace cleanup with optional Arabic normalization."""
    if value is None:
        return ""
    text = _strip_bilingual(str(value)).strip()
    text = _TRAILING_DASH_RE.sub("", text).strip()
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if normalize:
        return normalize_arabic(text)
    return text

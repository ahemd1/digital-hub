# DE Technical Assessment — Excel Pipeline

Python pipeline that ingests `Sample_Input.xlsx` (multi-sheet Arabic labor tables), forward-fills merged hierarchies, unpivots to long form, normalizes Arabic labels, and writes CSV matching the schema in `Sample_Output.csv`.

Written answers (Parts 1–3) are in [`ASSESSMENT.md`](ASSESSMENT.md).

## Setup

```bash
pip install -r requirements.txt
```

## Arabic standardization

Two layers, both in `pipeline/normalize.py`:

1. **Character cleanup** — strips tashkeel/tatweel, trailing dashes, and collapsed
   whitespace; folds `أ إ آ ٱ → ا`, `ى → ي`, `ة → ه`; drops English mirror text
   packed into the same cell.
2. **Cross-table unification** (`set_canonical`, on by default) — the bulletins spell
   the same thing differently per sheet, so equivalent labels collapse to one canonical
   value:

   | Concept | Variants in the source | Canonical |
   |---|---|---|
   | Republic total | `اجمالي الجمهوريه` (tables 2/18/ملحق 1), `إجمالى الجمهورية` (table 10) | `اجمالي الجمهوريه` |
   | Residence total | `الجمله` (tables 2/18), `جمله` (table 10), `جملة` (ملحق 1) | `جمله` |
   | Port Said | `بورسعيد` (tables 2/18), `بور سعيد` (ملحق 1) | `بورسعيد` |
   | Occupation label | `مشغلواالمصانع` (missing space) | `مشغلوا المصانع` |

Pass `--sample-spellings` to keep the provided sample's literal spellings instead of
unifying (useful for a byte-for-byte diff against `Sample_Output.csv`).

## Run

```bash
python pipeline/run_pipeline.py --input "c:\Users\Saad\Downloads\Sample_Input.xlsx" --output output/Sample_Output.csv
```

The provided sample uses inconsistent spellings for the same concept, so the
validation test canonicalizes both sides before comparing keys/values (it still checks
all 27 rows exactly on the measures).

## Validate against the 27-row sample

```bash
python tests/test_against_sample.py --generated output/Sample_Output.csv --sample "c:\Users\Saad\Downloads\Sample_Output.csv"
```

## Layout

```
pipeline/
  normalize.py      # Arabic + null mapping
  parsers.py        # per-sheet unpivots
  run_pipeline.py   # CLI entry
tests/
  test_against_sample.py
```

## Scalability

- Process **one workbook at a time**; never load hundreds of files into one DataFrame.
- Use a **bounded process pool** (or Airflow/Celery tasks) — one file per worker.
- Write CSV per file (or stream append); concatenate downstream if needed.
- Sheets inside a workbook are parsed independently so peak memory stays near one sheet.

# DE Technical Assessment — Excel Pipeline

Python pipeline that ingests `Sample_Input.xlsx` (multi-sheet Arabic labor tables), forward-fills merged hierarchies, unpivots to long form, normalizes Arabic labels, and writes CSV matching the schema in `Sample_Output.csv`.

Written answers (Parts 1–3) are in [`ASSESSMENT.md`](ASSESSMENT.md).

## Setup

```bash
pip install -r requirements.txt
```

## Run

```bash
python pipeline/run_pipeline.py --input "c:\Users\Saad\Downloads\Sample_Input.xlsx" --output output/Sample_Output.csv
```

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

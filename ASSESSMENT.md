# Data Engineering Technical Assessment

Answers for Parts 1–3 (English). The Excel ingestion pipeline is in `pipeline/` (see `README.md`).

---

## Part 1: Architecture & Modeling Challenge

### Task 1.1: Storage Architecture Strategy

#### 1. Warehouse vs Lake vs Lakehouse — recommendation

| Pattern | Strengths | Gaps for this scenario |
|---|---|---|
| **Traditional data warehouse** | Strong schema, BI-friendly, governance | Awkward for raw clickstream and large semi-structured web logs; costly to land every event before modeling |
| **Data lake** | Cheap storage for raw ERP extracts + clickstream | Weak concurrency/governance for executive dashboards; SQL/engineering burden without a warehouse layer |
| **Data lakehouse** | Lake storage for raw/history + warehouse-style tables for analytics; supports batch + streaming | Needs clear medallion/layering and ownership |

**Recommendation: Lakehouse**, aligned to the target stack (ClickHouse + PostgreSQL analytics, dbt, Airflow).

- **OLTP (keep out of the analytics path for heavy BI):** SQL Server ERP and the e-commerce PostgreSQL remain systems of record for transactions and registrations. Nightly/CDC extracts land in the lake (bronze), are cleaned (silver), and modeled (gold).
- **OLAP:** Curated dimensional models and aggregates live in ClickHouse (and/or analytics PostgreSQL) for cohort analysis, funnels, and dashboards. ClickHouse handles high-volume clickstream; Postgres can hold smaller conformed dimensions and serving tables if needed.

This hybrid fits store sales (structured, moderate volume) plus web events (high volume, evolving schema) without querying production OLTP for analytics.

#### 2. Power BI / Tableau on production PostgreSQL

Connecting dashboards directly to the **production** OLTP Postgres is a false economy:

- **Locks & contention:** Analytical scans compete with OLTP writes; long queries hold buffers and can block or slow checkouts/registrations.
- **I/O & cache pollution:** Full-table or large-range scans push hot transactional pages out of shared buffers.
- **No columnar / MPP scan path:** Row-store Postgres is optimized for point lookups and short transactions, not wide historical aggregations. Warehouses/ClickHouse use columnar storage, compression, and vectorized execution.
- **Schema coupling:** Report models freeze production tables; product changes become dashboard breakages.
- **Security & blast radius:** Broad read access to PII/transaction tables increases risk.

Use a replica at minimum, and preferably curated OLAP tables fed by Airflow/dbt.

---

### Task 1.2: Dimension & Fact Modeling

#### 1. Conformed `dim_customers`

Design one customer dimension consumed by both store and web facts:

- **Surrogate key:** `customer_sk` (warehouse-generated).
- **Natural / source keys:** `erp_customer_id`, `web_user_id` (nullable until matched), plus stable business attributes (email, phone, national id if available).
- **Matching:** deterministic keys first (email/phone normalized); then fuzzy name+address; maintain a mapping table (`source_system`, `source_id`, `customer_sk`, `match_confidence`, `match_method`).
- **Golden record:** pick surviving attributes by survivorship rules (e.g. ERP wins for billing address, web wins for last login email).

**Challenges:** duplicate accounts, shared household phones/emails, typos, GDPR/consent differences between systems, late-arriving matches that require fact re-keying, and conflicting demographics.

#### 2. Junk dimension for degenerate flags

`payment_method` × `delivery_type` × `promotion_applied` are low-cardinality flags. A **junk dimension** (`dim_order_context`) holds the Cartesian product (or observed combinations) with a single `order_context_sk` on the sales fact. Facts stay narrow; filters remain dimensional without three tiny snowflake tables.

Example grain: one row per `(payment_method, delivery_type, promotion_applied)`.

#### 3. SCD Type 2 (address) vs SCD Type 3 (loyalty)

**SCD2 — shipping address (history):** keep versions with `valid_from`, `valid_to`, `is_current`. Facts store `customer_address_sk` (or `customer_sk` + address version) as of order date.

dbt incremental outline:

```sql
-- models/dim_customer_address.sql
{{ config(materialized='incremental', unique_key='address_sk') }}

with incoming as (
  select
    {{ dbt_utils.generate_surrogate_key(['customer_sk', 'valid_from']) }} as address_sk,
    customer_sk,
    shipping_address,
    region_id,
    valid_from,
    cast(null as timestamp) as valid_to,
    true as is_current
  from {{ ref('stg_customer_address_changes') }}
),
closed as (
  -- on incremental runs: close prior is_current rows when address changed
  select ...
)
select * from incoming
{% if is_incremental() %}
union all
select * from closed
{% endif %}
```

**SCD3 — loyalty tier:** wide current row with `current_tier`, `previous_tier` (and maybe `tier_changed_at`). No full history—only current vs previous for quick deltas. Schema differs by storing prior value in columns on the same row rather than adding version rows.

---

## Part 2: Data Pipelines & Performance Optimization

### Task 2.1: SSIS Lookup Cache Modes

#### 1. Modes

| Mode | Behavior |
|---|---|
| **Full Cache** | Load entire reference set into memory before rows flow; fastest lookups; highest memory |
| **Partial Cache** | Cache entries as they are looked up (with size limit); miss → query DB, then cache |
| **No Cache** | Every row hits the database; lowest memory; most round-trips |

#### 2. Choice for OOM + top-100 products

Use **Partial Cache**. Full Cache on 15M products caused OOM. Partial Cache keeps the hot ~100 products in memory after first hits (covering ~95% of traffic) while avoiding loading the full dimension. No Cache would thrash the DB with per-row lookups.

Optionally pre-seed a small reference query for the top 100 SKUs and keep cache size capped to that working set.

#### 3. No-match row redirection

Configure the Lookup error output (or “Redirect rows to no match output”) to send unmatched product keys to an error/quarantine path: log `order_id`, `product_id`, package execution id; do not silently drop. Optionally default `category_id` only in a controlled downstream path after review.

---

### Task 2.2: ClickHouse Partitioning & Ordering

#### 1. Strategy for `user_sessions`

- **PARTITION BY** `toYYYYMM(event_date)` (monthly). Matches retention, tiered storage, and partition pruning for date-bounded funnels.
- **ORDER BY** `(user_id, event_time)` (primary key / sorting key). Enables efficient per-user session scans and sparse index granules on `user_id`.

Also keep `event_date` as a proper Date column for partition expression clarity.

#### 2. Why not `user_id` or millisecond timestamp partitions

ClickHouse performs best with a **modest** number of partitions (typically dozens to low hundreds, not millions). Partitioning by `user_id` or `toUnixTimestamp64Milli(event_time)` creates an explosion of parts:

- Heavy merge scheduler load and “too many parts” errors
- Poor insert batching and memory overhead per part
- Ineffective pruning (queries rarely hit one user partition usefully at lake scale)

Use partitions for coarse time (or large tenant), and put selective columns in `ORDER BY`, not in `PARTITION BY`.

---

## Part 3: SQL & Linux Hands-on Mastery

### Task 3.1: Logical order & window rewrite

#### 1. Logical clause order

For the given query shape, logical processing is:

1. `FROM`
2. `WHERE`
3. `GROUP BY`
4. `HAVING`
5. **Window** (`OVER` / `LAG` / `LEAD`) — evaluated after `HAVING`, on the grouped result
6. `SELECT` (including window outputs)
7. (`ORDER BY` / `LIMIT` if present — not in the given query)

#### 2. The bug and rewrite

`LAG`/`LEAD` run **after** `GROUP BY`/`HAVING`. Grouping to `(user_id, page_id, visit_time)` collapses duplicates before the window, so “page transitions” are computed on the aggregated grain, not the filtered raw hit stream. `HAVING COUNT(*) > 1` also does not mean “keep pages with more than one interaction globally”—it filters groups after aggregation.

Correct pattern: aggregate/filter in a CTE, then apply windows on the filtered detail (or on the intended grain):

```sql
WITH page_counts AS (
  SELECT user_id, page_id
  FROM web_traffic
  WHERE visit_time >= DATE '2026-07-01'
  GROUP BY user_id, page_id
  HAVING COUNT(*) > 1
),
filtered AS (
  SELECT w.user_id, w.page_id, w.visit_time
  FROM web_traffic w
  INNER JOIN page_counts p
    ON w.user_id = p.user_id
   AND w.page_id = p.page_id
  WHERE w.visit_time >= DATE '2026-07-01'
)
SELECT
  user_id,
  page_id,
  visit_time,
  LAG(page_id)  OVER (PARTITION BY user_id ORDER BY visit_time) AS previous_page,
  LEAD(page_id) OVER (PARTITION BY user_id ORDER BY visit_time) AS next_page
FROM filtered;
```

---

### Task 3.2: De-duplication DML

#### 1. Delete duplicates, keep earliest `load_timestamp`

```sql
DELETE FROM raw_orders a
USING raw_orders b
WHERE a.order_id = b.order_id
  AND a.load_timestamp > b.load_timestamp;
```

If timestamps can tie, add a tie-breaker (e.g. `ctid`):

```sql
DELETE FROM raw_orders a
USING raw_orders b
WHERE a.order_id = b.order_id
  AND (
        a.load_timestamp > b.load_timestamp
     OR (a.load_timestamp = b.load_timestamp AND a.ctid > b.ctid)
      );
```

#### 2. Why `NOT IN` deletes fail at 100M rows — alternative

A `DELETE ... WHERE ctid NOT IN (SELECT ...)` style plan often:

- Builds a huge anti-join / materializes massive ID lists
- Causes long transactions, bloat, and WAL spikes
- Holds locks that block ingest

**Better at scale:** build a clean table, then swap:

```sql
CREATE TABLE raw_orders_dedup AS
SELECT DISTINCT ON (order_id) *
FROM raw_orders
ORDER BY order_id, load_timestamp ASC, ctid ASC;

BEGIN;
ALTER TABLE raw_orders RENAME TO raw_orders_old;
ALTER TABLE raw_orders_dedup RENAME TO raw_orders;
COMMIT;
-- recreate indexes/constraints; DROP raw_orders_old after validation
```

Or batch deletes by `order_id` ranges in Airflow to keep transactions small.

---

### Task 3.3: Linux & Logs

#### 1. Find and kill the process on port 8080

```bash
# identify listener
sudo lsof -iTCP:8080 -sTCP:LISTEN -n -P
# or: sudo fuser 8080/tcp

# forceful terminate (replace <PID>)
sudo kill -9 <PID>

# one-liner variants:
sudo fuser -k 8080/tcp
# or: kill -9 $(sudo lsof -t -iTCP:8080 -sTCP:LISTEN)
```

#### 2. Search a 10 GB log with context (no editor)

```bash
grep -n -C 5 'OutOfMemoryError' /var/log/airflow/dag_execution.log
```

---

## Excel Pipeline — Scalability Note

The sample workbook is processed **one sheet at a time** with pandas; values are melted to long form and written to CSV without holding hundreds of workbooks in memory.

For hundreds of files:

- **Process files sequentially or with a bounded process pool** (multiprocessing/Celery workers), one workbook per worker.
- **Do not materialize the full lake of workbooks** in a single DataFrame; stream writes (`to_csv` append or per-file outputs then concatenate).
- **Orchestrate with Airflow:** each file (or batch of N files) is a task; retries and backpressure prevent memory collapse.
- **Normalize in vectorized pandas/pyarrow**, not cell-by-cell Python over the entire archive.

See `README.md` and `pipeline/` for the implementation.

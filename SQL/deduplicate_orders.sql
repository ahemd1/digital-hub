-- Task 3.2: de-duplicate raw_orders, keep the EARLIEST load_timestamp per order_id (PostgreSQL)
--
-- ctid is the physical row locator (block, offset). It is the only per-row handle
-- available because the table has no primary key. It is NOT a business key: it changes
-- after UPDATE, VACUUM FULL, CLUSTER, so use it only inside ONE statement/transaction.

-- 1) The single DML statement (the one the assessment asks for) ----------------
DELETE FROM raw_orders AS r
USING (
    SELECT ctid AS row_ctid,
           ROW_NUMBER() OVER (
               PARTITION BY order_id
               ORDER BY load_timestamp ASC, ctid ASC     -- ctid breaks ties deterministically
           ) AS rn
    FROM raw_orders
) AS ranked
WHERE r.ctid = ranked.row_ctid
  AND ranked.rn > 1;

-- How "earliest" is retained: rn = 1 is the row with the smallest load_timestamp per
-- order_id; every other row (rn > 1) is deleted.
-- Ties: if two rows share order_id AND load_timestamp, nothing in the data says which one
-- is "right". ctid ASC picks one arbitrarily-but-deterministically (the physically first).
-- That is a convenience, not a business rule. If the duplicates are fully identical this is
-- harmless; if they differ in other columns, a business rule is needed.
-- NULL load_timestamp sorts LAST in ASC order in PostgreSQL, so a NULL row is kept only if
-- it is the sole row for that order_id. A NULL order_id forms its own partition: all rows
-- with NULL order_id are treated as duplicates of each other -> check before running.

-- 2) Why NOT IN is risky / slow --------------------------------------------------
--   DELETE FROM raw_orders WHERE ctid NOT IN (<subquery listing the rows to keep>)
--   * NOT IN against a subquery with a NULL returns UNKNOWN for every row -> deletes nothing
--     (or the wrong thing). NOT EXISTS / anti-join does not have this trap.
--   * PostgreSQL often cannot turn NOT IN into an anti-join; it may use a hashed SubPlan that
--     must fit in work_mem, otherwise it degrades toward repeated scans.
--   * On 100M rows a single DELETE writes one dead tuple per removed row (WAL volume,
--     bloat, a long transaction that holds back VACUUM, locks held to commit).

-- 3) Large-table alternative: rebuild instead of delete -----------------------------
-- (Run in a maintenance window; validate counts before the swap.)
-- BEGIN;
-- CREATE TABLE raw_orders_dedup (LIKE raw_orders INCLUDING ALL);
-- INSERT INTO raw_orders_dedup
-- SELECT DISTINCT ON (order_id) *
-- FROM   raw_orders
-- ORDER  BY order_id, load_timestamp ASC;      -- earliest load per order_id
-- -- validation: SELECT COUNT(*) , COUNT(DISTINCT order_id) FROM raw_orders_dedup;
-- --             distinct order_ids must equal COUNT(DISTINCT order_id) on raw_orders
-- ALTER TABLE raw_orders RENAME TO raw_orders_old;
-- ALTER TABLE raw_orders_dedup RENAME TO raw_orders;
-- ALTER TABLE raw_orders ADD PRIMARY KEY (order_id);   -- prevents recurrence
-- COMMIT;
-- -- keep raw_orders_old until validated, then DROP it.
-- Operational notes: an index on (order_id, load_timestamp) helps sorting; DISTINCT ON needs
-- a sort/hash of 100M rows (disk spill, tune work_mem for the session); rebuilt indexes,
-- grants, views, FKs and sequences must be recreated/checked; writers must be paused or
-- redirected during the swap. Alternative: delete in batches by order_id range with
-- periodic COMMIT and VACUUM, which is slower but keeps the table online.

-- Task 3.2: de-duplicate raw_orders, keep the EARLIEST load_timestamp per order_id (PostgreSQL)
--
-- ctid is the physical row locator (block, offset). It is the only per-row handle
-- available because the table has no primary key. It is NOT a business key: it changes
-- after UPDATE, VACUUM FULL, CLUSTER, so use it only inside ONE statement/transaction.

-- 1) The single DML statement
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

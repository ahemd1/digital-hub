-- Task 3.1: logical query processing + window functions (PostgreSQL)
--
-- Logical order (conceptual; the planner may physically reorder):
--   FROM -> WHERE -> GROUP BY -> HAVING -> window functions (OVER) -> SELECT list
--   -> DISTINCT -> ORDER BY -> LIMIT
-- Window functions see only rows that survived WHERE / GROUP BY / HAVING.

-- ---------------------------------------------------------------------------
-- ORIGINAL (as given). It does NOT raise an error in PostgreSQL because
-- user_id/page_id/visit_time are all in GROUP BY. It is wrong logically:
--   * grain is (user_id, page_id, visit_time): HAVING COUNT(*) > 1 keeps only
--     identical duplicate events (same user, page AND timestamp);
--   * LAG/LEAD then run over those few surviving rows, so "previous/next page"
--     are neighbours among duplicates, not among the user's real page visits.
-- ---------------------------------------------------------------------------
-- SELECT user_id, page_id, visit_time,
--        LAG(page_id, 1)  OVER (PARTITION BY user_id ORDER BY visit_time) AS previous_page,
--        LEAD(page_id, 1) OVER (PARTITION BY user_id ORDER BY visit_time) AS next_page
-- FROM web_traffic
-- WHERE visit_time >= '2026-07-01'
-- GROUP BY user_id, page_id, visit_time
-- HAVING COUNT(*) > 1;

-- ---------------------------------------------------------------------------
-- CORRECTED, interpretation A (assumption): "interaction" = number of visits
-- by a user to a page (grain: user_id, page_id), within the date filter.
-- Step 1 decides WHICH (user,page) pairs qualify; step 2 keeps every visit event
-- of qualifying pairs; step 3 computes LAG/LEAD over those events.
-- ---------------------------------------------------------------------------
WITH qualifying_pairs AS (
    SELECT user_id, page_id
    FROM   web_traffic
    WHERE  visit_time >= '2026-07-01'
    GROUP  BY user_id, page_id
    HAVING COUNT(*) > 1
)
SELECT w.user_id,
       w.page_id,
       w.visit_time,
       LAG(w.page_id, 1)  OVER (PARTITION BY w.user_id ORDER BY w.visit_time, w.page_id) AS previous_page,
       LEAD(w.page_id, 1) OVER (PARTITION BY w.user_id ORDER BY w.visit_time, w.page_id) AS next_page
FROM   web_traffic w
JOIN   qualifying_pairs q
       ON q.user_id = w.user_id AND q.page_id = w.page_id
WHERE  w.visit_time >= '2026-07-01'          -- repeat filter: the join is on pairs, not dates
ORDER  BY w.user_id, w.visit_time, w.page_id;

-- ---------------------------------------------------------------------------
-- CORRECTED, interpretation B (alternative): "low interaction page" = a page
-- with <= 1 visit across ALL users. Only the CTE grain changes.
-- ---------------------------------------------------------------------------
-- WITH qualifying_pages AS (
--     SELECT page_id FROM web_traffic
--     WHERE visit_time >= '2026-07-01'
--     GROUP BY page_id HAVING COUNT(*) > 1
-- )
-- SELECT w.user_id, w.page_id, w.visit_time,
--        LAG(w.page_id)  OVER (PARTITION BY w.user_id ORDER BY w.visit_time, w.page_id) AS previous_page,
--        LEAD(w.page_id) OVER (PARTITION BY w.user_id ORDER BY w.visit_time, w.page_id) AS next_page
-- FROM web_traffic w JOIN qualifying_pages q USING (page_id)
-- WHERE w.visit_time >= '2026-07-01';

-- Notes
-- * Ties: if one user has two rows with the same visit_time, ORDER BY visit_time alone is
--   non-deterministic. "w.page_id" above only makes the output repeatable; it is NOT the true
--   event order. A real tie-breaker needs an event id / sequence / click order column, which
--   the assessment schema does not provide.
-- * A page that appears only once for a user is removed BEFORE LAG/LEAD, so transitions skip
--   over it (A -> B -> C with B filtered gives A's next_page = C). That is the requested behaviour
--   ("transitions after filtering"), but state it explicitly in the interview.

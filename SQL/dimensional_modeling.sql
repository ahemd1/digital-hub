-- Task 1.2: dimensional modeling sketch (PostgreSQL syntax; the target warehouse is
-- ClickHouse + dbt, so treat this as a logical design / DML outline, not ClickHouse DDL).
-- Items marked ASSUMPTION are design decisions the assessment does not specify.

-- ============================================================================
-- A. Conformed customer dimension + ID mapping
-- ============================================================================
-- Source IDs are NOT assumed globally unique: identity = (source_system, source_customer_id).
CREATE TABLE customer_id_map (
    source_system       text   NOT NULL CHECK (source_system IN ('erp_sqlserver', 'web_postgres')),
    source_customer_id  text   NOT NULL,            -- text: ERP and web IDs may differ in type
    customer_key        bigint NOT NULL,            -- surrogate key of the resolved customer
    match_rule          text   NOT NULL,            -- e.g. 'exact_email' / 'manual' / 'unmatched'
    matched_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_system, source_customer_id)
);

CREATE TABLE dim_customers (            -- one row per resolved (de-duplicated) customer
    customer_key        bigserial PRIMARY KEY,      -- surrogate key used by facts
    erp_customer_id     text,                       -- nullable: customer may exist in one system only
    web_user_id         text,
    full_name           text,
    email_normalized    text,                       -- ASSUMPTION: a candidate matching attribute
    -- SCD3 columns
    loyalty_tier_current  text,
    loyalty_tier_previous text,
    loyalty_tier_changed_at timestamptz
);
-- Address history lives in a separate SCD2 table (section C) so that facts can join on the
-- address version valid at purchase time. ASSUMPTION: this split is a design choice.

-- ============================================================================
-- B. Junk dimension (payment_method x delivery_type x promotion_applied)
-- ============================================================================
CREATE TABLE dim_order_profile (
    order_profile_key  smallint PRIMARY KEY,
    payment_method     text    NOT NULL CHECK (payment_method IN ('Cash','Credit','PayPal')),
    delivery_type      text    NOT NULL CHECK (delivery_type  IN ('Pickup','Standard','Express')),
    promotion_applied  boolean NOT NULL,
    UNIQUE (payment_method, delivery_type, promotion_applied)
);
-- ASSUMPTION: pre-load the full cross product (3 x 3 x 2 = 18 rows). Not every combination
-- necessarily occurs (e.g. Cash + Express may never happen online); alternatively insert only
-- combinations observed in the data and add new ones as they appear (late-arriving combination).
INSERT INTO dim_order_profile
SELECT row_number() OVER (ORDER BY p, d, promo), p, d, promo
FROM (VALUES ('Cash'),('Credit'),('PayPal'))        AS pm(p)
CROSS JOIN (VALUES ('Pickup'),('Standard'),('Express')) AS dt(d)
CROSS JOIN (VALUES (true),(false))                  AS pr(promo);
-- The fact table then carries ONE small key (order_profile_key) instead of three text columns.

-- ============================================================================
-- C. SCD Type 2: customer shipping address
-- ============================================================================
CREATE TABLE dim_customer_address (
    address_key     bigserial PRIMARY KEY,           -- surrogate key (one per version)
    customer_key    bigint      NOT NULL,            -- stable key from dim_customers
    address_line    text,
    city            text,
    region          text,                            -- region used to attribute sales
    country         text,
    effective_from  timestamptz NOT NULL,
    effective_to    timestamptz,                     -- NULL = open-ended (current version)
    is_current      boolean     NOT NULL DEFAULT true
);
-- At most one current row per customer:
CREATE UNIQUE INDEX uq_dim_customer_address_current
    ON dim_customer_address (customer_key) WHERE is_current;

-- Staging table: latest address per customer from the sources, plus the change time.
CREATE TABLE stg_customer_address (
    customer_key bigint PRIMARY KEY,
    address_line text, city text, region text, country text,
    changed_at   timestamptz NOT NULL
);

-- Run both statements in ONE transaction. IS DISTINCT FROM treats NULLs correctly.
BEGIN;
-- 1) expire current versions whose tracked attributes changed
UPDATE dim_customer_address d
SET    effective_to = s.changed_at,
       is_current   = false
FROM   stg_customer_address s
WHERE  d.customer_key = s.customer_key
  AND  d.is_current
  AND (d.address_line, d.city, d.region, d.country)
      IS DISTINCT FROM (s.address_line, s.city, s.region, s.country);

-- 2) insert a new current version for changed customers and for brand-new customers
INSERT INTO dim_customer_address
       (customer_key, address_line, city, region, country, effective_from, effective_to, is_current)
SELECT s.customer_key, s.address_line, s.city, s.region, s.country, s.changed_at, NULL, true
FROM   stg_customer_address s
LEFT   JOIN dim_customer_address d
       ON d.customer_key = s.customer_key AND d.is_current
WHERE  d.customer_key IS NULL;      -- no current row exists (new, or just expired above)
COMMIT;

-- Point-in-time join for the fact table (half-open interval [from, to) ):
--   JOIN dim_customer_address a
--     ON a.customer_key = f.customer_key
--    AND f.order_ts >= a.effective_from
--    AND (f.order_ts < a.effective_to OR a.effective_to IS NULL)
-- ASSUMPTIONS: half-open interval; timestamp (not date) granularity so two changes on the
-- same day stay distinguishable; effective_from of the first row = first time the address was
-- known (not necessarily when the customer moved).

-- dbt alternative (snapshot):
--   {% snapshot dim_customer_address_snapshot %}
--   {{ config(target_schema='snapshots', unique_key='customer_key',
--             strategy='check', check_cols=['address_line','city','region','country']) }}
--   select customer_key, address_line, city, region, country from {{ ref('stg_customer_address') }}
--   {% endsnapshot %}
--   dbt adds dbt_valid_from / dbt_valid_to (NULL = current). Check the installed dbt version's
--   docs for snapshot config syntax and the ClickHouse adapter's snapshot support before relying on it.

-- ============================================================================
-- D. SCD Type 3: loyalty tier (current + previous only)
-- ============================================================================
-- Columns live on the SAME customer row (see dim_customers above). Update: shift current into
-- previous, then write the new value. In PostgreSQL the right-hand sides of an UPDATE see the
-- OLD row values, so this is safe in one statement:
--   UPDATE dim_customers c
--   SET    loyalty_tier_previous   = c.loyalty_tier_current,
--          loyalty_tier_current    = s.loyalty_tier,
--          loyalty_tier_changed_at = now()
--   FROM   stg_loyalty s
--   WHERE  c.customer_key = s.customer_key
--     AND  c.loyalty_tier_current IS DISTINCT FROM s.loyalty_tier;
-- Difference vs SCD2: SCD3 overwrites in place and keeps exactly one step of history (extra
-- columns, no extra rows); SCD2 adds a row per version and keeps unlimited history.

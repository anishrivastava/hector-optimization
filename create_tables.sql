-- ================================================================
-- STEP 1: Run this in Supabase SQL Editor
-- Creates all tables needed for the optimization project
-- ================================================================

-- ── Table 1: practical_capacity  (your practical_capacity_cateogory_final.csv) ──
CREATE TABLE IF NOT EXISTS practical_capacity (
    id                          BIGSERIAL PRIMARY KEY,
    plant_code                  TEXT NOT NULL,
    category_main               TEXT NOT NULL,
    max_production_capacity     NUMERIC,
    production_cost_inr_per_case NUMERIC
);

CREATE INDEX IF NOT EXISTS idx_pc_plant    ON practical_capacity (plant_code);
CREATE INDEX IF NOT EXISTS idx_pc_category ON practical_capacity (category_main);

-- ── Table 2: sku_plant_lookup  (SKU → which plants can make it) ──
CREATE TABLE IF NOT EXISTS sku_plant_lookup (
    id                          BIGSERIAL PRIMARY KEY,
    sku_code                    TEXT NOT NULL,
    category                    TEXT,
    sku_size                    TEXT,
    plant_code                  TEXT NOT NULL,
    max_production_capacity     NUMERIC,
    production_cost_per_case    NUMERIC
);

CREATE INDEX IF NOT EXISTS idx_spl_sku   ON sku_plant_lookup (sku_code);
CREATE INDEX IF NOT EXISTS idx_spl_plant ON sku_plant_lookup (plant_code);

-- ── Table 3: optimization_results  (output of the optimizer) ──
CREATE TABLE IF NOT EXISTS optimization_results (
    id                          BIGSERIAL PRIMARY KEY,
    run_timestamp               TIMESTAMPTZ DEFAULT NOW(),
    plant_code                  TEXT,
    category_main               TEXT,
    sku_code                    TEXT,
    customer_or_warehouse       TEXT,
    route                       TEXT,
    supplied_cases              NUMERIC,
    max_production_capacity     NUMERIC,
    production_cost_per_case    NUMERIC,
    total_production_cost       NUMERIC,
    total_freight_cost          NUMERIC,
    total_cost                  NUMERIC
);

CREATE INDEX IF NOT EXISTS idx_or_sku      ON optimization_results (sku_code);
CREATE INDEX IF NOT EXISTS idx_or_customer ON optimization_results (customer_or_warehouse);
CREATE INDEX IF NOT EXISTS idx_or_plant    ON optimization_results (plant_code);

-- ── Row Level Security (allow reads) ──
ALTER TABLE practical_capacity    ENABLE ROW LEVEL SECURITY;
ALTER TABLE sku_plant_lookup      ENABLE ROW LEVEL SECURITY;
ALTER TABLE optimization_results  ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow read" ON practical_capacity    FOR SELECT USING (true);
CREATE POLICY "Allow read" ON sku_plant_lookup      FOR SELECT USING (true);
CREATE POLICY "Allow read" ON optimization_results  FOR SELECT USING (true);

-- ── Verify ──
-- SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';
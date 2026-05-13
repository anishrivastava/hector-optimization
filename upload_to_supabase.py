"""
STEP 2 — Upload input files to Supabase
========================================
Run this ONCE (and re-run whenever your Excel or CSV changes).

What it uploads:
  1. practical_capacity_cateogory_final.csv  → table: practical_capacity
  2. SKU→Plant mapping (built from Excel)    → table: sku_plant_lookup

Usage:
    pip install supabase pandas openpyxl
    python STEP2_upload_to_supabase.py
"""

import os
import pandas as pd
from supabase import create_client

# ── CONFIG — edit these paths ────────────────────────────────
EXCEL_FILE    = r"C:\Users\shash\Desktop\hector_optimization\FSD Data (6).xlsx"
CAPACITY_CSV  = r"C:\Users\shash\Desktop\hector_optimization\practical_capacity_cateogory_final.csv"

SUPABASE_URL  = os.environ.get("SUPABASE_URL", "")          # https://xxxx.supabase.co
SUPABASE_KEY  = os.environ.get("SUPABASE_SERVICE_KEY", "")  # service role key
# ─────────────────────────────────────────────────────────────


def upload_table(client, table_name: str, df: pd.DataFrame, batch_size=500):
    """Clear and re-upload a table."""
    print(f"\nUploading → '{table_name}' ({len(df)} rows) …")

    # Clear old data
    client.table(table_name).delete().neq("id", 0).execute()
    print("  Old data cleared.")

    records = df.to_dict(orient="records")
    for start in range(0, len(records), batch_size):
        batch = records[start: start + batch_size]
        client.table(table_name).insert(batch).execute()
        print(f"  ✓ {min(start + batch_size, len(records))}/{len(records)} rows")

    print(f"  ✅ Done — '{table_name}'")


def build_sku_plant_lookup(excel_path: str) -> pd.DataFrame:
    """
    Build SKU → Plant mapping from Excel.
    Joins Product-SKU + practical_capacity CSV logic using Excel sheets.
    """
    pc_cap  = pd.read_excel(excel_path, sheet_name="ProductionCapacity")
    pc_cost = pd.read_excel(excel_path, sheet_name="ProductionCost")
    sku_df  = pd.read_excel(excel_path, sheet_name="Product-SKU")

    # Capacity per plant × category
    plant_cat_cap = (
        pc_cap
        .groupby(["PLANT CODE", "CATEGORY MAIN"], as_index=False)["NO OF CASES/DAY"]
        .sum()
        .rename(columns={"NO OF CASES/DAY": "max_production_capacity"})
    )

    # Cost per plant × category
    plant_cat_cost = (
        pc_cost[["PLANT CODE", "CATEGORY MAIN", "PRODUCTION COST (INR/CASE)"]]
        .drop_duplicates(["PLANT CODE", "CATEGORY MAIN"])
    )

    plant_cat = plant_cat_cap.merge(plant_cat_cost, on=["PLANT CODE", "CATEGORY MAIN"], how="left")

    # Join with SKU → Category
    sku_plant = (
        sku_df[["SKU CODE_masked", "CATEGORY MAIN_masked", "SKU SIZE_masked"]]
        .merge(
            plant_cat,
            left_on="CATEGORY MAIN_masked",
            right_on="CATEGORY MAIN",
            how="inner"
        )
        .drop(columns=["CATEGORY MAIN"])
        .rename(columns={
            "SKU CODE_masked"            : "sku_code",
            "SKU SIZE_masked"            : "sku_size",
            "CATEGORY MAIN_masked"       : "category",
            "PLANT CODE"                 : "plant_code",
            "PRODUCTION COST (INR/CASE)" : "production_cost_per_case",
        })
    )

    sku_plant["max_production_capacity"]  = sku_plant["max_production_capacity"].round(4)
    sku_plant["production_cost_per_case"] = sku_plant["production_cost_per_case"].round(4)
    return sku_plant


# ── MAIN ─────────────────────────────────────────────────────
if __name__ == "__main__":

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError(
            "Please set SUPABASE_URL and SUPABASE_SERVICE_KEY as environment variables.\n"
            "Windows:  set SUPABASE_URL=https://xxxx.supabase.co\n"
            "          set SUPABASE_SERVICE_KEY=eyJ..."
        )

    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # ── 1. Upload practical_capacity CSV ──────────────────────
    df_cap = pd.read_csv(CAPACITY_CSV).rename(columns={
        "PLANT CODE"                 : "plant_code",
        "CATEGORY MAIN"              : "category_main",
        "MAX_PRODUCTION_CAPACITY"    : "max_production_capacity",
        "PRODUCTION COST (INR/CASE)" : "production_cost_inr_per_case",
    })
    upload_table(client, "practical_capacity", df_cap)

    # ── 2. Upload SKU → Plant lookup ──────────────────────────
    print("\nBuilding SKU → Plant lookup from Excel …")
    df_sku_plant = build_sku_plant_lookup(EXCEL_FILE)
    print(f"  {len(df_sku_plant)} rows | "
          f"{df_sku_plant['sku_code'].nunique()} SKUs | "
          f"{df_sku_plant['plant_code'].nunique()} plants")
    upload_table(client, "sku_plant_lookup", df_sku_plant)

    print("\n✅ All uploads complete!")
    print("   You can now run STEP3_optimizer.py")
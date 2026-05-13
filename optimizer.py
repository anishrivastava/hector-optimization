"""
STEP 3 — Run the Optimizer
===========================
Reads input data from your files, runs the PuLP optimizer,
saves results to Supabase (optimization_results table)
AND saves a local CSV output.

Usage:
    pip install pulp pandas openpyxl supabase
    python STEP3_optimizer.py
"""

import os
import pandas as pd
import numpy as np
import pulp
from supabase import create_client

# ── CONFIG — edit these paths ────────────────────────────────
EXCEL_FILE   = r"C:\Users\shash\Desktop\hector_optimization\FSD Data (6).xlsx"
CAPACITY_CSV = r"C:\Users\shash\Desktop\hector_optimization\practical_capacity_cateogory_final.csv"
OUTPUT_CSV   = r"C:\Users\shash\Desktop\hector_optimization\FSD_demand_PRODUCTION_output.csv"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
# ─────────────────────────────────────────────────────────────


# ============================================================
# SECTION A — LOAD DATA
# ============================================================

print("Loading data …")

links_df    = pd.read_excel(EXCEL_FILE, sheet_name="PrimaryLinks & DirectLinks OLD")
sales_df    = pd.read_excel(EXCEL_FILE, sheet_name="Sales Hierarchy")
distance_df = pd.read_excel(EXCEL_FILE, sheet_name="Distance")
df_demand   = pd.read_excel(EXCEL_FILE, sheet_name="Demand")
sku_df      = pd.read_excel(EXCEL_FILE, sheet_name="Product-SKU")

df_demand.columns = df_demand.columns.astype(str)
df_demand = df_demand.loc[:, ~df_demand.columns.str.contains("^Unnamed")]

# This is your second input file
model_input_df2 = pd.read_csv(CAPACITY_CSV)

print("   All files loaded")


# ============================================================
# SECTION B — FREIGHT TABLES
# ============================================================

# ── DF1: Plant → Warehouse freight ───────────────────────────
plant_warehouse_links = links_df[
    links_df["DESTINATION LOCATION TYPE"].str.upper() == "WAREHOUSE"
].copy()

plant_warehouse_freight_avg = (
    plant_warehouse_links
    .groupby(["SOURCE LOCATION CODE", "DESTINATION LOCATION CODE"], as_index=False)
    ["FINAL FREIGHT"].mean()
    .rename(columns={
        "SOURCE LOCATION CODE"      : "PLANT CODE",
        "DESTINATION LOCATION CODE" : "WAREHOUSE CODE",
        "FINAL FREIGHT"             : "AVG_FREIGHT_COST",
    })
)
df1 = plant_warehouse_freight_avg.rename(columns={"AVG_FREIGHT_COST": "PLANT_WH_COST"})

# ── DF2: Warehouse → Customer freight (Haversine) ────────────
warehouse_customers_df = sales_df[
    sales_df["CUSTOMER SHIPMENT ROUTE"].str.upper().str.contains("THROUGH WAREHOUSE")
].copy()

warehouse_lat_long = (
    distance_df[distance_df["LOCATION TYPE 2"].str.upper() == "WAREHOUSE"]
    [["DESTINATION CODE 2", "LATITUDE 2", "LONGITUDE 2"]]
    .drop_duplicates()
    .rename(columns={
        "DESTINATION CODE 2": "WAREHOUSE CODE",
        "LATITUDE 2"        : "WAREHOUSE_LAT",
        "LONGITUDE 2"       : "WAREHOUSE_LONG",
    })
)

warehouse_customer_list = warehouse_customers_df["CUSTOMER CODE_masked"].unique()

customer_lat_long = (
    distance_df[
        (distance_df["LOCATION TYPE 2"].str.upper() == "CUSTOMER") &
        (distance_df["DESTINATION CODE 2"].isin(warehouse_customer_list))
    ]
    [["DESTINATION CODE 2", "LATITUDE 2", "LONGITUDE 2"]]
    .drop_duplicates()
    .rename(columns={
        "DESTINATION CODE 2": "CUSTOMER CODE",
        "LATITUDE 2"        : "CUSTOMER_LAT",
        "LONGITUDE 2"       : "CUSTOMER_LONG",
    })
)

warehouse_lat_long["key"] = 1
customer_lat_long["key"]  = 1
warehouse_customer_map = warehouse_lat_long.merge(customer_lat_long, on="key").drop(columns=["key"])


def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return R * 2 * np.arcsin(np.sqrt(a))


warehouse_customer_map["DISTANCE_KM"] = haversine_distance(
    warehouse_customer_map["WAREHOUSE_LAT"], warehouse_customer_map["WAREHOUSE_LONG"],
    warehouse_customer_map["CUSTOMER_LAT"],  warehouse_customer_map["CUSTOMER_LONG"],
)

bucket_rate_df = pd.DataFrame({
    "MIN_KM" : [0, 101, 201, 301, 401, 501, 601, 701, 801, 901, 1001, 1501],
    "MAX_KM" : [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1200, 1e9],
    "RATE_9MT"  : [14.23, 11.20, 7.36, 6.65, 6.09, 4.63, 3.59, 3.87, 3.64, 3.81, 2.73, 3.13],
    "RATE_16MT" : [10.94,  9.57, 6.43, 5.06, 4.37, 3.99, 4.67, 3.19, 3.45, 3.02, 5.22, 2.37],
})
bucket_rate_df["AVG_RATE_PER_KM"] = (bucket_rate_df["RATE_9MT"] + bucket_rate_df["RATE_16MT"]) / 2


def get_bucket_rate(distance):
    if pd.isna(distance):
        return 0
    row = bucket_rate_df[
        (distance >= bucket_rate_df["MIN_KM"]) & (distance < bucket_rate_df["MAX_KM"])
    ]
    return row["AVG_RATE_PER_KM"].iloc[0] if len(row) else bucket_rate_df["AVG_RATE_PER_KM"].iloc[-1]


warehouse_customer_map["RATE_PER_KM"]  = warehouse_customer_map["DISTANCE_KM"].apply(get_bucket_rate)
warehouse_customer_map["FREIGHT_COST"] = warehouse_customer_map["DISTANCE_KM"] * warehouse_customer_map["RATE_PER_KM"]

df2 = warehouse_customer_map[["WAREHOUSE CODE", "CUSTOMER CODE", "FREIGHT_COST"]].copy()
df2 = df2.rename(columns={"FREIGHT_COST": "WH_CUST_COST"})

# ── DF3: Plant → Customer direct freight ─────────────────────
direct_customers = sales_df[
    sales_df["CUSTOMER SHIPMENT ROUTE"].str.upper().str.contains("DIRECT TO CUSTOMER")
].copy()
direct_customer_list = direct_customers["CUSTOMER CODE_masked"].unique()

plant_customer_links_direct = links_df[
    (links_df["SOURCE LOCATION TYPE"].str.upper() == "PLANT") &
    (links_df["DESTINATION LOCATION TYPE"].str.upper() == "CUSTOMER") &
    (links_df["DESTINATION LOCATION CODE"].isin(direct_customer_list))
].copy()

plant_customer_freight_avg = (
    plant_customer_links_direct
    .groupby(["SOURCE LOCATION CODE", "DESTINATION LOCATION CODE"], as_index=False)
    ["FINAL FREIGHT"].mean()
)

df3_direct_dispatch = plant_customer_freight_avg.rename(columns={
    "SOURCE LOCATION CODE"      : "PLANT CODE",
    "DESTINATION LOCATION CODE" : "CUSTOMER CODE",
    "FINAL FREIGHT"             : "FREIGHT COST",
})
df3_direct_dispatch["WAREHOUSE CODE"] = "W"

# ── DF5: Combined routing table ──────────────────────────────
df5_wh = df1.merge(df2, on="WAREHOUSE CODE", how="inner")
df5_wh["ROUTE"] = df5_wh["WAREHOUSE CODE"]
df5_wh = df5_wh.rename(columns={"CUSTOMER CODE": "WAREHOUSE_CUSTOMER"})
df5_wh["PLANT_DIRECT_COST"] = 0
df5_wh["TOTAL_FREIGHT_COST"] = df5_wh["PLANT_WH_COST"] + df5_wh["WH_CUST_COST"]
df5_wh = df5_wh[["PLANT CODE", "WAREHOUSE_CUSTOMER", "ROUTE",
                  "PLANT_WH_COST", "WH_CUST_COST", "PLANT_DIRECT_COST", "TOTAL_FREIGHT_COST"]]

df5_direct = df3_direct_dispatch.rename(columns={"FREIGHT COST": "PLANT_DIRECT_COST"})
df5_direct["ROUTE"] = "DIRECT"
df5_direct["PLANT_WH_COST"] = 0
df5_direct["TOTAL_FREIGHT_COST"] = df5_direct["PLANT_DIRECT_COST"]
df5_direct = df5_direct.rename(columns={"CUSTOMER CODE": "WAREHOUSE_CUSTOMER"})
df5_direct = df5_direct[["PLANT CODE", "WAREHOUSE_CUSTOMER", "ROUTE",
                          "PLANT_WH_COST", "PLANT_DIRECT_COST", "TOTAL_FREIGHT_COST"]]

df5_plant_wh_customer_cost = pd.concat([df5_wh, df5_direct], axis=0, ignore_index=True)

print("   Freight tables built")


# ============================================================
# SECTION C — MASTER TABLE: CUSTOMERS
# ============================================================

df_demand_customer = df_demand[
    (df_demand["CUSTOMER / WAREHOUSE"] == "CUSTOMER") &
    (df_demand["DEMAND (IN CASES)"] > 0)
].copy()

df_demand_enriched = df_demand_customer.merge(
    sku_df[["SKU CODE_masked", "CATEGORY MAIN_masked", "SKU SIZE_masked"]],
    on="SKU CODE_masked", how="left"
)

df_dp = df_demand_enriched.merge(
    model_input_df2[["PLANT CODE", "CATEGORY MAIN",
                     "MAX_PRODUCTION_CAPACITY", "PRODUCTION COST (INR/CASE)"]],
    left_on=["CATEGORY MAIN_masked"], right_on=["CATEGORY MAIN"], how="inner"
)

df_master = df_dp.merge(
    df5_plant_wh_customer_cost,
    left_on=["PLANT CODE", "CUSTOMER / WAREHOUSE CODE_masked"],
    right_on=["PLANT CODE", "WAREHOUSE_CUSTOMER"],
    how="inner"
)

df_master["PRODUCTION COST (INR/CASE)"] = pd.to_numeric(
    df_master["PRODUCTION COST (INR/CASE)"], errors="coerce"
)
max_cost = df_master["PRODUCTION COST (INR/CASE)"].max()
df_master["PRODUCTION COST (INR/CASE)"] = df_master["PRODUCTION COST (INR/CASE)"].fillna(max_cost * 5)
df_master["TOTAL_COST_PER_CASE"] = (
    df_master["PRODUCTION COST (INR/CASE)"] + df_master["TOTAL_FREIGHT_COST"]
)
df_master = df_master.drop_duplicates(
    ["PLANT CODE", "CATEGORY MAIN", "SKU CODE_masked", "WAREHOUSE_CUSTOMER", "ROUTE"]
).reset_index(drop=True)

df_master.loc[df_master["ROUTE"] == "DIRECT", "WH_CUST_COST"] = 0
df_master = df_master[
    df_master["MAX_PRODUCTION_CAPACITY"].notna() &
    (df_master["MAX_PRODUCTION_CAPACITY"] > 0)
].reset_index(drop=True)

# Route validation
direct_customers_list    = sales_df[sales_df["CUSTOMER SHIPMENT ROUTE"].str.contains("DIRECT",    case=False)]["CUSTOMER CODE_masked"]
warehouse_customers_list = sales_df[sales_df["CUSTOMER SHIPMENT ROUTE"].str.contains("WAREHOUSE", case=False)]["CUSTOMER CODE_masked"]

df_master = df_master[
    ~(
        (df_master["WAREHOUSE_CUSTOMER"].isin(direct_customers_list)    & (df_master["ROUTE"] != "DIRECT")) |
        (df_master["WAREHOUSE_CUSTOMER"].isin(warehouse_customers_list) & (df_master["ROUTE"] == "DIRECT"))
    )
].reset_index(drop=True)

df_master["DEMAND_KEY"] = (
    df_master["TIME ID"].astype(str) + "|" +
    df_master["CHANNEL CODE_masked"] + "|" +
    df_master["CUSTOMER / WAREHOUSE CODE_masked"] + "|" +
    df_master["SKU CODE_masked"]
)

print("   Customer master table built")


# ============================================================
# SECTION D — MASTER TABLE: WAREHOUSES
# ============================================================

df_wh_raw = df_demand[
    (df_demand["CUSTOMER / WAREHOUSE"] == "WAREHOUSE") &
    (df_demand["DEMAND (IN CASES)"] > 0)
].copy()

df_wh_clean = (
    df_wh_raw
    .groupby(["TIME ID", "CHANNEL CODE_masked",
              "CUSTOMER / WAREHOUSE CODE_masked", "SKU CODE_masked"], as_index=False)
    .agg({"DEMAND (IN CASES)": "sum"})
)

df_wh_sku = df_wh_clean.merge(
    sku_df[["SKU CODE_masked", "CATEGORY MAIN_masked", "SKU SIZE_masked"]],
    on="SKU CODE_masked", how="left"
)

df_wh_prod = df_wh_sku.merge(
    model_input_df2[["PLANT CODE", "CATEGORY MAIN",
                     "MAX_PRODUCTION_CAPACITY", "PRODUCTION COST (INR/CASE)"]],
    left_on=["CATEGORY MAIN_masked"], right_on=["CATEGORY MAIN"], how="inner"
)

df_wh_routes = df1.rename(columns={"WAREHOUSE CODE": "WAREHOUSE_CUSTOMER"})[
    ["PLANT CODE", "WAREHOUSE_CUSTOMER", "PLANT_WH_COST"]
]

df_wh_routed = df_wh_prod.merge(
    df_wh_routes,
    left_on=["PLANT CODE", "CUSTOMER / WAREHOUSE CODE_masked"],
    right_on=["PLANT CODE", "WAREHOUSE_CUSTOMER"],
    how="inner"
)

df_wh_master = df_wh_routed.copy()
df_wh_master["ROUTE"] = "DIRECT"
df_wh_master["WH_CUST_COST"] = 0
df_wh_master["PLANT_DIRECT_COST"] = df_wh_master["PLANT_WH_COST"]
df_wh_master["TOTAL_FREIGHT_COST"] = df_wh_master["PLANT_DIRECT_COST"]

df_wh_master["PRODUCTION COST (INR/CASE)"] = pd.to_numeric(
    df_wh_master["PRODUCTION COST (INR/CASE)"], errors="coerce"
)
max_cost = df_wh_master["PRODUCTION COST (INR/CASE)"].max()
df_wh_master["PRODUCTION COST (INR/CASE)"] = df_wh_master["PRODUCTION COST (INR/CASE)"].fillna(max_cost * 5)
df_wh_master["TOTAL_COST_PER_CASE"] = (
    df_wh_master["PRODUCTION COST (INR/CASE)"] + df_wh_master["TOTAL_FREIGHT_COST"]
)

df_wh_master["DEMAND_KEY"] = (
    df_wh_master["TIME ID"].astype(str) + "|" +
    df_wh_master["CHANNEL CODE_masked"] + "|" +
    df_wh_master["CUSTOMER / WAREHOUSE CODE_masked"] + "|" +
    df_wh_master["SKU CODE_masked"]
)

print("   Warehouse master table built")


# ============================================================
# SECTION E — COMBINE & FINAL CHECKS
# ============================================================

cols_to_drop = ["CITY_masked", "CUSTOMER / WAREHOUSE"]
df_master_opt = df_master.drop(columns=cols_to_drop, errors="ignore")
df_wh_opt     = df_wh_master.drop(columns=cols_to_drop, errors="ignore")

common_cols   = [c for c in df_master_opt.columns if c in df_wh_opt.columns]
df_master_opt = df_master_opt[common_cols]
df_wh_opt     = df_wh_opt[common_cols]

df_master_final = pd.concat([df_master_opt, df_wh_opt], ignore_index=True)

assert df_master_final.isna().sum().sum() == 0, "❌ NULL values found in final df"

final_demand = df_master_final.drop_duplicates("DEMAND_KEY")["DEMAND (IN CASES)"].sum()
print(f"  Total demand entering optimizer: {final_demand:,.0f} cases")


# ============================================================
# SECTION F — OPTIMIZER (PuLP)
# ============================================================

print("\nRunning optimizer …")

model = pulp.LpProblem("Production_Dispatch_MinCost", pulp.LpMinimize)

x     = pulp.LpVariable.dicts("Supply", df_master_final.index, lowBound=0)
unmet = pulp.LpVariable.dicts("Unmet",  df_master_final["DEMAND_KEY"].unique(), lowBound=0)

BIG_PENALTY = 1e8

for dk, grp in df_master_final.groupby("DEMAND_KEY"):
    model += (
        pulp.lpSum(x[i] for i in grp.index) + unmet[dk]
        == grp["DEMAND (IN CASES)"].iloc[0]
    ), f"Demand_{dk}"

for (plant, category), grp in df_master_final.groupby(["PLANT CODE", "CATEGORY MAIN"]):
    model += (
        pulp.lpSum(x[i] for i in grp.index) <= grp["MAX_PRODUCTION_CAPACITY"].iloc[0]
    ), f"Capacity_{plant}_{category}"

model += (
    pulp.lpSum(x[i] * df_master_final.loc[i, "TOTAL_COST_PER_CASE"] for i in df_master_final.index)
    + pulp.lpSum(unmet[dk] * BIG_PENALTY for dk in unmet)
)

solver = pulp.PULP_CBC_CMD(msg=1)
model.solve(solver)

print(f"  Status     : {pulp.LpStatus[model.status]}")
print(f"  Total Cost : {pulp.value(model.objective):,.2f}")


# ============================================================
# SECTION G — EXTRACT SOLUTION
# ============================================================

df_solution = df_master_final.copy()
df_solution["SUPPLIED_CASES"] = [
    x[i].varValue if x[i].varValue is not None else 0
    for i in df_solution.index
]
df_solution = df_solution[df_solution["SUPPLIED_CASES"] > 0].reset_index(drop=True)
df_solution["TOTAL_PRODUCTION_COST"] = (
    df_solution["SUPPLIED_CASES"] * df_solution["PRODUCTION COST (INR/CASE)"]
)
df_solution["TOTAL_COST"] = df_solution["TOTAL_PRODUCTION_COST"] + df_solution["TOTAL_FREIGHT_COST"]

final_output = df_solution[[
    "PLANT CODE", "CATEGORY MAIN", "SKU CODE_masked", "WAREHOUSE_CUSTOMER",
    "ROUTE", "SUPPLIED_CASES", "MAX_PRODUCTION_CAPACITY",
    "PRODUCTION COST (INR/CASE)", "TOTAL_PRODUCTION_COST",
    "TOTAL_FREIGHT_COST", "TOTAL_COST",
]].rename(columns={"SKU CODE_masked": "SKU CODE"})

# Save local CSV
final_output.to_csv(OUTPUT_CSV, index=False)
print(f"\n   Output CSV saved: {OUTPUT_CSV}")

# Fulfilment summary
total_demand   = df_master_final.drop_duplicates("DEMAND_KEY")["DEMAND (IN CASES)"].sum()
total_supplied = sum(x[i].value() for i in x)
total_unmet    = sum(unmet[dk].value() for dk in unmet)
print(f"  Total Demand   : {total_demand:,.0f}")
print(f"  Total Supplied : {total_supplied:,.0f}")
print(f"  Total Unmet    : {total_unmet:,.0f}")
print(f"  Fulfilment %   : {100 * total_supplied / total_demand:.1f}%")


# ============================================================
# SECTION H — SAVE RESULTS TO SUPABASE
# ============================================================

if SUPABASE_URL and SUPABASE_KEY:
    print("\nSaving results to Supabase …")
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Clear old results
    client.table("optimization_results").delete().neq("id", 0).execute()

    records = final_output.rename(columns={
        "PLANT CODE"                   : "plant_code",
        "CATEGORY MAIN"                : "category_main",
        "SKU CODE"                     : "sku_code",
        "WAREHOUSE_CUSTOMER"           : "customer_or_warehouse",
        "ROUTE"                        : "route",
        "SUPPLIED_CASES"               : "supplied_cases",
        "MAX_PRODUCTION_CAPACITY"      : "max_production_capacity",
        "PRODUCTION COST (INR/CASE)"   : "production_cost_per_case",
        "TOTAL_PRODUCTION_COST"        : "total_production_cost",
        "TOTAL_FREIGHT_COST"           : "total_freight_cost",
        "TOTAL_COST"                   : "total_cost",
    }).to_dict(orient="records")

    batch_size = 500
    for start in range(0, len(records), batch_size):
        batch = records[start: start + batch_size]
        client.table("optimization_results").insert(batch).execute()
        print(f"   {min(start + batch_size, len(records))}/{len(records)} rows")

    print("   Results saved to Supabase → 'optimization_results' table")
else:
    print("\n    Supabase not configured — results saved to CSV only.")
    print("      Set SUPABASE_URL and SUPABASE_SERVICE_KEY to enable Supabase upload.")
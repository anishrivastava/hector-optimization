import os
from collections import defaultdict
from fastmcp import FastMCP
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

mcp = FastMCP("hector-optimizer")
_client: Client | None = None


def db() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def to_table(rows: list[dict]) -> str:
    if not rows:
        return "No results found."
    headers = list(rows[0].keys())
    widths = {h: max(len(h), max(len(str(r.get(h, ""))) for r in rows)) for h in headers}
    sep  = "  ".join("-" * widths[h] for h in headers)
    head = "  ".join(h.ljust(widths[h]) for h in headers)
    body = "\n".join("  ".join(str(r.get(h, "")).ljust(widths[h]) for h in headers) for r in rows)
    return f"{head}\n{sep}\n{body}"


@mcp.tool()
def which_plant_for_customer_sku(customer_code: str, sku_code: str) -> str:
    """Find which plant was assigned to fulfill a specific SKU for a specific customer or warehouse after running the optimizer."""
    resp = (
        db().table("optimization_results")
        .select("plant_code, sku_code, customer_or_warehouse, route, supplied_cases, total_freight_cost, total_cost")
        .ilike("customer_or_warehouse", f"%{customer_code}%")
        .ilike("sku_code", f"%{sku_code}%")
        .order("total_cost")
        .execute()
    )
    rows = resp.data
    if not rows:
        return f"No assignment found for customer '{customer_code}' + SKU '{sku_code}'."
    return f"Plant assignment — Customer: '{customer_code}' | SKU: '{sku_code}'\nFound {len(rows)} assignment(s):\n\n" + to_table(rows)


@mcp.tool()
def search_plants_for_sku(sku_code: str) -> str:
    """Find which plants CAN manufacture a given SKU. Returns plant codes, capacity, and production cost."""
    resp = (
        db().table("sku_plant_lookup")
        .select("sku_code, category, plant_code, max_production_capacity, production_cost_per_case")
        .ilike("sku_code", f"%{sku_code}%")
        .order("production_cost_per_case")
        .execute()
    )
    rows = resp.data
    if not rows:
        return f"No plants found that can manufacture SKU matching '{sku_code}'."
    n = len({r["plant_code"] for r in rows})
    return f"Plants that can manufacture SKU '{sku_code}' ({n} plant(s)):\n\n" + to_table(rows)


@mcp.tool()
def search_skus_for_plant(plant_code: str) -> str:
    """Find all SKUs that a given plant can manufacture."""
    resp = (
        db().table("sku_plant_lookup")
        .select("plant_code, sku_code, category, max_production_capacity, production_cost_per_case")
        .ilike("plant_code", f"%{plant_code}%")
        .order("sku_code")
        .execute()
    )
    rows = resp.data
    if not rows:
        return f"No SKUs found for plant matching '{plant_code}'."
    n = len({r["sku_code"] for r in rows})
    return f"SKUs manufactured by plant '{plant_code}' ({n} unique SKUs):\n\n" + to_table(rows)


@mcp.tool()
def list_all_plants() -> str:
    """List all plants and their total production capacity."""
    resp = (
        db().table("practical_capacity")
        .select("plant_code, category_main, max_production_capacity")
        .execute()
    )
    rows = resp.data
    plant_cap: dict[str, float] = defaultdict(float)
    for r in rows:
        plant_cap[r["plant_code"]] += r.get("max_production_capacity") or 0
    summary = [{"plant_code": p, "total_capacity_cases_per_month": round(c, 0)} for p, c in sorted(plant_cap.items())]
    return f"All plants ({len(summary)} total):\n\n" + to_table(summary)


@mcp.tool()
def get_plant_assignments(plant_code: str) -> str:
    """Show all customers/warehouses assigned to a specific plant in the optimizer results."""
    resp = (
        db().table("optimization_results")
        .select("plant_code, sku_code, customer_or_warehouse, route, supplied_cases, total_cost")
        .ilike("plant_code", f"%{plant_code}%")
        .order("customer_or_warehouse")
        .execute()
    )
    rows = resp.data
    if not rows:
        return f"No assignments found for plant '{plant_code}'. Run the optimizer first."
    total_cases = sum(r.get("supplied_cases") or 0 for r in rows)
    return f"Supply assignments for plant '{plant_code}'\nTotal: {len(rows)} rows | {total_cases:,.0f} cases\n\n" + to_table(rows)


@mcp.tool()
def get_customer_supply_plan(customer_code: str) -> str:
    """Show the full supply plan for a customer or warehouse: which plant supplies which SKU, how many cases, at what cost."""
    resp = (
        db().table("optimization_results")
        .select("customer_or_warehouse, sku_code, plant_code, route, supplied_cases, production_cost_per_case, total_freight_cost, total_cost")
        .ilike("customer_or_warehouse", f"%{customer_code}%")
        .order("sku_code")
        .execute()
    )
    rows = resp.data
    if not rows:
        return f"No supply plan found for customer '{customer_code}'. Run the optimizer first."
    total_cases = sum(r.get("supplied_cases") or 0 for r in rows)
    total_cost  = sum(r.get("total_cost") or 0 for r in rows)
    return f"Supply plan for customer '{customer_code}'\nTotal: {len(rows)} SKU line(s) | {total_cases:,.0f} cases | Cost: {total_cost:,.2f}\n\n" + to_table(rows)
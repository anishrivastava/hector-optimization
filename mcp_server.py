import os
import asyncio
import mcp.types as types
from mcp.server import Server
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

mcp = Server("hector-optimizer")
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
    widths  = {h: max(len(h), max(len(str(r.get(h, ""))) for r in rows)) for h in headers}
    sep  = "  ".join("-" * widths[h] for h in headers)
    head = "  ".join(h.ljust(widths[h]) for h in headers)
    body = "\n".join(
        "  ".join(str(r.get(h, "")).ljust(widths[h]) for h in headers)
        for r in rows
    )
    return f"{head}\n{sep}\n{body}"


@mcp.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="which_plant_for_customer_sku",
            description=(
                "After running the optimizer: find which plant was assigned "
                "to fulfill a specific SKU for a specific customer or warehouse. "
                "Also shows supplied cases, freight cost, and total cost."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "customer_code": {"type": "string", "description": "Customer or warehouse code (partial match ok)."},
                    "sku_code": {"type": "string", "description": "SKU code (partial match ok)."}
                },
                "required": ["customer_code", "sku_code"]
            }
        ),
        types.Tool(
            name="search_plants_for_sku",
            description="Find which plants CAN manufacture a given SKU. Returns plant codes, capacity, and production cost.",
            inputSchema={
                "type": "object",
                "properties": {
                    "sku_code": {"type": "string", "description": "SKU code (partial match ok)."}
                },
                "required": ["sku_code"]
            }
        ),
        types.Tool(
            name="search_skus_for_plant",
            description="Find all SKUs that a given plant can manufacture.",
            inputSchema={
                "type": "object",
                "properties": {
                    "plant_code": {"type": "string", "description": "Plant code (partial match ok)."}
                },
                "required": ["plant_code"]
            }
        ),
        types.Tool(
            name="list_all_plants",
            description="List all plants and their total production capacity.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="get_plant_assignments",
            description="Show all customers/warehouses assigned to a specific plant in the optimizer results.",
            inputSchema={
                "type": "object",
                "properties": {
                    "plant_code": {"type": "string", "description": "Plant code (partial match ok)."}
                },
                "required": ["plant_code"]
            }
        ),
        types.Tool(
            name="get_customer_supply_plan",
            description="Show the full supply plan for a customer or warehouse: which plant supplies which SKU, how many cases, at what cost.",
            inputSchema={
                "type": "object",
                "properties": {
                    "customer_code": {"type": "string", "description": "Customer or warehouse code (partial match ok)."}
                },
                "required": ["customer_code"]
            }
        ),
    ]


@mcp.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        text = await _handle(name, arguments)
    except Exception as e:
        text = f"Error in '{name}': {type(e).__name__}: {e}"
    return [types.TextContent(type="text", text=text)]


async def _handle(name: str, args: dict) -> str:

    if name == "which_plant_for_customer_sku":
        customer = args["customer_code"]
        sku      = args["sku_code"]
        resp = (
            db().table("optimization_results")
            .select("plant_code, sku_code, customer_or_warehouse, route, supplied_cases, total_freight_cost, total_cost")
            .ilike("customer_or_warehouse", f"%{customer}%")
            .ilike("sku_code", f"%{sku}%")
            .order("total_cost")
            .execute()
        )
        rows = resp.data
        if not rows:
            return f"No assignment found for customer '{customer}' + SKU '{sku}'."
        return f"Plant assignment — Customer: '{customer}' | SKU: '{sku}'\nFound {len(rows)} assignment(s):\n\n" + to_table(rows)

    elif name == "search_plants_for_sku":
        sku  = args["sku_code"]
        resp = (
            db().table("sku_plant_lookup")
            .select("sku_code, category, plant_code, max_production_capacity, production_cost_per_case")
            .ilike("sku_code", f"%{sku}%")
            .order("production_cost_per_case")
            .execute()
        )
        rows = resp.data
        if not rows:
            return f"No plants found that can manufacture SKU matching '{sku}'."
        n = len({r["plant_code"] for r in rows})
        return f"Plants that can manufacture SKU '{sku}' ({n} plant(s)):\n\n" + to_table(rows)

    elif name == "search_skus_for_plant":
        plant = args["plant_code"]
        resp  = (
            db().table("sku_plant_lookup")
            .select("plant_code, sku_code, category, max_production_capacity, production_cost_per_case")
            .ilike("plant_code", f"%{plant}%")
            .order("sku_code")
            .execute()
        )
        rows = resp.data
        if not rows:
            return f"No SKUs found for plant matching '{plant}'."
        n = len({r["sku_code"] for r in rows})
        return f"SKUs manufactured by plant '{plant}' ({n} unique SKUs):\n\n" + to_table(rows)

    elif name == "list_all_plants":
        resp = (
            db().table("practical_capacity")
            .select("plant_code, category_main, max_production_capacity")
            .execute()
        )
        rows = resp.data
        from collections import defaultdict
        plant_cap: dict[str, float] = defaultdict(float)
        for r in rows:
            plant_cap[r["plant_code"]] += r.get("max_production_capacity") or 0
        summary = [{"plant_code": p, "total_capacity_cases_per_month": round(c, 0)} for p, c in sorted(plant_cap.items())]
        return f"All plants ({len(summary)} total):\n\n" + to_table(summary)

    elif name == "get_plant_assignments":
        plant = args["plant_code"]
        resp  = (
            db().table("optimization_results")
            .select("plant_code, sku_code, customer_or_warehouse, route, supplied_cases, total_cost")
            .ilike("plant_code", f"%{plant}%")
            .order("customer_or_warehouse")
            .execute()
        )
        rows = resp.data
        if not rows:
            return f"No assignments found for plant '{plant}'. Run the optimizer first."
        total_cases = sum(r.get("supplied_cases") or 0 for r in rows)
        return f"Supply assignments for plant '{plant}'\nTotal: {len(rows)} rows | {total_cases:,.0f} cases\n\n" + to_table(rows)

    elif name == "get_customer_supply_plan":
        customer = args["customer_code"]
        resp     = (
            db().table("optimization_results")
            .select("customer_or_warehouse, sku_code, plant_code, route, supplied_cases, production_cost_per_case, total_freight_cost, total_cost")
            .ilike("customer_or_warehouse", f"%{customer}%")
            .order("sku_code")
            .execute()
        )
        rows = resp.data
        if not rows:
            return f"No supply plan found for customer '{customer}'. Run the optimizer first."
        total_cases = sum(r.get("supplied_cases") or 0 for r in rows)
        total_cost  = sum(r.get("total_cost") or 0 for r in rows)
        return f"Supply plan for customer '{customer}'\nTotal: {len(rows)} SKU line(s) | {total_cases:,.0f} cases | Cost: {total_cost:,.2f}\n\n" + to_table(rows)

    return f"Unknown tool: {name}"


if __name__ == "__main__":
    from mcp.server.stdio import stdio_server
    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await mcp.run(read_stream, write_stream, mcp.create_initialization_options())
    asyncio.run(main())
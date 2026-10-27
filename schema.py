"""Single source of truth for the data model.

Everything else (data dictionary markdown, SQL DDL, PK/FK/enum/null validation)
is generated from TABLES, so documentation and checks can never drift apart.

Field tuple: (name, type, required, allowed_values_or_range, unit, rule)
type is one of: str, int, float, date, bool
"""

CATEGORIES = ["ELEC", "MECH", "PACK", "RAW"]
SKU_UOMS = ["EA", "BOX", "KG"]
ALL_UOMS = ["EA", "BOX", "KG", "LB"]
LOC_TYPES = ["PLANT", "DC", "STORE"]
REGIONS = ["NORTH", "SOUTH", "EAST", "WEST"]
SUPPLIER_REGIONS = ["IN", "CN", "DE", "US", "MX"]
APPROVAL = ["APPROVED", "PENDING", "REJECTED"]
PO_STATUS = ["PLANNED", "CONFIRMED", "SHIPPED", "DELAYED", "CANCELLED"]
PROD_STATUS = ["PLANNED", "RELEASED"]
CAUSES = ["TRANSPORT_DELAY", "SUPPLIER_CAPACITY", "PRODUCTION_CAPACITY", "DEMAND_SPIKE",
          "PO_CANCELLED", "LEAD_TIME_GAP", "NO_INBOUND_PLANNED", "INSUFFICIENT_SUPPLY"]
SHORTAGE_STATUS = ["OPEN", "MITIGATION_PROPOSED", "ESCALATED"]
MIT_TYPES = ["ALT_SUPPLIER", "EXPEDITE_PO", "SUBSTITUTE", "PRODUCTION_BOOST"]

# Allowed lifecycle transitions for purchase orders (event sourcing in po_event)
PO_TRANSITIONS = {
    None: ["PLANNED"],
    "PLANNED": ["CONFIRMED", "CANCELLED"],
    "CONFIRMED": ["SHIPPED", "CANCELLED"],
    "SHIPPED": ["DELAYED"],
    "DELAYED": [],
    "CANCELLED": [],
}

TABLES = {
    "sku": dict(
        desc="Item master. One row per stock-keeping unit (parent table).",
        pk=["sku_id"], unique=[], fks=[],
        fields=[
            ("sku_id", "str", True, "SKU-NNNNNN", "-", "PK, immutable, zero-padded counter"),
            ("sku_name", "str", True, "free text", "-", "non-empty"),
            ("category", "str", True, CATEGORIES, "-", "RAW items are never 'make' items"),
            ("uom", "str", True, SKU_UOMS, "-", "Base unit of measure; all quantities are in this unit"),
            ("unit_cost", "float", True, ">= 0.5", "USD per base unit", "2 decimals"),
            ("is_make", "bool", True, "0/1", "-", "1 = produced in-house at a PLANT (has BOM)"),
        ]),
    "location": dict(
        desc="Stocking/production locations (parent table).",
        pk=["location_id"], unique=[], fks=[],
        fields=[
            ("location_id", "str", True, "LOC-NNN", "-", "PK, immutable"),
            ("location_name", "str", True, "free text", "-", ""),
            ("location_type", "str", True, LOC_TYPES, "-", "Only PLANT locations have production capacity"),
            ("region", "str", True, REGIONS, "-", ""),
        ]),
    "supplier": dict(
        desc="Supplier master (parent table).",
        pk=["supplier_id"], unique=[], fks=[],
        fields=[
            ("supplier_id", "str", True, "SUP-NNNN", "-", "PK, immutable"),
            ("supplier_name", "str", True, "free text", "-", ""),
            ("region", "str", True, SUPPLIER_REGIONS, "-", ""),
            ("reliability", "float", True, "0..1", "ratio", "Drives probability of transport delay"),
            ("is_constrained", "bool", True, "0/1", "-", "1 = capacity-constrained supplier (capacity x0.35)"),
        ]),
    "uom_conversion": dict(
        desc="Unit-of-measure conversion factors (reference data).",
        pk=["from_uom", "to_uom"], unique=[], fks=[],
        fields=[
            ("from_uom", "str", True, ALL_UOMS, "-", ""),
            ("to_uom", "str", True, ALL_UOMS, "-", ""),
            ("factor", "float", True, "> 0", "to_uom per from_uom", "qty_in_to_uom = qty_in_from_uom * factor"),
        ]),
    "sku_substitute": dict(
        desc="Bridge table SKU <-> SKU (N:M). A substitute may be used only when APPROVED and effective.",
        pk=["sku_id", "substitute_sku_id"], unique=[],
        fks=[(("sku_id",), "sku", ("sku_id",)), (("substitute_sku_id",), "sku", ("sku_id",))],
        fields=[
            ("sku_id", "str", True, "FK sku", "-", "Original SKU"),
            ("substitute_sku_id", "str", True, "FK sku", "-", "Must differ from sku_id"),
            ("approval_status", "str", True, APPROVAL, "-", "Only APPROVED substitutes may appear in mitigations"),
            ("effective_from", "date", True, "ISO date", "-", ""),
            ("effective_to", "date", False, "ISO date or empty", "-", ">= effective_from; empty = open ended"),
        ]),
    "bom": dict(
        desc="Bill of materials (make SKU -> RAW component). N:M between SKUs.",
        pk=["parent_sku_id", "component_sku_id"], unique=[],
        fks=[(("parent_sku_id",), "sku", ("sku_id",)), (("component_sku_id",), "sku", ("sku_id",))],
        fields=[
            ("parent_sku_id", "str", True, "FK sku", "-", "is_make = 1"),
            ("component_sku_id", "str", True, "FK sku", "-", "category RAW"),
            ("qty_per", "int", True, "1..4", "component units per parent unit", ""),
        ]),
    "lead_time": dict(
        desc="Which supplier can supply which SKU, with lead time and MOQ (N:M bridge SKU <-> Supplier).",
        pk=["sku_id", "supplier_id"], unique=[],
        fks=[(("sku_id",), "sku", ("sku_id",)), (("supplier_id",), "supplier", ("supplier_id",))],
        fields=[
            ("sku_id", "str", True, "FK sku", "-", ""),
            ("supplier_id", "str", True, "FK supplier", "-", ""),
            ("lead_time_days", "int", True, "7..60", "calendar days", "order_date -> promised_date"),
            ("moq", "int", True, [1, 10, 25, 50], "base units", "Minimum order quantity"),
            ("effective_from", "date", True, "ISO date", "-", ""),
            ("effective_to", "date", False, "ISO date or empty", "-", ""),
        ]),
    "supplier_capacity": dict(
        desc="Weekly committed-delivery capacity per supplier.",
        pk=["supplier_id", "week"], unique=[],
        fks=[(("supplier_id",), "supplier", ("supplier_id",))],
        fields=[
            ("supplier_id", "str", True, "FK supplier", "-", ""),
            ("week", "str", True, "2026W01..2026W52", "-", ""),
            ("week_start", "date", True, "ISO Monday", "-", ""),
            ("capacity_units", "int", True, ">= 10", "base units / week", "Sum of active PO qty_base by promised week must not exceed this"),
        ]),
    "production_capacity": dict(
        desc="Weekly production line capacity per PLANT location.",
        pk=["location_id", "week"], unique=[],
        fks=[(("location_id",), "location", ("location_id",))],
        fields=[
            ("location_id", "str", True, "FK location (PLANT)", "-", ""),
            ("week", "str", True, "2026W01..2026W52", "-", ""),
            ("week_start", "date", True, "ISO Monday", "-", ""),
            ("capacity_units", "int", True, ">= 1", "base units / week", "Sum of planned_qty per plant-week must not exceed this"),
        ]),
    "forecast_demand": dict(
        desc="Weekly forecast per SKU-location (52 weeks).",
        pk=["demand_id"], unique=[["sku_id", "location_id", "week"]],
        fks=[(("sku_id",), "sku", ("sku_id",)), (("location_id",), "location", ("location_id",))],
        fields=[
            ("demand_id", "str", True, "DEM-<sku>-<loc>-2026Www", "-", "PK; must equal 'DEM-'+sku_id+'-'+location_id+'-'+week"),
            ("sku_id", "str", True, "FK sku", "-", ""),
            ("location_id", "str", True, "FK location", "-", ""),
            ("week", "str", True, "2026W01..2026W52", "-", ""),
            ("week_start", "date", True, "ISO Monday", "-", ""),
            ("forecast_qty", "int", True, ">= 0", "base units", ""),
        ]),
    "inventory": dict(
        desc="Opening on-hand snapshot (start of 2026W01) per SKU-location.",
        pk=["inventory_id"], unique=[["sku_id", "location_id"]],
        fks=[(("sku_id",), "sku", ("sku_id",)), (("location_id",), "location", ("location_id",))],
        fields=[
            ("inventory_id", "str", True, "INV-<sku>-<loc>", "-", "PK"),
            ("sku_id", "str", True, "FK sku", "-", ""),
            ("location_id", "str", True, "FK location", "-", ""),
            ("snapshot_date", "date", True, "2025-12-29", "-", "Opening balance date"),
            ("on_hand_qty", "int", True, ">= 0", "base units", ""),
            ("safety_stock_qty", "int", True, ">= 0", "base units", "~1 week of average demand"),
        ]),
    "purchase_order": dict(
        desc="Inbound purchase orders (latest state; history is in po_event).",
        pk=["po_id"], unique=[],
        fks=[(("sku_id",), "sku", ("sku_id",)), (("supplier_id",), "supplier", ("supplier_id",)),
             (("location_id",), "location", ("location_id",)),
             (("sku_id", "supplier_id"), "lead_time", ("sku_id", "supplier_id")),
             (("sku_id", "location_id"), "inventory", ("sku_id", "location_id"))],
        fields=[
            ("po_id", "str", True, "PO-2026-NNNNNN", "-", "PK, immutable"),
            ("sku_id", "str", True, "FK sku", "-", ""),
            ("supplier_id", "str", True, "FK supplier", "-", "Must be a valid (sku, supplier) pair in lead_time"),
            ("location_id", "str", True, "FK location", "-", "Destination"),
            ("order_date", "date", True, "ISO date", "-", ">= plan run date 2025-12-01"),
            ("promised_date", "date", True, "ISO date", "-", "order_date + lead_time_days"),
            ("expected_arrival_date", "date", True, "ISO date", "-", "promised_date + transport_delay_days"),
            ("qty_ordered", "int", True, ">= 1", "order_uom", ""),
            ("order_uom", "str", True, ALL_UOMS, "-", "Normally equals sku.uom"),
            ("qty_base", "int", True, ">= 1", "base units", "= round(qty_ordered * factor(order_uom -> sku.uom)); >= moq"),
            ("status", "str", True, PO_STATUS, "-", "Equals the last event in po_event"),
            ("transport_delay_days", "int", True, ">= 0", "days", "> 0 only for DELAYED"),
            ("po_value", "float", True, ">= 0", "USD", "qty_base * sku.unit_cost"),
        ]),
    "po_event": dict(
        desc="Append-only PO lifecycle history (state changes are never overwritten).",
        pk=["po_id", "event_seq"], unique=[],
        fks=[(("po_id",), "purchase_order", ("po_id",))],
        fields=[
            ("po_id", "str", True, "FK purchase_order", "-", ""),
            ("event_seq", "int", True, ">= 1", "-", "1,2,3... contiguous per PO"),
            ("event_type", "str", True, PO_STATUS, "-", "Transition must be allowed (see README)"),
            ("event_date", "date", True, "ISO date", "-", "Non-decreasing within a PO"),
        ]),
    "production_plan": dict(
        desc="Planned production quantities per make SKU at a PLANT, by week.",
        pk=["plan_id"], unique=[["sku_id", "location_id", "week"]],
        fks=[(("sku_id",), "sku", ("sku_id",)), (("location_id",), "location", ("location_id",)),
             (("sku_id", "location_id"), "inventory", ("sku_id", "location_id"))],
        fields=[
            ("plan_id", "str", True, "PP-2026-NNNNNN", "-", "PK"),
            ("sku_id", "str", True, "FK sku", "-", "is_make = 1"),
            ("location_id", "str", True, "FK location", "-", "location_type = PLANT"),
            ("week", "str", True, "2026W02..2026W52", "-", "Production starts no earlier than W02"),
            ("week_start", "date", True, "ISO Monday", "-", ""),
            ("planned_qty", "int", True, ">= 1", "base units", "Sum per plant-week <= production_capacity"),
            ("status", "str", True, PROD_STATUS, "-", ""),
        ]),
    "production_component_requirement": dict(
        desc="Derived BOM explosion: component quantity required by each production plan row.",
        pk=["plan_id", "component_sku_id"], unique=[],
        fks=[(("plan_id",), "production_plan", ("plan_id",)), (("component_sku_id",), "sku", ("sku_id",))],
        fields=[
            ("plan_id", "str", True, "FK production_plan", "-", ""),
            ("component_sku_id", "str", True, "FK sku", "-", ""),
            ("required_qty", "int", True, ">= 1", "component base units", "= planned_qty * bom.qty_per"),
        ]),
    "projected_balance": dict(
        desc="Derived week-by-week projected available balance per SKU-location.",
        pk=["sku_id", "location_id", "week"], unique=[],
        fks=[(("sku_id", "location_id"), "inventory", ("sku_id", "location_id"))],
        fields=[
            ("sku_id", "str", True, "FK", "-", ""),
            ("location_id", "str", True, "FK", "-", ""),
            ("week", "str", True, "2026W01..2026W52", "-", ""),
            ("opening_qty", "int", True, "any integer", "base units", "W01 = on_hand_qty, else previous closing_qty"),
            ("forecast_qty", "int", True, ">= 0", "base units", "= forecast_demand.forecast_qty"),
            ("po_receipts_qty", "int", True, ">= 0", "base units", "active PO qty_base by expected arrival week"),
            ("production_qty", "int", True, ">= 0", "base units", "production_plan.planned_qty"),
            ("closing_qty", "int", True, "any integer (negative = backlog)", "base units",
             "= opening + po_receipts + production - forecast"),
        ]),
    "shortage": dict(
        desc="One row per shortage episode (consecutive weeks of negative projected balance).",
        pk=["shortage_id"], unique=[["sku_id", "location_id", "first_week"]],
        fks=[(("sku_id", "location_id"), "inventory", ("sku_id", "location_id"))],
        fields=[
            ("shortage_id", "str", True, "SHORT-2026-NNNNNN", "-", "PK"),
            ("sku_id", "str", True, "FK", "-", ""),
            ("location_id", "str", True, "FK", "-", ""),
            ("first_week", "str", True, "week label", "-", "First week closing_qty < 0"),
            ("need_date", "date", True, "ISO Monday", "-", "week_start of first_week"),
            ("end_week", "str", True, "week label", "-", "Last consecutive negative week"),
            ("weeks_affected", "int", True, ">= 1", "weeks", ""),
            ("shortage_qty", "int", True, ">= 1", "base units", "Peak backlog = -min(closing_qty) in the episode"),
            ("value_at_risk", "float", True, ">= 0", "USD", "shortage_qty * unit_cost"),
            ("cause_code", "str", True, CAUSES, "-", "Counterfactual rule, see README"),
            ("cause_detail", "str", True, "free text", "-", "Human-readable explanation"),
            ("lead_time_days_used", "int", True, "7..60", "days", "Shortest lead_time_days among the SKU's suppliers"),
            ("latest_order_date", "date", True, "ISO date", "-", "need_date - lead_time_days_used"),
            ("ordering_window_open", "bool", True, "0/1", "-", "latest_order_date >= plan run date (2025-12-01)"),
            ("priority_score", "float", True, ">= 0", "-", "value_at_risk * (1 + 4 / first_week_number)"),
            ("priority_rank", "int", True, ">= 1", "-", "1 = most urgent (score descending)"),
            ("status", "str", True, SHORTAGE_STATUS, "-",
             "MITIGATION_PROPOSED if a valid option fully resolves it; OPEN if only partial options exist; ESCALATED if none"),
        ]),
    "mitigation_option": dict(
        desc="Candidate mitigations per shortage with cost and service trade-offs.",
        pk=["mitigation_id"], unique=[],
        fks=[(("shortage_id",), "shortage", ("shortage_id",)), (("supplier_id",), "supplier", ("supplier_id",)),
             (("substitute_sku_id",), "sku", ("sku_id",)), (("source_po_id",), "purchase_order", ("po_id",))],
        fields=[
            ("mitigation_id", "str", True, "MIT-<shortage_id>-NN", "-", "PK"),
            ("shortage_id", "str", True, "FK shortage", "-", ""),
            ("option_type", "str", True, MIT_TYPES, "-", ""),
            ("supplier_id", "str", False, "FK supplier", "-", "ALT_SUPPLIER only"),
            ("substitute_sku_id", "str", False, "FK sku", "-", "SUBSTITUTE only; must be APPROVED and effective"),
            ("source_po_id", "str", False, "FK purchase_order", "-", "EXPEDITE_PO only"),
            ("recovery_qty", "int", True, ">= 1", "base units", "ALT_SUPPLIER qty <= remaining supplier capacity"),
            ("lead_time_days", "int", True, ">= 0", "days", "ALT_SUPPLIER: lead_time table value; EXPEDITE_PO: >= 50% of original"),
            ("recovery_week", "str", True, "week label", "-", "Week the recovered quantity is available"),
            ("extra_cost", "float", True, ">= 0", "USD", "Premium over the baseline plan"),
            ("cost_per_unit", "float", True, ">= 0", "USD / unit", "extra_cost / recovery_qty"),
            ("service_level_pct", "float", True, "0..100", "%", "coverage x lateness penalty (10% per late week)"),
            ("resolves_shortage", "bool", True, "0/1", "-", "qty >= shortage_qty and recovery_week <= first_week"),
            ("recommended", "bool", True, "0/1", "-", "Best option: resolving first, then cheapest; else best service"),
        ]),
}

# Load order respects FK dependencies (parents first)
TABLE_ORDER = ["sku", "location", "supplier", "uom_conversion", "sku_substitute", "bom", "lead_time",
               "supplier_capacity", "production_capacity", "forecast_demand", "inventory", "purchase_order",
               "po_event", "production_plan", "production_component_requirement", "projected_balance",
               "shortage", "mitigation_option"]

SQL_TYPES = {"str": "TEXT", "int": "INTEGER", "float": "REAL", "date": "TEXT", "bool": "INTEGER"}


def columns(table):
    return [f[0] for f in TABLES[table]["fields"]]


def render_ddl():
    out = ["-- Generated from schema.py. Do not edit by hand.", "PRAGMA foreign_keys = ON;", ""]
    for t in TABLE_ORDER:
        spec = TABLES[t]
        lines = []
        for name, typ, req, allowed, _unit, _rule in spec["fields"]:
            line = f"  {name} {SQL_TYPES[typ]}"
            if req:
                line += " NOT NULL"
            if isinstance(allowed, list) and typ == "str":
                vals = ", ".join(f"'{v}'" for v in allowed)
                line += f" CHECK ({name} IN ({vals}))"
            lines.append(line)
        lines.append(f"  PRIMARY KEY ({', '.join(spec['pk'])})")
        for u in spec["unique"]:
            lines.append(f"  UNIQUE ({', '.join(u)})")
        for cols, ref, rcols in spec["fks"]:
            lines.append(f"  FOREIGN KEY ({', '.join(cols)}) REFERENCES {ref} ({', '.join(rcols)})")
        out.append(f"CREATE TABLE {t} (\n" + ",\n".join(lines) + "\n);\n")
    return "\n".join(out)


def render_dictionary():
    md = ["# Data dictionary", "",
          "_Generated from `schema.py` (`python schema.py`). All quantities are in the SKU base unit unless stated. "
          "All dates are ISO-8601. Week labels are `2026Www`; week 1 starts Monday 2025-12-29 (ISO week)._", ""]
    for t in TABLE_ORDER:
        spec = TABLES[t]
        md += [f"## `{t}`", "", spec["desc"], "",
               f"- **Primary key:** `{', '.join(spec['pk'])}`"]
        for u in spec["unique"]:
            md.append(f"- **Unique:** `{', '.join(u)}`")
        for cols, ref, rcols in spec["fks"]:
            md.append(f"- **FK:** `{', '.join(cols)}` -> `{ref}({', '.join(rcols)})`")
        md += ["", "| Field | Type | Required | Allowed values / range | Unit | Uniqueness | Validation rule |",
               "|---|---|---|---|---|---|---|"]
        for name, typ, req, allowed, unit, rule in spec["fields"]:
            av = ", ".join(map(str, allowed)) if isinstance(allowed, list) else allowed
            uniq = "unique" if spec["pk"] == [name] else ("part of PK" if name in spec["pk"] else "")
            md.append(f"| `{name}` | {typ} | {'yes' if req else 'no'} | {av} | {unit} | {uniq} | {rule} |")
        md.append("")
    return "\n".join(md)


if __name__ == "__main__":
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(here, "docs"), exist_ok=True)
    with open(os.path.join(here, "schema.sql"), "w") as f:
        f.write(render_ddl())
    with open(os.path.join(here, "docs", "data_dictionary.md"), "w") as f:
        f.write(render_dictionary())
    print("wrote schema.sql and docs/data_dictionary.md")

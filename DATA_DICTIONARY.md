# Data dictionary

_Generated from `schema.py` (`python schema.py`). All quantities are in the SKU base unit unless stated. All dates are ISO-8601. Week labels are `2026Www`; week 1 starts Monday 2025-12-29 (ISO week)._

## `sku`

Item master. One row per stock-keeping unit (parent table).

- **Primary key:** `sku_id`

| Field | Type | Required | Allowed values / range | Unit | Uniqueness | Validation rule |
|---|---|---|---|---|---|---|
| `sku_id` | str | yes | SKU-NNNNNN | - | unique | PK, immutable, zero-padded counter |
| `sku_name` | str | yes | free text | - |  | non-empty |
| `category` | str | yes | ELEC, MECH, PACK, RAW | - |  | RAW items are never 'make' items |
| `uom` | str | yes | EA, BOX, KG | - |  | Base unit of measure; all quantities are in this unit |
| `unit_cost` | float | yes | >= 0.5 | USD per base unit |  | 2 decimals |
| `is_make` | bool | yes | 0/1 | - |  | 1 = produced in-house at a PLANT (has BOM) |

## `location`

Stocking/production locations (parent table).

- **Primary key:** `location_id`

| Field | Type | Required | Allowed values / range | Unit | Uniqueness | Validation rule |
|---|---|---|---|---|---|---|
| `location_id` | str | yes | LOC-NNN | - | unique | PK, immutable |
| `location_name` | str | yes | free text | - |  |  |
| `location_type` | str | yes | PLANT, DC, STORE | - |  | Only PLANT locations have production capacity |
| `region` | str | yes | NORTH, SOUTH, EAST, WEST | - |  |  |

## `supplier`

Supplier master (parent table).

- **Primary key:** `supplier_id`

| Field | Type | Required | Allowed values / range | Unit | Uniqueness | Validation rule |
|---|---|---|---|---|---|---|
| `supplier_id` | str | yes | SUP-NNNN | - | unique | PK, immutable |
| `supplier_name` | str | yes | free text | - |  |  |
| `region` | str | yes | IN, CN, DE, US, MX | - |  |  |
| `reliability` | float | yes | 0..1 | ratio |  | Drives probability of transport delay |
| `is_constrained` | bool | yes | 0/1 | - |  | 1 = capacity-constrained supplier (capacity x0.35) |

## `uom_conversion`

Unit-of-measure conversion factors (reference data).

- **Primary key:** `from_uom, to_uom`

| Field | Type | Required | Allowed values / range | Unit | Uniqueness | Validation rule |
|---|---|---|---|---|---|---|
| `from_uom` | str | yes | EA, BOX, KG, LB | - | part of PK |  |
| `to_uom` | str | yes | EA, BOX, KG, LB | - | part of PK |  |
| `factor` | float | yes | > 0 | to_uom per from_uom |  | qty_in_to_uom = qty_in_from_uom * factor |

## `sku_substitute`

Bridge table SKU <-> SKU (N:M). A substitute may be used only when APPROVED and effective.

- **Primary key:** `sku_id, substitute_sku_id`
- **FK:** `sku_id` -> `sku(sku_id)`
- **FK:** `substitute_sku_id` -> `sku(sku_id)`

| Field | Type | Required | Allowed values / range | Unit | Uniqueness | Validation rule |
|---|---|---|---|---|---|---|
| `sku_id` | str | yes | FK sku | - | part of PK | Original SKU |
| `substitute_sku_id` | str | yes | FK sku | - | part of PK | Must differ from sku_id |
| `approval_status` | str | yes | APPROVED, PENDING, REJECTED | - |  | Only APPROVED substitutes may appear in mitigations |
| `effective_from` | date | yes | ISO date | - |  |  |
| `effective_to` | date | no | ISO date or empty | - |  | >= effective_from; empty = open ended |

## `bom`

Bill of materials (make SKU -> RAW component). N:M between SKUs.

- **Primary key:** `parent_sku_id, component_sku_id`
- **FK:** `parent_sku_id` -> `sku(sku_id)`
- **FK:** `component_sku_id` -> `sku(sku_id)`

| Field | Type | Required | Allowed values / range | Unit | Uniqueness | Validation rule |
|---|---|---|---|---|---|---|
| `parent_sku_id` | str | yes | FK sku | - | part of PK | is_make = 1 |
| `component_sku_id` | str | yes | FK sku | - | part of PK | category RAW |
| `qty_per` | int | yes | 1..4 | component units per parent unit |  |  |

## `lead_time`

Which supplier can supply which SKU, with lead time and MOQ (N:M bridge SKU <-> Supplier).

- **Primary key:** `sku_id, supplier_id`
- **FK:** `sku_id` -> `sku(sku_id)`
- **FK:** `supplier_id` -> `supplier(supplier_id)`

| Field | Type | Required | Allowed values / range | Unit | Uniqueness | Validation rule |
|---|---|---|---|---|---|---|
| `sku_id` | str | yes | FK sku | - | part of PK |  |
| `supplier_id` | str | yes | FK supplier | - | part of PK |  |
| `lead_time_days` | int | yes | 7..60 | calendar days |  | order_date -> promised_date |
| `moq` | int | yes | 1, 10, 25, 50 | base units |  | Minimum order quantity |
| `effective_from` | date | yes | ISO date | - |  |  |
| `effective_to` | date | no | ISO date or empty | - |  |  |

## `supplier_capacity`

Weekly committed-delivery capacity per supplier.

- **Primary key:** `supplier_id, week`
- **FK:** `supplier_id` -> `supplier(supplier_id)`

| Field | Type | Required | Allowed values / range | Unit | Uniqueness | Validation rule |
|---|---|---|---|---|---|---|
| `supplier_id` | str | yes | FK supplier | - | part of PK |  |
| `week` | str | yes | 2026W01..2026W52 | - | part of PK |  |
| `week_start` | date | yes | ISO Monday | - |  |  |
| `capacity_units` | int | yes | >= 10 | base units / week |  | Sum of active PO qty_base by promised week must not exceed this |

## `production_capacity`

Weekly production line capacity per PLANT location.

- **Primary key:** `location_id, week`
- **FK:** `location_id` -> `location(location_id)`

| Field | Type | Required | Allowed values / range | Unit | Uniqueness | Validation rule |
|---|---|---|---|---|---|---|
| `location_id` | str | yes | FK location (PLANT) | - | part of PK |  |
| `week` | str | yes | 2026W01..2026W52 | - | part of PK |  |
| `week_start` | date | yes | ISO Monday | - |  |  |
| `capacity_units` | int | yes | >= 1 | base units / week |  | Sum of planned_qty per plant-week must not exceed this |

## `forecast_demand`

Weekly forecast per SKU-location (52 weeks).

- **Primary key:** `demand_id`
- **Unique:** `sku_id, location_id, week`
- **FK:** `sku_id` -> `sku(sku_id)`
- **FK:** `location_id` -> `location(location_id)`

| Field | Type | Required | Allowed values / range | Unit | Uniqueness | Validation rule |
|---|---|---|---|---|---|---|
| `demand_id` | str | yes | DEM-<sku>-<loc>-2026Www | - | unique | PK; must equal 'DEM-'+sku_id+'-'+location_id+'-'+week |
| `sku_id` | str | yes | FK sku | - |  |  |
| `location_id` | str | yes | FK location | - |  |  |
| `week` | str | yes | 2026W01..2026W52 | - |  |  |
| `week_start` | date | yes | ISO Monday | - |  |  |
| `forecast_qty` | int | yes | >= 0 | base units |  |  |

## `inventory`

Opening on-hand snapshot (start of 2026W01) per SKU-location.

- **Primary key:** `inventory_id`
- **Unique:** `sku_id, location_id`
- **FK:** `sku_id` -> `sku(sku_id)`
- **FK:** `location_id` -> `location(location_id)`

| Field | Type | Required | Allowed values / range | Unit | Uniqueness | Validation rule |
|---|---|---|---|---|---|---|
| `inventory_id` | str | yes | INV-<sku>-<loc> | - | unique | PK |
| `sku_id` | str | yes | FK sku | - |  |  |
| `location_id` | str | yes | FK location | - |  |  |
| `snapshot_date` | date | yes | 2025-12-29 | - |  | Opening balance date |
| `on_hand_qty` | int | yes | >= 0 | base units |  |  |
| `safety_stock_qty` | int | yes | >= 0 | base units |  | ~1 week of average demand |

## `purchase_order`

Inbound purchase orders (latest state; history is in po_event).

- **Primary key:** `po_id`
- **FK:** `sku_id` -> `sku(sku_id)`
- **FK:** `supplier_id` -> `supplier(supplier_id)`
- **FK:** `location_id` -> `location(location_id)`
- **FK:** `sku_id, supplier_id` -> `lead_time(sku_id, supplier_id)`
- **FK:** `sku_id, location_id` -> `inventory(sku_id, location_id)`

| Field | Type | Required | Allowed values / range | Unit | Uniqueness | Validation rule |
|---|---|---|---|---|---|---|
| `po_id` | str | yes | PO-2026-NNNNNN | - | unique | PK, immutable |
| `sku_id` | str | yes | FK sku | - |  |  |
| `supplier_id` | str | yes | FK supplier | - |  | Must be a valid (sku, supplier) pair in lead_time |
| `location_id` | str | yes | FK location | - |  | Destination |
| `order_date` | date | yes | ISO date | - |  | >= plan run date 2025-12-01 |
| `promised_date` | date | yes | ISO date | - |  | order_date + lead_time_days |
| `expected_arrival_date` | date | yes | ISO date | - |  | promised_date + transport_delay_days |
| `qty_ordered` | int | yes | >= 1 | order_uom |  |  |
| `order_uom` | str | yes | EA, BOX, KG, LB | - |  | Normally equals sku.uom |
| `qty_base` | int | yes | >= 1 | base units |  | = round(qty_ordered * factor(order_uom -> sku.uom)); >= moq |
| `status` | str | yes | PLANNED, CONFIRMED, SHIPPED, DELAYED, CANCELLED | - |  | Equals the last event in po_event |
| `transport_delay_days` | int | yes | >= 0 | days |  | > 0 only for DELAYED |
| `po_value` | float | yes | >= 0 | USD |  | qty_base * sku.unit_cost |

## `po_event`

Append-only PO lifecycle history (state changes are never overwritten).

- **Primary key:** `po_id, event_seq`
- **FK:** `po_id` -> `purchase_order(po_id)`

| Field | Type | Required | Allowed values / range | Unit | Uniqueness | Validation rule |
|---|---|---|---|---|---|---|
| `po_id` | str | yes | FK purchase_order | - | part of PK |  |
| `event_seq` | int | yes | >= 1 | - | part of PK | 1,2,3... contiguous per PO |
| `event_type` | str | yes | PLANNED, CONFIRMED, SHIPPED, DELAYED, CANCELLED | - |  | Transition must be allowed (see README) |
| `event_date` | date | yes | ISO date | - |  | Non-decreasing within a PO |

## `production_plan`

Planned production quantities per make SKU at a PLANT, by week.

- **Primary key:** `plan_id`
- **Unique:** `sku_id, location_id, week`
- **FK:** `sku_id` -> `sku(sku_id)`
- **FK:** `location_id` -> `location(location_id)`
- **FK:** `sku_id, location_id` -> `inventory(sku_id, location_id)`

| Field | Type | Required | Allowed values / range | Unit | Uniqueness | Validation rule |
|---|---|---|---|---|---|---|
| `plan_id` | str | yes | PP-2026-NNNNNN | - | unique | PK |
| `sku_id` | str | yes | FK sku | - |  | is_make = 1 |
| `location_id` | str | yes | FK location | - |  | location_type = PLANT |
| `week` | str | yes | 2026W02..2026W52 | - |  | Production starts no earlier than W02 |
| `week_start` | date | yes | ISO Monday | - |  |  |
| `planned_qty` | int | yes | >= 1 | base units |  | Sum per plant-week <= production_capacity |
| `status` | str | yes | PLANNED, RELEASED | - |  |  |

## `production_component_requirement`

Derived BOM explosion: component quantity required by each production plan row.

- **Primary key:** `plan_id, component_sku_id`
- **FK:** `plan_id` -> `production_plan(plan_id)`
- **FK:** `component_sku_id` -> `sku(sku_id)`

| Field | Type | Required | Allowed values / range | Unit | Uniqueness | Validation rule |
|---|---|---|---|---|---|---|
| `plan_id` | str | yes | FK production_plan | - | part of PK |  |
| `component_sku_id` | str | yes | FK sku | - | part of PK |  |
| `required_qty` | int | yes | >= 1 | component base units |  | = planned_qty * bom.qty_per |

## `projected_balance`

Derived week-by-week projected available balance per SKU-location.

- **Primary key:** `sku_id, location_id, week`
- **FK:** `sku_id, location_id` -> `inventory(sku_id, location_id)`

| Field | Type | Required | Allowed values / range | Unit | Uniqueness | Validation rule |
|---|---|---|---|---|---|---|
| `sku_id` | str | yes | FK | - | part of PK |  |
| `location_id` | str | yes | FK | - | part of PK |  |
| `week` | str | yes | 2026W01..2026W52 | - | part of PK |  |
| `opening_qty` | int | yes | any integer | base units |  | W01 = on_hand_qty, else previous closing_qty |
| `forecast_qty` | int | yes | >= 0 | base units |  | = forecast_demand.forecast_qty |
| `po_receipts_qty` | int | yes | >= 0 | base units |  | active PO qty_base by expected arrival week |
| `production_qty` | int | yes | >= 0 | base units |  | production_plan.planned_qty |
| `closing_qty` | int | yes | any integer (negative = backlog) | base units |  | = opening + po_receipts + production - forecast |

## `shortage`

One row per shortage episode (consecutive weeks of negative projected balance).

- **Primary key:** `shortage_id`
- **Unique:** `sku_id, location_id, first_week`
- **FK:** `sku_id, location_id` -> `inventory(sku_id, location_id)`

| Field | Type | Required | Allowed values / range | Unit | Uniqueness | Validation rule |
|---|---|---|---|---|---|---|
| `shortage_id` | str | yes | SHORT-2026-NNNNNN | - | unique | PK |
| `sku_id` | str | yes | FK | - |  |  |
| `location_id` | str | yes | FK | - |  |  |
| `first_week` | str | yes | week label | - |  | First week closing_qty < 0 |
| `need_date` | date | yes | ISO Monday | - |  | week_start of first_week |
| `end_week` | str | yes | week label | - |  | Last consecutive negative week |
| `weeks_affected` | int | yes | >= 1 | weeks |  |  |
| `shortage_qty` | int | yes | >= 1 | base units |  | Peak backlog = -min(closing_qty) in the episode |
| `value_at_risk` | float | yes | >= 0 | USD |  | shortage_qty * unit_cost |
| `cause_code` | str | yes | TRANSPORT_DELAY, SUPPLIER_CAPACITY, PRODUCTION_CAPACITY, DEMAND_SPIKE, PO_CANCELLED, LEAD_TIME_GAP, NO_INBOUND_PLANNED, INSUFFICIENT_SUPPLY | - |  | Counterfactual rule, see README |
| `cause_detail` | str | yes | free text | - |  | Human-readable explanation |
| `lead_time_days_used` | int | yes | 7..60 | days |  | Shortest lead_time_days among the SKU's suppliers |
| `latest_order_date` | date | yes | ISO date | - |  | need_date - lead_time_days_used |
| `ordering_window_open` | bool | yes | 0/1 | - |  | latest_order_date >= plan run date (2025-12-01) |
| `priority_score` | float | yes | >= 0 | - |  | value_at_risk * (1 + 4 / first_week_number) |
| `priority_rank` | int | yes | >= 1 | - |  | 1 = most urgent (score descending) |
| `status` | str | yes | OPEN, MITIGATION_PROPOSED, ESCALATED | - |  | MITIGATION_PROPOSED if a valid option fully resolves it; OPEN if only partial options exist; ESCALATED if none |

## `mitigation_option`

Candidate mitigations per shortage with cost and service trade-offs.

- **Primary key:** `mitigation_id`
- **FK:** `shortage_id` -> `shortage(shortage_id)`
- **FK:** `supplier_id` -> `supplier(supplier_id)`
- **FK:** `substitute_sku_id` -> `sku(sku_id)`
- **FK:** `source_po_id` -> `purchase_order(po_id)`

| Field | Type | Required | Allowed values / range | Unit | Uniqueness | Validation rule |
|---|---|---|---|---|---|---|
| `mitigation_id` | str | yes | MIT-<shortage_id>-NN | - | unique | PK |
| `shortage_id` | str | yes | FK shortage | - |  |  |
| `option_type` | str | yes | ALT_SUPPLIER, EXPEDITE_PO, SUBSTITUTE, PRODUCTION_BOOST | - |  |  |
| `supplier_id` | str | no | FK supplier | - |  | ALT_SUPPLIER only |
| `substitute_sku_id` | str | no | FK sku | - |  | SUBSTITUTE only; must be APPROVED and effective |
| `source_po_id` | str | no | FK purchase_order | - |  | EXPEDITE_PO only |
| `recovery_qty` | int | yes | >= 1 | base units |  | ALT_SUPPLIER qty <= remaining supplier capacity |
| `lead_time_days` | int | yes | >= 0 | days |  | ALT_SUPPLIER: lead_time table value; EXPEDITE_PO: >= 50% of original |
| `recovery_week` | str | yes | week label | - |  | Week the recovered quantity is available |
| `extra_cost` | float | yes | >= 0 | USD |  | Premium over the baseline plan |
| `cost_per_unit` | float | yes | >= 0 | USD / unit |  | extra_cost / recovery_qty |
| `service_level_pct` | float | yes | 0..100 | % |  | coverage x lateness penalty (10% per late week) |
| `resolves_shortage` | bool | yes | 0/1 | - |  | qty >= shortage_qty and recovery_week <= first_week |
| `recommended` | bool | yes | 0/1 | - |  | Best option: resolving first, then cheapest; else best service |

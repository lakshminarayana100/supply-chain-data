# Validation summary

Result: **PASS** (168/168 checks)

## Injected edge cases vs detectors

| Issue type | Injected | Detected | TP | FP | FN | Precision | Recall | Status |
|---|---|---|---|---|---|---|---|---|
| INBOUND_COUNTED_TWICE | 50 | 50 | 50 | 0 | 0 | 1.0 | 1.0 | PASS |
| SHORTAGE_WITHOUT_LEAD_TIME | 102 | 102 | 102 | 0 | 0 | 1.0 | 1.0 | PASS |
| SUBSTITUTE_NOT_APPROVED | 102 | 102 | 102 | 0 | 0 | 1.0 | 1.0 | PASS |
| SUPPLIER_CAPACITY_EXCEEDED | 50 | 50 | 50 | 0 | 0 | 1.0 | 1.0 | PASS |
| UOM_MISMATCH | 50 | 50 | 50 | 0 | 0 | 1.0 | 1.0 | PASS |

## Integrity checks

| Check | Status | Violations |
|---|---|---|
| sku: primary key unique (sku_id) | PASS | 0 |
| sku: all schema columns present | PASS | 0 |
| sku: required fields not null | PASS | 0 |
| sku: enum values allowed | PASS | 0 |
| location: primary key unique (location_id) | PASS | 0 |
| location: all schema columns present | PASS | 0 |
| location: required fields not null | PASS | 0 |
| location: enum values allowed | PASS | 0 |
| supplier: primary key unique (supplier_id) | PASS | 0 |
| supplier: all schema columns present | PASS | 0 |
| supplier: required fields not null | PASS | 0 |
| supplier: enum values allowed | PASS | 0 |
| uom_conversion: primary key unique (from_uom, to_uom) | PASS | 0 |
| uom_conversion: all schema columns present | PASS | 0 |
| uom_conversion: required fields not null | PASS | 0 |
| uom_conversion: enum values allowed | PASS | 0 |
| sku_substitute: primary key unique (sku_id, substitute_sku_id) | PASS | 0 |
| sku_substitute: all schema columns present | PASS | 0 |
| sku_substitute: required fields not null | PASS | 0 |
| sku_substitute: enum values allowed | PASS | 0 |
| sku_substitute: FK (sku_id) -> sku | PASS | 0 |
| sku_substitute: FK (substitute_sku_id) -> sku | PASS | 0 |
| bom: primary key unique (parent_sku_id, component_sku_id) | PASS | 0 |
| bom: all schema columns present | PASS | 0 |
| bom: required fields not null | PASS | 0 |
| bom: enum values allowed | PASS | 0 |
| bom: FK (parent_sku_id) -> sku | PASS | 0 |
| bom: FK (component_sku_id) -> sku | PASS | 0 |
| lead_time: primary key unique (sku_id, supplier_id) | PASS | 0 |
| lead_time: all schema columns present | PASS | 0 |
| lead_time: required fields not null | PASS | 0 |
| lead_time: enum values allowed | PASS | 0 |
| lead_time: FK (sku_id) -> sku | PASS | 0 |
| lead_time: FK (supplier_id) -> supplier | PASS | 0 |
| supplier_capacity: primary key unique (supplier_id, week) | PASS | 0 |
| supplier_capacity: all schema columns present | PASS | 0 |
| supplier_capacity: required fields not null | PASS | 0 |
| supplier_capacity: enum values allowed | PASS | 0 |
| supplier_capacity: FK (supplier_id) -> supplier | PASS | 0 |
| production_capacity: primary key unique (location_id, week) | PASS | 0 |
| production_capacity: all schema columns present | PASS | 0 |
| production_capacity: required fields not null | PASS | 0 |
| production_capacity: enum values allowed | PASS | 0 |
| production_capacity: FK (location_id) -> location | PASS | 0 |
| forecast_demand: primary key unique (demand_id) | PASS | 0 |
| forecast_demand: unique (sku_id, location_id, week) | PASS | 0 |
| forecast_demand: all schema columns present | PASS | 0 |
| forecast_demand: required fields not null | PASS | 0 |
| forecast_demand: enum values allowed | PASS | 0 |
| forecast_demand: FK (sku_id) -> sku | PASS | 0 |
| forecast_demand: FK (location_id) -> location | PASS | 0 |
| inventory: primary key unique (inventory_id) | PASS | 0 |
| inventory: unique (sku_id, location_id) | PASS | 0 |
| inventory: all schema columns present | PASS | 0 |
| inventory: required fields not null | PASS | 0 |
| inventory: enum values allowed | PASS | 0 |
| inventory: FK (sku_id) -> sku | PASS | 0 |
| inventory: FK (location_id) -> location | PASS | 0 |
| purchase_order: primary key unique (po_id) | PASS | 0 |
| purchase_order: all schema columns present | PASS | 0 |
| purchase_order: required fields not null | PASS | 0 |
| purchase_order: enum values allowed | PASS | 0 |
| purchase_order: FK (sku_id) -> sku | PASS | 0 |
| purchase_order: FK (supplier_id) -> supplier | PASS | 0 |
| purchase_order: FK (location_id) -> location | PASS | 0 |
| purchase_order: FK (sku_id, supplier_id) -> lead_time | PASS | 0 |
| purchase_order: FK (sku_id, location_id) -> inventory | PASS | 0 |
| po_event: primary key unique (po_id, event_seq) | PASS | 0 |
| po_event: all schema columns present | PASS | 0 |
| po_event: required fields not null | PASS | 0 |
| po_event: enum values allowed | PASS | 0 |
| po_event: FK (po_id) -> purchase_order | PASS | 0 |
| production_plan: primary key unique (plan_id) | PASS | 0 |
| production_plan: unique (sku_id, location_id, week) | PASS | 0 |
| production_plan: all schema columns present | PASS | 0 |
| production_plan: required fields not null | PASS | 0 |
| production_plan: enum values allowed | PASS | 0 |
| production_plan: FK (sku_id) -> sku | PASS | 0 |
| production_plan: FK (location_id) -> location | PASS | 0 |
| production_plan: FK (sku_id, location_id) -> inventory | PASS | 0 |
| production_component_requirement: primary key unique (plan_id, component_sku_id) | PASS | 0 |
| production_component_requirement: all schema columns present | PASS | 0 |
| production_component_requirement: required fields not null | PASS | 0 |
| production_component_requirement: enum values allowed | PASS | 0 |
| production_component_requirement: FK (plan_id) -> production_plan | PASS | 0 |
| production_component_requirement: FK (component_sku_id) -> sku | PASS | 0 |
| projected_balance: primary key unique (sku_id, location_id, week) | PASS | 0 |
| projected_balance: all schema columns present | PASS | 0 |
| projected_balance: required fields not null | PASS | 0 |
| projected_balance: enum values allowed | PASS | 0 |
| projected_balance: FK (sku_id, location_id) -> inventory | PASS | 0 |
| shortage: primary key unique (shortage_id) | PASS | 0 |
| shortage: unique (sku_id, location_id, first_week) | PASS | 0 |
| shortage: all schema columns present | PASS | 0 |
| shortage: required fields not null | PASS | 0 |
| shortage: enum values allowed | PASS | 0 |
| shortage: FK (sku_id, location_id) -> inventory | PASS | 0 |
| mitigation_option: primary key unique (mitigation_id) | PASS | 0 |
| mitigation_option: all schema columns present | PASS | 0 |
| mitigation_option: required fields not null | PASS | 0 |
| mitigation_option: enum values allowed | PASS | 0 |
| mitigation_option: FK (shortage_id) -> shortage | PASS | 0 |
| mitigation_option: FK (supplier_id) -> supplier | PASS | 0 |
| mitigation_option: FK (substitute_sku_id) -> sku | PASS | 0 |
| mitigation_option: FK (source_po_id) -> purchase_order | PASS | 0 |
| sku: sku_id format ^SKU-\d{6}$ | PASS | 0 |
| location: location_id format ^LOC-\d{3}$ | PASS | 0 |
| supplier: supplier_id format ^SUP-\d{4}$ | PASS | 0 |
| purchase_order: po_id format ^PO-2026-\d{6}$ | PASS | 0 |
| shortage: shortage_id format ^SHORT-2026-\d{6}$ | PASS | 0 |
| production_plan: plan_id format ^PP-2026-\d{6}$ | PASS | 0 |
| mitigation_option: mitigation_id format ^MIT-SHORT-2026-\d{6}-\d{2}$ | PASS | 0 |
| forecast_demand: demand_id format ^DEM-SKU-\d{6}-LOC-\d{3}-2026W\d{2}$ | PASS | 0 |
| forecast_demand: demand_id == DEM-<sku>-<loc>-<week> | PASS | 0 |
| inventory: inventory_id == INV-<sku>-<loc> | PASS | 0 |
| ground truth not leaked into input tables (no label columns) | PASS | 0 |
| PO: order_date >= plan run date | PASS | 0 |
| PO: promised_date == order_date + lead_time_days | PASS | 0 |
| PO: expected_arrival == promised + transport_delay | PASS | 0 |
| PO: delay > 0 only for DELAYED POs | PASS | 0 |
| PO: po_value == qty_base * unit_cost | PASS | 0 |
| PO: no PO for a make SKU at a plant (produced there instead) | PASS | 0 |
| PO: converted quantity >= MOQ | PASS | 0 |
| po_event: only allowed lifecycle transitions | PASS | 0 |
| po_event: sequence is contiguous 1..n | PASS | 0 |
| po_event: event dates non-decreasing | PASS | 0 |
| po_event: last event == purchase_order.status | PASS | 0 |
| po_event: every PO has history | PASS | 0 |
| sku_substitute: substitute != sku | PASS | 0 |
| sku_substitute: effective_to >= effective_from | PASS | 0 |
| bom: parent is a make SKU | PASS | 0 |
| bom: component is RAW | PASS | 0 |
| production_plan: make SKU at a PLANT | PASS | 0 |
| production_plan: week >= 2026W02 | PASS | 0 |
| production_plan: plant-week load <= production_capacity | PASS | 0 |
| component requirement == planned_qty * bom.qty_per | PASS | 0 |
| component requirement rows complete | PASS | 0 |
| balance: closing == opening + receipts + production - forecast | PASS | 0 |
| balance: opening(w) == closing(w-1) | PASS | 0 |
| balance: opening(W01) == inventory.on_hand_qty | PASS | 0 |
| balance: 52 weeks per SKU-location | PASS | 0 |
| balance: forecast == forecast_demand | PASS | 0 |
| balance: receipts == active PO qty_base by expected arrival week | PASS | 0 |
| balance: production == production_plan | PASS | 0 |
| shortage: episodes == negative-balance episodes (no missing / extra) | PASS | 0 |
| shortage: shortage_qty == peak backlog | PASS | 0 |
| shortage: end_week matches | PASS | 0 |
| shortage: value_at_risk == qty * unit_cost | PASS | 0 |
| shortage: priority_rank is a permutation ordered by score | PASS | 0 |
| shortage: every shortage has a cause code and explanation | PASS | 0 |
| shortage: status consistent with mitigation options | PASS | 0 |
| mitigation: option ids contiguous per shortage (MIT-<shortage>-01..) | PASS | 0 |
| mitigation: at most one recommended option per shortage | PASS | 0 |
| mitigation: resolves flag == (qty>=need and recovery<=need week) | PASS | 0 |
| mitigation: cost_per_unit == extra_cost/qty | PASS | 0 |
| mitigation: service level within 0..100 | PASS | 0 |
| mitigation ALT_SUPPLIER: (sku, supplier) exists in lead_time with same lead time | PASS | 0 |
| mitigation ALT_SUPPLIER: recovery week == plan run date + lead time | PASS | 0 |
| mitigation ALT_SUPPLIER: qty >= MOQ | PASS | 0 |
| mitigation ALT_SUPPLIER: qty <= remaining supplier capacity | PASS | 0 |
| mitigation EXPEDITE_PO: source PO belongs to the same SKU-location | PASS | 0 |
| mitigation EXPEDITE_PO: compression <= 50% and actually earlier | PASS | 0 |
| mitigation PRODUCTION_BOOST: make SKU at a PLANT | PASS | 0 |

## Metrics

```json
{
 "sku_location_pairs": 24000,
 "shortage_episodes": 5111,
 "pairs_with_shortage_pct": 18.67,
 "approx_fill_rate_pct": 95.66,
 "shortage_by_cause": {
  "INSUFFICIENT_SUPPLY": 1921,
  "SUPPLIER_CAPACITY": 1633,
  "LEAD_TIME_GAP": 570,
  "TRANSPORT_DELAY": 465,
  "PRODUCTION_CAPACITY": 207,
  "PO_CANCELLED": 141,
  "DEMAND_SPIKE": 103,
  "NO_INBOUND_PLANNED": 71
 },
 "shortage_by_status": {
  "MITIGATION_PROPOSED": 3030,
  "ESCALATED": 1507,
  "OPEN": 574
 },
 "shortages_with_resolving_option_pct": 60.1,
 "avg_options_per_shortage": 1.07,
 "ordering_window_closed_pct": 1.5,
 "total_value_at_risk_usd": 37688349.94,
 "avg_extra_cost_by_option_usd": {
  "ALT_SUPPLIER": 258.02,
  "EXPEDITE_PO": 1140.14,
  "PRODUCTION_BOOST": 598.59,
  "SUBSTITUTE": 2317.19
 },
 "avg_service_level_by_option_pct": {
  "ALT_SUPPLIER": 91.5,
  "EXPEDITE_PO": 90.8,
  "PRODUCTION_BOOST": 99.5,
  "SUBSTITUTE": 91.6
 },
 "po_count": 10050,
 "po_status": {
  "CONFIRMED": 3083,
  "SHIPPED": 2800,
  "PLANNED": 2078,
  "DELAYED": 1788,
  "CANCELLED": 301
 },
 "po_delayed_pct": 17.79,
 "po_avg_delay_days_when_delayed": 11.7,
 "supplier_capacity_utilisation_pct": 10.47,
 "demand_spike_scenarios": 926
}
```

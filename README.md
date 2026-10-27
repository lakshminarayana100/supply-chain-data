# Supply-chain shortage data generator

A deterministic synthetic-data generator, validator and test-suite for a **demand vs. supply shortage-prioritisation**
workflow: forecast demand is matched against on-hand stock, inbound purchase orders, production plans, supplier capacity
and lead times; projected balances are computed week by week; shortages are detected, explained and given mitigation
options with cost / service trade-offs.

* Pure Python (pandas + numpy). No ML, no external data, no network.
* One generator, three scales (`tiny` for tests, `starter`, `full` = 3,000 SKUs / 50 locations / 52 weeks / 500 suppliers / 10,000 POs).
* Fixed seed `20261022`; output is byte-identical across runs and processes.
* Ground truth is written to a **separate** file and never appears in an input table.

## Quick start

```bash
pip install -r requirements.txt
python generate.py --scale starter --seed 20261022 --out output/starter   # ~1 s
python validate.py --data output/starter                                  # 168 checks
python -m pytest -q                                                       # 12 tests
python reproduce.py --scale starter                                       # same seed twice -> same checksums
python generate.py --scale full --out output/full && python validate.py --data output/full   # ~6 s + ~6 s
python export_sql.py --data output/starter                                # SQLite with PK/FK/CHECK constraints
```
Tested with Python 3.12, pandas 3.0, numpy 2.4.

## What is in the repo

| Path | Purpose |
|---|---|
| `schema.py` | Single source of truth: tables, PK/FK, enums, validation rules. Generates the data dictionary and `schema.sql`. |
| `generate.py` | The generator (`--scale`, `--seed`, `--out`). |
| `validate.py` | Integrity checks, anomaly detectors, ground-truth scoring, metrics. |
| `reproduce.py` | Regenerates twice with the same seed and compares row counts + SHA-256. |
| `export_sql.py` | Loads CSVs into SQLite using `schema.sql`; can dump a plain `seed.sql`. |
| `test_pipeline.py` | pytest suite (12 positive and negative tests). |
| `DATA_DICTIONARY.md` | Field-level dictionary (type, required, allowed values, unit, uniqueness, rule). |
| `WALKTHROUGH.md` | Design decisions, assumptions, how each rule is implemented. |
| `SAMPLE_starter_*` | Sample outputs from the starter run (shortages, mitigation options, ground truth, validation summary). Run the generator to get the complete datasets. |
| `SAMPLE_*_full.*` | Validation summary, metrics, manifest (checksums) and reproducibility report of the full-scale run. |
| `PROMPTS.md` | Prompt history for the AI tool used. |

## Data model (18 tables)

```
sku ──< lead_time >── supplier ──< supplier_capacity
 │  \                      │
 │   sku_substitute (N:M)  └──< purchase_order ──< po_event (append-only history)
 │   bom (N:M, make→RAW)          ▲
 │                                │ (sku, location) must exist in inventory
location ──< inventory ──< forecast_demand        production_plan ──< production_component_requirement
 │              │                                  ▲        (PLANT only, capacity: production_capacity)
 │              └──< projected_balance (derived) ──┘
 └──< production_capacity          shortage ──< mitigation_option
```
Cardinalities, PKs and FKs are listed per table in `DATA_DICTIONARY.md`. IDs: `SKU-000001`, `LOC-001`, `SUP-0001`,
`DEM-<sku>-<loc>-2026W01`, `PO-2026-000001`, `PP-2026-000001`, `SHORT-2026-000001`, `MIT-<shortage-id>-01`.

## How the business logic works (all derived values come from source records)

1. **Master data** first, then demand (seasonal Poisson, ~4% of SKU-locations get a 2-4x spike), then opening inventory
   (a few SKU-locations start with thin cover so early shortages exist).
2. **Supply**: make SKUs at plants get a `production_plan` (limited by weekly plant capacity, BOM exploded into component
   requirements); everything else gets purchase orders sized to the projected deficit, limited by supplier weekly capacity,
   MOQ and lead time (an order cannot be placed before the plan-run date 2025-12-01). Delay probability depends on supplier
   reliability. Each PO has an append-only `po_event` history (PLANNED → CONFIRMED → SHIPPED → DELAYED, or CANCELLED).
3. **Projected balance** per SKU-location-week: `closing = opening + PO receipts (expected arrival) + production − forecast`.
4. **Shortage** = an episode of negative closing balance. Root cause is found by *single-factor counterfactuals*
   (remove transport delay / supplier cut / plant cut / demand spike / cancellations and see whether the shortage
   disappears); otherwise `LEAD_TIME_GAP`, `NO_INBOUND_PLANNED` or `INSUFFICIENT_SUPPLY`.
   Each shortage records the lead time used, the latest order date, whether the ordering window is still open and a priority score.
5. **Mitigation options** per shortage: alternative supplier (respects lead time, MOQ, remaining capacity), expedite an
   existing PO (max 50% lead-time compression), approved & effective substitute with surplus, production boost on spare line
   capacity. Each carries cost, recovery week and service level; one is flagged `recommended`.

## Labelled edge cases

Injected on top of valid baseline data and listed in `ground_truth.csv/json` (`label_kind = ANOMALY`):

| issue_type | What is injected | Detector (uses input tables only) |
|---|---|---|
| `INBOUND_COUNTED_TWICE` | exact duplicate PO line with a new PO id | duplicate natural key |
| `SUBSTITUTE_NOT_APPROVED` | mitigation using a PENDING/REJECTED substitution | join to `sku_substitute` |
| `SUPPLIER_CAPACITY_EXCEEDED` | PO inflated so supplier-week load > capacity | load vs `supplier_capacity` |
| `SHORTAGE_WITHOUT_LEAD_TIME` | shortage row with lead time 0 | recompute from `lead_time` |
| `UOM_MISMATCH` | PO ordered in another unit, stored without conversion | `qty_base` vs `uom_conversion` |

`label_kind = SCENARIO` rows (demand spikes) document legitimate events. `validate.py` scores each detector against the
ground truth: precision and recall are 1.0 for all five. Everything derived (balance, shortages, mitigations) is computed
*from the delivered, anomaly-containing tables*, so anomalies have realistic downstream effects.

## Validation and results

`python validate.py` runs 168 checks (PK uniqueness, FK integrity, required fields, enums, ID formats, date ordering,
arithmetic reconciliation, PO lifecycle transitions, mitigation policy, no label leakage, detector scoring). Latest results:
`SAMPLE_validation_summary_full.md`, `SAMPLE_metrics_full.json`, `SAMPLE_starter_validation_summary.md`.
Full scale: 168/168 passed; see metrics for shortage rate, cause mix, fill rate, option cost/service trade-offs.

## Reproducibility

`python reproduce.py` regenerates with the same seed twice and compares row counts and SHA-256 of every file
(`SAMPLE_reproducibility_report_full.json`: identical). A different seed changes the data. No timestamps are written, and
no data depends on dict/set ordering or hash seed (checked with different `PYTHONHASHSEED` values).

## Assumptions and limitations

* **Sparse SKU-location matrix**: each SKU is stocked at 8 of the 50 locations at full scale (24,000 pairs × 52 weeks =
  1.25M demand rows) instead of all 150,000 combinations.
* The full dataset has 10,000 baseline POs plus 50 injected duplicate lines (10,050 rows).
* Supplier capacity is counted in the week of the *promised* date; cancelled POs do not use capacity.
* PO status is a snapshot of the latest lifecycle state; event dates are scheduled dates in the simulated calendar.
* Shortages are backlog-based (negative balance carries forward); `approx_fill_rate_pct` is an approximation.
* Mitigation options are alternatives, not a combined plan (they may draw on the same remaining capacity).
* Make SKUs are produced, not bought, at plants; costs are simple percentage premiums chosen for plausibility, not calibrated.
* **Provenance**: 100% synthetic, no external datasets, no personal or confidential data.

## AI usage disclosure

This project was built with Claude (Anthropic) as an AI coding assistant; the full prompt history is in `PROMPTS.md`.
AI accelerated nearly everything (schema, generator, validator, tests, documentation) and I relied heavily on it for the
initial implementation.

> **TODO (author): replace this paragraph with what you personally reviewed, changed and validated**
> I built this with Claude (Anthropic) as an AI assistant; prompts are in PROMPTS.md. AI wrote most of the initial code. I ran the generator, validator and tests on my machine, read WALKTHROUGH.md, and went through generate.py and validate.py to understand the pipeline.
> 
> generator and validator, read `WALKTHROUGH.md`, changed parameters, extended a test). Do not leave it as is.

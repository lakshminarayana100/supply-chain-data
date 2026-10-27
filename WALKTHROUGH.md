# Walkthrough: problem, assumptions, key decisions

## Problem as understood
Build a reproducible synthetic dataset and tooling for a shortage-prioritisation workflow: which SKU-locations will run
short, why, how urgent, and what could be done about it, including deliberately broken records that a data-quality
process should catch.

## Key decisions and trade-offs
| Decision | Why | Trade-off |
|---|---|---|
| `schema.py` drives docs, DDL and validation | documentation and checks cannot drift | slightly more abstract code |
| Sparse SKU-location pairs (8 of 50) | keeps full scale to 1.25M rows, still 3,000 SKUs × 50 locations × 52 weeks | not a dense matrix |
| Vectorised numpy for demand/balance, loops only for PO placement | full scale in ~6 s | PO placement is sequential because capacity is shared |
| POs sized to deficits, then limited by capacity | shortages arise from rules, not random labels | some shortages are "insufficient supply" catch-alls |
| Root cause via counterfactuals | explainable, deterministic cause per shortage | one factor at a time; combined causes fall to a generic code |
| Anomalies injected, then everything derived from the delivered data | realistic downstream effect; reconciliation still passes | the "true" balance is only in the ground truth text |
| Detectors in `validate.py` use only input tables | proves anomalies are findable and no label leakage | detectors are rule-based, not learned |
| Separate `ground_truth.csv/json` | requirement: never leak labels | none |

## Reading the code (suggested order)
1. `schema.py` (what exists) → 2. `generate.py::build` (the pipeline order) → 3. `make_demand`, `generate_pos`,
`build_shortages`, `build_mitigations` (the logic) → 4. `inject_*` (edge cases) → 5. `validate.py::detect` and `domain_checks`.

## Things worth being able to explain
* Why `closing = opening + receipts + production − forecast` and how W01 opening equals `inventory.on_hand_qty`.
* How a PO's promised date (`order_date + lead_time`) differs from expected arrival (`+ transport delay`).
* How the counterfactual cause attribution works and why `LEAD_TIME_GAP` exists.
* How each of the five edge cases is injected, labelled and detected.
* Why the same seed gives identical output (single `numpy.random.Generator`, fixed call order, no hash-order dependence).
* Limitations listed in the README.

"""End-to-end tests on the 'tiny' scale (same generator code path as 'full')."""
import json
import os
import re
import shutil
import tempfile
from functools import lru_cache

import numpy as np
import pandas as pd

import generate
import schema
import validate

SEED = 20261022


@lru_cache(maxsize=None)
def dataset(seed=SEED):
    out = tempfile.mkdtemp(prefix=f"sc_test_{seed}_")
    manifest = generate.build("tiny", seed, out, verbose=False)
    return out, manifest


def tables():
    out, _ = dataset()
    return {n: pd.read_csv(os.path.join(out, f"{n}.csv")) for n in schema.TABLE_ORDER}


# ---------------------------------------------------------------- acceptance / integrity
def test_full_validation_suite_passes():
    out, _ = dataset()
    result = validate.run(out, write=False)
    failed = [c for c in result["integrity"] + result["detectors"] if c.get("status") != "PASS"]
    assert not failed, failed
    assert result["totals"]["checks"] >= 100


def test_projected_balance_reconciles_week_by_week_independently():
    """Re-derive the balance with plain numpy from raw tables (not using validate.py)."""
    t = tables()
    inv, fd, po, pp, pb = t["inventory"], t["forecast_demand"], t["purchase_order"], t["production_plan"], t["projected_balance"]
    row = inv.iloc[len(inv) // 2]
    sku, loc = row.sku_id, row.location_id
    demand = fd[(fd.sku_id == sku) & (fd.location_id == loc)].sort_values("week").forecast_qty.to_numpy()
    assert len(demand) == 52
    recv = np.zeros(52, dtype=int)
    for r in po[(po.sku_id == sku) & (po.location_id == loc) & (po.status != "CANCELLED")].itertuples():
        w = (pd.Timestamp(r.expected_arrival_date) - pd.Timestamp(generate.WEEK1_START)).days // 7
        if 0 <= w < 52:
            recv[w] += r.qty_base
    prod = np.zeros(52, dtype=int)
    for r in pp[(pp.sku_id == sku) & (pp.location_id == loc)].itertuples():
        prod[int(r.week[-2:]) - 1] += r.planned_qty
    expected = row.on_hand_qty + np.cumsum(recv + prod - demand)
    got = pb[(pb.sku_id == sku) & (pb.location_id == loc)].sort_values("week").closing_qty.to_numpy()
    assert (expected == got).all()


def test_shortages_have_cause_lead_time_and_valid_options():
    t = tables()
    sh, mit = t["shortage"], t["mitigation_option"]
    assert len(sh) > 0
    assert sh.cause_code.isin(schema.CAUSES).all() and sh.cause_detail.str.len().gt(10).all()
    rec = mit[mit.recommended == 1]
    assert rec.shortage_id.is_unique
    for typ in ("ALT_SUPPLIER", "EXPEDITE_PO"):           # trade-offs are exposed: cost AND service
        sub = mit[mit.option_type == typ]
        if len(sub):
            assert (sub.extra_cost >= 0).all() and sub.service_level_pct.between(0, 100).all()


# ---------------------------------------------------------------- IDs and joins
def test_id_conventions_and_zero_padded_counters():
    t = tables()
    assert t["sku"].sku_id.iloc[0] == "SKU-000001"
    assert t["purchase_order"].po_id.iloc[0] == "PO-2026-000001"
    assert t["shortage"].shortage_id.iloc[0] == "SHORT-2026-000001"
    assert t["mitigation_option"].mitigation_id.iloc[0].startswith("MIT-SHORT-2026-000001-0")
    d = t["forecast_demand"].iloc[0]
    assert d.demand_id == f"DEM-{d.sku_id}-{d.location_id}-2026W01"
    nums = t["purchase_order"].po_id.str[-6:].astype(int).sort_values().to_numpy()
    assert (nums == np.arange(1, len(nums) + 1)).all()           # contiguous, no gaps / reuse


def test_every_foreign_key_resolves():
    t = tables()
    for name in schema.TABLE_ORDER:
        for cols, ref, rcols in schema.TABLES[name]["fks"]:
            child = t[name][list(cols)].dropna().drop_duplicates()
            parent = t[ref][list(rcols)].drop_duplicates()
            m = child.merge(parent, left_on=list(cols), right_on=list(rcols), how="left", indicator=True)
            assert (m["_merge"] == "both").all(), (name, cols, ref)


# ---------------------------------------------------------------- ground truth
def test_ground_truth_is_separate_and_covers_all_edge_cases():
    out, _ = dataset()
    gt = pd.read_csv(os.path.join(out, "ground_truth.csv"))
    assert os.path.exists(os.path.join(out, "ground_truth.json"))
    expected = {"INBOUND_COUNTED_TWICE", "SUBSTITUTE_NOT_APPROVED", "SUPPLIER_CAPACITY_EXCEEDED",
                "SHORTAGE_WITHOUT_LEAD_TIME", "UOM_MISMATCH"}
    assert expected <= set(gt[gt.label_kind == "ANOMALY"].issue_type)
    for name in schema.TABLE_ORDER:                              # no label leakage into inputs
        cols = pd.read_csv(os.path.join(out, f"{name}.csv"), nrows=0).columns
        assert not {"issue_type", "label_kind", "gt_id"} & set(cols)
    t = tables()
    po_ids, sh_ids, mit_ids = set(t["purchase_order"].po_id), set(t["shortage"].shortage_id), set(t["mitigation_option"].mitigation_id)
    for r in gt[gt.label_kind == "ANOMALY"].itertuples():         # every label points at a real record
        assert r.entity_id in {"purchase_order": po_ids, "shortage": sh_ids, "mitigation_option": mit_ids}[r.entity]


def test_detectors_find_exactly_the_injected_anomalies():
    out, _ = dataset()
    result = validate.run(out, write=False)
    assert len(result["detectors"]) == 5
    for d in result["detectors"]:
        assert d["injected"] > 0 and d["false_positive"] == 0 and d["false_negative"] == 0, d


# ---------------------------------------------------------------- reproducibility / parameterisation
def test_same_seed_is_byte_identical_and_other_seed_differs():
    _, m1 = dataset()
    out2 = tempfile.mkdtemp(prefix="sc_test_again_")
    m2 = generate.build("tiny", SEED, out2, verbose=False)
    shutil.rmtree(out2, ignore_errors=True)
    assert m1["sha256"] == m2["sha256"] and m1["row_counts"] == m2["row_counts"]
    _, m3 = dataset(SEED + 1)
    assert m3["sha256"]["forecast_demand.csv"] != m1["sha256"]["forecast_demand.csv"]


def test_scales_share_one_generator_and_full_matches_required_volume():
    full = generate.SCALES["full"]
    assert (full["skus"], full["locations"], full["suppliers"], full["pos"]) == (3000, 50, 500, 10000)
    assert generate.WEEKS == 52
    t = tables()
    tiny = generate.SCALES["tiny"]
    assert len(t["sku"]) == tiny["skus"] and len(t["supplier"]) == tiny["suppliers"]
    assert len(t["forecast_demand"]) == tiny["skus"] * tiny["locs_per_sku"] * 52


# ---------------------------------------------------------------- negative tests: the validator must catch corruption
def _corrupted(mutator):
    out, _ = dataset()
    tmp = tempfile.mkdtemp(prefix="sc_corrupt_")
    for fn in os.listdir(out):
        shutil.copy(os.path.join(out, fn), tmp)
    mutator(tmp)
    try:
        return validate.run(tmp, write=False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_validator_catches_broken_balance_arithmetic():
    def mutate(d):
        pb = pd.read_csv(f"{d}/projected_balance.csv")
        pb.loc[10, "closing_qty"] += 7
        pb.to_csv(f"{d}/projected_balance.csv", index=False)
    r = _corrupted(mutate)
    assert not r["passed"]
    assert any(c["status"] == "FAIL" and "closing ==" in c["check"] for c in r["integrity"])


def test_validator_catches_duplicate_primary_key_and_orphan_fk():
    def mutate(d):
        po = pd.read_csv(f"{d}/purchase_order.csv")
        po.loc[1, "po_id"] = po.loc[0, "po_id"]
        po.loc[2, "supplier_id"] = "SUP-9999"
        po.to_csv(f"{d}/purchase_order.csv", index=False)
    r = _corrupted(mutate)
    failed = " | ".join(c["check"] for c in r["integrity"] if c["status"] == "FAIL")
    assert "purchase_order: primary key unique" in failed and "FK (supplier_id)" in failed


def test_validator_catches_illegal_po_lifecycle_transition():
    def mutate(d):
        ev = pd.read_csv(f"{d}/po_event.csv")
        i = ev.index[ev.event_type == "CONFIRMED"][0]
        ev.loc[i, "event_type"] = "DELAYED"          # PLANNED -> DELAYED is not allowed
        ev.to_csv(f"{d}/po_event.csv", index=False)
    r = _corrupted(mutate)
    assert any(c["status"] == "FAIL" and "lifecycle" in c["check"] for c in r["integrity"])

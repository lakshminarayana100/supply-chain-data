#!/usr/bin/env python3
"""Synthetic supply-chain shortage data generator.

Pipeline (every derived value is computed from source records, never drawn independently):

  1. master data      : sku, location, supplier, uom_conversion, sku_substitute, bom, lead_time,
                        supplier_capacity, production_capacity
  2. demand/inventory : forecast_demand (52 weeks, seasonality + labelled spikes), inventory (opening on-hand)
  3. supply           : production_plan (make SKUs at plants), purchase_order + po_event (event history)
  4. edge cases       : labelled anomalies injected into purchase orders (duplicates, UoM, capacity)
  5. derived          : projected_balance, shortage (+ counterfactual root cause), mitigation_option
  6. edge cases       : labelled anomalies injected into shortage / mitigation rows
  7. ground truth     : ground_truth.csv/json (kept out of every input table)

Usage:  python generate.py --scale starter --seed 20261022 --out output
"""
import argparse
import hashlib
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import pandas as pd

import schema

GENERATOR_VERSION = "1.0.0"
YEAR = 2026
WEEKS = 52
WEEK1_START = date(2025, 12, 29)      # Monday of ISO week 2026-W01
PLAN_RUN_DATE = date(2025, 12, 1)     # earliest date any order can be placed / mitigation ordered
SNAPSHOT_DATE = WEEK1_START           # opening inventory snapshot
MOQS = [1, 10, 25, 50]
UOM_FACTORS = {("EA", "EA"): 1.0, ("BOX", "BOX"): 1.0, ("KG", "KG"): 1.0, ("LB", "LB"): 1.0,
               ("BOX", "EA"): 12.0, ("EA", "BOX"): 1.0 / 12.0,
               ("LB", "KG"): 0.45359237, ("KG", "LB"): 1.0 / 0.45359237}
ALT_UOM = {"EA": "BOX", "BOX": "EA", "KG": "LB"}   # wrong-unit scenario per SKU base unit

SCALES = {   # same generator, different scale
    "tiny":    dict(skus=60,   locations=6,  suppliers=12,  pos=150,   locs_per_sku=3),
    "starter": dict(skus=300,  locations=12, suppliers=60,  pos=900,   locs_per_sku=5),
    "full":    dict(skus=3000, locations=50, suppliers=500, pos=10000, locs_per_sku=8),
}


# ----------------------------------------------------------------------------- helpers
def wk_label(w):
    return f"{YEAR}W{w:02d}"


def wk_start(w):
    return WEEK1_START + timedelta(days=7 * (int(w) - 1))


def week_of(d):
    return (d - WEEK1_START).days // 7 + 1


def wnum(label):
    return int(label[-2:])


def iso(d):
    return None if d is None else d.isoformat()


def uom_factor(frm, to):
    return UOM_FACTORS[(frm, to)]


# ----------------------------------------------------------------------------- master data
def make_skus(rng, n):
    category = rng.choice(schema.CATEGORIES, n, p=[.3, .3, .2, .2])
    return pd.DataFrame({
        "sku_id": [f"SKU-{i:06d}" for i in range(1, n + 1)],
        "sku_name": [f"Item {i:06d}" for i in range(1, n + 1)],
        "category": category,
        "uom": rng.choice(schema.SKU_UOMS, n, p=[.7, .2, .1]),
        "unit_cost": np.round(np.maximum(0.5, rng.lognormal(3.0, 0.8, n)), 2),
        "is_make": ((rng.random(n) < 0.3) & (category != "RAW")).astype(int),
    })


def make_locations(rng, n):
    types = rng.choice(schema.LOC_TYPES, n, p=[.2, .3, .5])
    plants = np.flatnonzero(types == "PLANT")
    for i in range(max(0, 2 - len(plants))):      # guarantee >= 2 plants
        types[i] = "PLANT"
    return pd.DataFrame({
        "location_id": [f"LOC-{i:03d}" for i in range(1, n + 1)],
        "location_name": [f"Site {i:03d}" for i in range(1, n + 1)],
        "location_type": types,
        "region": rng.choice(schema.REGIONS, n),
    })


def make_suppliers(rng, n):
    return pd.DataFrame({
        "supplier_id": [f"SUP-{i:04d}" for i in range(1, n + 1)],
        "supplier_name": [f"Supplier {i:04d}" for i in range(1, n + 1)],
        "region": rng.choice(schema.SUPPLIER_REGIONS, n),
        "reliability": np.round(rng.beta(8, 2, n), 3),
        "is_constrained": (rng.random(n) < 0.15).astype(int),
    })


def make_uom_conversion():
    return pd.DataFrame([(a, b, f) for (a, b), f in sorted(UOM_FACTORS.items())],
                        columns=["from_uom", "to_uom", "factor"])


def make_substitutes(rng, skus):
    rows = []
    for _cat, grp in skus.groupby("category", sort=True):
        ids = grp.sku_id.to_numpy(dtype=object)
        if len(ids) < 3:
            continue
        for src in rng.choice(ids, max(1, len(ids) // 8), replace=False):
            pool = ids[ids != src]
            n_sub = int(rng.integers(1, 3))
            for sub in rng.choice(pool, min(n_sub, len(pool)), replace=False):
                status = str(rng.choice(schema.APPROVAL, p=[.65, .2, .15]))
                eff_to = None
                if status == "APPROVED" and rng.random() < 0.2:      # boundary: approval expires mid-year
                    eff_to = str(rng.choice(["2026-03-31", "2026-06-30", "2026-09-30"]))
                rows.append((src, str(sub), status, "2025-01-01", eff_to))
    return pd.DataFrame(rows, columns=columns_of("sku_substitute"))


def columns_of(t):
    return schema.columns(t)


def make_bom(rng, skus):
    raw = skus.sku_id[skus.category == "RAW"].to_numpy(dtype=object)
    rows = []
    for sid in skus.sku_id[skus.is_make == 1]:
        for c in rng.choice(raw, min(len(raw), int(rng.integers(2, 4))), replace=False):
            rows.append((sid, str(c), int(rng.integers(1, 5))))
    return pd.DataFrame(rows, columns=columns_of("bom"))


def make_lead_times(rng, skus, suppliers):
    sup = suppliers.supplier_id.to_numpy(dtype=object)
    rows = []
    for sid in skus.sku_id:
        for s in rng.choice(sup, min(len(sup), int(rng.integers(1, 4))), replace=False):
            rows.append((sid, str(s), int(rng.integers(7, 61)), int(rng.choice(MOQS)), "2025-01-01", None))
    return pd.DataFrame(rows, columns=columns_of("lead_time"))


def weekly_table(ids, id_col, base, rng, jitter=(0.8, 1.2), floor=10):
    n = len(ids)
    cap = np.maximum(floor, np.round(base[:, None] * rng.uniform(*jitter, (n, WEEKS)))).astype(int)
    weeks = np.arange(1, WEEKS + 1)
    return pd.DataFrame({
        id_col: np.repeat(np.asarray(ids, dtype=object), WEEKS),
        "week": np.tile([wk_label(w) for w in weeks], n),
        "week_start": np.tile([iso(wk_start(w)) for w in weeks], n),
        "capacity_units": cap.ravel(),
    })


def make_supplier_capacity(rng, suppliers):
    base = rng.integers(150, 1501, len(suppliers)) * np.where(suppliers.is_constrained == 1, 0.35, 1.0)
    return weekly_table(suppliers.supplier_id.tolist(), "supplier_id", base, rng)


def make_production_capacity(rng, locations):
    plants = locations.location_id[locations.location_type == "PLANT"].tolist()
    base = rng.integers(300, 1201, len(plants)).astype(float)
    return weekly_table(plants, "location_id", base, rng, jitter=(0.85, 1.15), floor=1)


# ----------------------------------------------------------------------------- demand / inventory
def make_pairs(rng, skus, locations, k):
    n_loc = len(locations)
    plant_idx = np.flatnonzero(locations.location_type.to_numpy() == "PLANT")
    rows = []
    for i, make in enumerate(skus.is_make.to_numpy()):
        if make:                                   # make SKUs are always present at >= 2 plants
            pl = rng.choice(plant_idx, min(2, len(plant_idx)), replace=False)
            pool = np.setdiff1d(np.arange(n_loc), pl)
            chosen = np.concatenate([pl, rng.choice(pool, k - len(pl), replace=False)])
        else:
            chosen = rng.choice(n_loc, k, replace=False)
        for j in np.sort(chosen):
            rows.append((i, int(j)))
    pairs = pd.DataFrame(rows, columns=["sku_i", "loc_i"])
    pairs["sku_id"] = skus.sku_id.to_numpy(dtype=object)[pairs.sku_i]
    pairs["location_id"] = locations.location_id.to_numpy(dtype=object)[pairs.loc_i]
    return pairs


def make_demand(rng, skus, pairs):
    P = len(pairs)
    weeks = np.arange(1, WEEKS + 1)
    cat_phase = {c: i * 6 for i, c in enumerate(schema.CATEGORIES)}
    phase = np.array([cat_phase[c] for c in skus.category.to_numpy()[pairs.sku_i]])
    lam0 = rng.lognormal(3.0, 0.7, P)                                   # mean weekly demand
    season = 1 + 0.2 * np.sin(2 * np.pi * (weeks[None, :] + phase[:, None]) / WEEKS)
    base = rng.poisson(lam0[:, None] * season).astype(np.int64)         # baseline forecast (no spikes)
    D = base.copy()
    spikes = []
    for p in np.flatnonzero(rng.random(P) < 0.04):                      # ~4% of pairs get a demand spike
        s = int(rng.integers(0, WEEKS - 3))
        length = int(rng.integers(1, 4))
        mult = float(rng.uniform(2, 4))
        D[p, s:s + length] = np.round(base[p, s:s + length] * mult)
        spikes.append((int(p), s + 1, length, round(mult, 2)))
    return lam0, base, D, spikes


def demand_table(pairs, skus, D):
    P = len(pairs)
    sku = np.repeat(pairs.sku_id.to_numpy(dtype=object), WEEKS)
    loc = np.repeat(pairs.location_id.to_numpy(dtype=object), WEEKS)
    labels = np.tile([wk_label(w) for w in range(1, WEEKS + 1)], P)
    return pd.DataFrame({
        "demand_id": pd.Series(["DEM-"] * (P * WEEKS), dtype=object) + sku + "-" + loc + "-" + labels,
        "sku_id": sku, "location_id": loc, "week": labels,
        "week_start": np.tile([iso(wk_start(w)) for w in range(1, WEEKS + 1)], P),
        "forecast_qty": D.ravel(),
    })


def closing_matrix(O, S, D):
    return O[:, None] + np.cumsum(S - D, axis=1)


# ----------------------------------------------------------------------------- production
def make_production(rng, pairs, skus, locations, bom, prod_cap, deficit_tot, first_week, is_plant_make):
    cap_rem = {(r.location_id, wnum(r.week)): int(r.capacity_units) for r in prod_cap.itertuples()}
    rows, nocap = [], []
    cand = np.flatnonzero(is_plant_make & (deficit_tot > 0))
    for p in rng.permutation(cand):
        loc = pairs.location_id.iat[p]
        need = int(math.ceil(deficit_tot[p] * rng.uniform(0.9, 1.1)))
        n_chunks = int(rng.integers(1, 4))
        chunk = int(math.ceil(need / n_chunks))
        start_w = max(2, int(first_week[p]) + 1 - n_chunks)
        for c in range(n_chunks):
            w = start_w + c
            if w > WEEKS:
                break
            qty = min(chunk, cap_rem.get((loc, w), 0))
            if qty < chunk:
                nocap.append((int(p), w, chunk - qty))
            if qty <= 0:
                continue
            cap_rem[(loc, w)] -= qty
            rows.append((int(p), pairs.sku_id.iat[p], loc, w, qty))
    rows.sort(key=lambda r: (r[3], r[2], r[1]))
    plan = pd.DataFrame(rows, columns=["pidx", "sku_id", "location_id", "w", "planned_qty"])
    plan.insert(0, "plan_id", [f"PP-{YEAR}-{i:06d}" for i in range(1, len(plan) + 1)])
    plan["week"] = [wk_label(w) for w in plan.w]
    plan["week_start"] = [iso(wk_start(w)) for w in plan.w]
    plan["status"] = rng.choice(schema.PROD_STATUS, len(plan), p=[.6, .4])
    req = plan[["plan_id", "sku_id", "planned_qty"]].merge(
        bom.rename(columns={"parent_sku_id": "sku_id"}), on="sku_id", how="inner")
    req["required_qty"] = req.planned_qty * req.qty_per
    req = req[["plan_id", "component_sku_id", "required_qty"]]
    return plan, req, nocap


# ----------------------------------------------------------------------------- purchase orders
def generate_pos(rng, cfg, pairs, skus, suppliers, lead, sup_cap, lam0, tot, first_week, po_candidate):
    sku_uom = dict(zip(skus.sku_id, skus.uom))
    rel = dict(zip(suppliers.supplier_id, suppliers.reliability))
    lt = defaultdict(list)
    for r in lead.itertuples():
        lt[r.sku_id].append((r.supplier_id, int(r.lead_time_days), int(r.moq)))
    cap_rem = {(r.supplier_id, wnum(r.week)): int(r.capacity_units) for r in sup_cap.itertuples()}
    rows, nocap = [], []

    def try_place(p, desired, target):
        sku, loc = pairs.sku_id.iat[p], pairs.location_id.iat[p]
        opts = lt[sku]
        first_w = None
        for oi in rng.permutation(len(opts)):
            sup, lead_d, moq = opts[oi]
            order_date = max(PLAN_RUN_DATE, target - timedelta(days=lead_d))
            promised = order_date + timedelta(days=lead_d)
            w = week_of(promised)
            first_w = w if first_w is None else first_w
            if not 1 <= w <= WEEKS:
                continue
            rem = cap_rem.get((sup, w), 0)
            qty = min(max(desired, moq), rem)
            if qty < moq:
                continue
            cap_rem[(sup, w)] = rem - qty
            if qty < desired:
                nocap.append((p, w, desired - qty))
            return dict(pidx=int(p), sku_id=sku, supplier_id=sup, location_id=loc, order_date=order_date,
                        promised_date=promised, qty_base=int(qty))
        if first_w is not None and 1 <= first_w <= WEEKS:
            nocap.append((p, first_w, desired))
        return None

    # (a) planner covers projected deficits: PO sized to the deficit, targeted at the first short week
    cand = np.flatnonzero(po_candidate & (tot > 0))
    for p in rng.permutation(cand)[: cfg["pos"]]:
        w = int(first_week[p]) - int(rng.integers(0, 3))
        if rng.random() < 0.08:                      # late planner decision -> arrives after the need date
            w = int(first_week[p]) + int(rng.integers(1, 4))
        w = min(max(w, 1), WEEKS)
        target = wk_start(w) + timedelta(days=int(rng.integers(0, 5)))
        desired = int(math.ceil(tot[p] * rng.uniform(0.85, 1.15)))
        po = try_place(p, desired, target)
        if po:
            rows.append(po)
    # (b) routine replenishment on random SKU-locations until the PO count target is met
    elig = np.flatnonzero(po_candidate)
    attempts = 0
    while len(rows) < cfg["pos"] and attempts < cfg["pos"] * 10:
        attempts += 1
        p = int(rng.choice(elig))
        desired = max(1, int(math.ceil(lam0[p] * rng.uniform(2, 5))))
        target = wk_start(int(rng.integers(2, WEEKS - 3))) + timedelta(days=int(rng.integers(0, 5)))
        po = try_place(p, desired, target)
        if po:
            rows.append(po)

    # status / delay: derived from supplier reliability
    for r in rows:
        if rng.random() < 0.03:
            r["status"], r["delay"] = "CANCELLED", 0
        elif rng.random() < min(0.6, (1 - rel[r["supplier_id"]]) * 0.9):
            r["status"], r["delay"] = "DELAYED", int(rng.integers(2, 22))
        else:
            r["status"], r["delay"] = str(rng.choice(["PLANNED", "CONFIRMED", "SHIPPED"], p=[.25, .4, .35])), 0
    rows.sort(key=lambda r: (r["order_date"], r["sku_id"], r["location_id"], r["supplier_id"]))
    po = pd.DataFrame(rows)
    po.insert(0, "po_id", [f"PO-{YEAR}-{i:06d}" for i in range(1, len(po) + 1)])
    po["order_uom"] = po.sku_id.map(sku_uom)
    po["qty_ordered"] = po.qty_base
    po["expected_arrival_date"] = [r.promised_date + timedelta(days=int(r.delay)) for r in po.itertuples()]
    po = po.rename(columns={"delay": "transport_delay_days"})
    return po, nocap


# ----------------------------------------------------------------------------- injected PO anomalies
def inject_po_anomalies(rng, po, skus, sup_cap, lead, k, gt):
    cost = dict(zip(skus.sku_id, skus.unit_cost))
    uom = dict(zip(skus.sku_id, skus.uom))
    moq = {(r.sku_id, r.supplier_id): int(r.moq) for r in lead.itertuples()}
    cap = {(r.supplier_id, wnum(r.week)): int(r.capacity_units) for r in sup_cap.itertuples()}
    po = po.copy()
    po["pwk"] = [week_of(d) for d in po.promised_date]
    active = po.status != "CANCELLED"
    used = po[active].groupby(["supplier_id", "pwk"]).qty_base.sum().to_dict()
    rem = {key: cap[key] - used.get(key, 0) for key in cap}
    taken = set()
    order = [int(i) for i in rng.permutation(po.index[active].to_numpy())]
    new_rows = []

    # 1) inbound counted twice: an exact duplicate PO line with a new PO id (still within capacity)
    n = 0
    for i in order:
        if n >= k:
            break
        r = po.loc[i]
        key = (r.supplier_id, r.pwk)
        if i in taken or rem[key] < r.qty_base:
            continue
        rem[key] -= r.qty_base
        taken.add(i)
        new_id = f"PO-{YEAR}-{len(po) + len(new_rows) + 1:06d}"
        d = r.to_dict()
        d["po_id"] = new_id
        new_rows.append(d)
        gt.append(dict(label_kind="ANOMALY", issue_type="INBOUND_COUNTED_TWICE", entity="purchase_order",
                       entity_id=new_id, related_id=r.po_id,
                       detail=f"exact duplicate of {r.po_id} (qty_base {r.qty_base})",
                       expected_decision="exclude the duplicate inbound from projected balance"))
        n += 1

    # 2) units-of-measure mismatch: ordered in another unit, quantity stored without conversion
    n = 0
    for i in order:
        if n >= k:
            break
        r = po.loc[i]
        if i in taken or r.order_uom != uom[r.sku_id]:
            continue
        alt = ALT_UOM[r.order_uom]
        f_alt_to_base = uom_factor(alt, r.order_uom)
        q_ord = int(round(r.qty_base / f_alt_to_base))
        true_base = int(round(q_ord * f_alt_to_base))
        recorded = q_ord                                      # BUG being simulated: no conversion applied
        key = (r.supplier_id, r.pwk)
        if q_ord < 1 or true_base < 1 or recorded == true_base or rem[key] < recorded - r.qty_base:
            continue
        if true_base < moq[(r["sku_id"], r["supplier_id"])]:
            continue
        po.loc[i, "order_uom"] = alt
        po.loc[i, "qty_ordered"] = q_ord
        po.loc[i, "qty_base"] = recorded
        rem[key] -= recorded - r.qty_base
        taken.add(i)
        gt.append(dict(label_kind="ANOMALY", issue_type="UOM_MISMATCH", entity="purchase_order",
                       entity_id=r.po_id, related_id=r.sku_id,
                       detail=f"ordered {q_ord} {alt}; stored qty_base={recorded} but correct={true_base} {r.order_uom}",
                       expected_decision=f"convert with factor {f_alt_to_base:.6f}; correct qty_base={true_base}"))
        n += 1

    # 3) supplier capacity exceeded: inflate one PO so its supplier-week total passes capacity
    n = 0
    for i in order:
        if n >= k:
            break
        r = po.loc[i]
        key = (r.supplier_id, r.pwk)
        if i in taken or r.order_uom != uom[r.sku_id]:
            continue
        new_qty = int(r.qty_base + max(rem[key], 0) + max(1, math.ceil(0.25 * cap[key])))
        po.loc[i, "qty_ordered"] = new_qty
        po.loc[i, "qty_base"] = new_qty
        rem[key] -= new_qty - r.qty_base
        taken.add(i)
        gt.append(dict(label_kind="ANOMALY", issue_type="SUPPLIER_CAPACITY_EXCEEDED", entity="purchase_order",
                       entity_id=r.po_id, related_id=f"{r.supplier_id}|{wk_label(int(r.pwk))}",
                       detail=f"qty_base raised {r.qty_base}->{new_qty}; capacity {cap[key]}",
                       expected_decision="cap quantity at remaining supplier capacity or split across suppliers"))
        n += 1

    if new_rows:
        po = pd.concat([po, pd.DataFrame(new_rows)], ignore_index=True)
    po["po_value"] = np.round(po.qty_base * po.sku_id.map(cost), 2)
    return po.drop(columns=["pwk"])


def make_po_events(rng, po):
    rows = []
    for r in po.itertuples():
        d0 = r.order_date
        ev = [("PLANNED", d0)]
        d1 = d0
        if r.status in ("CONFIRMED", "SHIPPED", "DELAYED") or (r.status == "CANCELLED" and rng.random() < 0.5):
            d1 = d0 + timedelta(days=int(rng.integers(1, 4)))
            ev.append(("CONFIRMED", d1))
        if r.status in ("SHIPPED", "DELAYED"):
            d2 = min(max(d1 + timedelta(days=1), r.promised_date - timedelta(days=int(rng.integers(3, 8)))),
                     r.promised_date)
            ev.append(("SHIPPED", d2))
        if r.status == "DELAYED":
            ev.append(("DELAYED", r.promised_date))
        if r.status == "CANCELLED":
            ev.append(("CANCELLED", ev[-1][1] + timedelta(days=int(rng.integers(1, 6)))))
        for seq, (t, d) in enumerate(ev, 1):
            rows.append((r.po_id, seq, t, iso(d)))
    return pd.DataFrame(rows, columns=columns_of("po_event"))


# ----------------------------------------------------------------------------- supply matrices
def supply_matrix(P, p_idx, w_idx, qty):
    S = np.zeros((P, WEEKS + 2), dtype=np.int64)
    w = np.asarray(w_idx)
    ok = (w >= 1) & (w <= WEEKS)
    np.add.at(S, (np.asarray(p_idx)[ok], w[ok]), np.asarray(qty)[ok])
    return S[:, 1:WEEKS + 1]


def extra_matrix(P, extras):
    if not extras:
        return np.zeros((P, WEEKS), dtype=np.int64)
    p, w, q = zip(*extras)
    return supply_matrix(P, p, w, q)


# ----------------------------------------------------------------------------- shortages
def build_shortages(pairs, skus, O, C, S, S_nodelay, S_nosupcut, S_noprodcut, S_cancel, D, D0, po, lt_min):
    """Detect episodes in C and attribute a root cause by single-factor counterfactuals."""
    M = C < 0
    prev = np.zeros_like(M)
    prev[:, 1:] = M[:, :-1]
    cost = skus.unit_cost.to_numpy()[pairs.sku_i.to_numpy()]
    by_p = defaultdict(list)
    for r in po.itertuples():
        by_p[r.pidx].append(r)
    cf = {   # counterfactual closing balances, each removes exactly one factor
        "TRANSPORT_DELAY": closing_matrix(O, S_nodelay, D),
        "SUPPLIER_CAPACITY": closing_matrix(O, S_nosupcut, D),
        "PRODUCTION_CAPACITY": closing_matrix(O, S_noprodcut, D),
        "DEMAND_SPIKE": closing_matrix(O, S, D0),
        "PO_CANCELLED": closing_matrix(O, S_cancel, D),
    }
    supply_total = S
    out = []
    for p, w in np.argwhere(M & ~prev):
        e = w
        while e + 1 < WEEKS and M[p, e + 1]:
            e += 1
        peak = int(-C[p, w:e + 1].min())
        cause = None
        for name in ("TRANSPORT_DELAY", "SUPPLIER_CAPACITY", "PRODUCTION_CAPACITY", "DEMAND_SPIKE", "PO_CANCELLED"):
            if cf[name][p, w] >= 0:
                cause = name
                break
        if cause is None:
            if supply_total[p].sum() == 0:
                cause = "NO_INBOUND_PLANNED"
            elif e < WEEKS - 1:
                cause = "LEAD_TIME_GAP"
            else:
                cause = "INSUFFICIENT_SUPPLY"
        pos_p = by_p.get(int(p), [])
        if cause == "TRANSPORT_DELAY":
            late = [r for r in pos_p if r.status == "DELAYED"]
            detail = f"{len(late)} PO(s) arrived late, max {max(r.transport_delay_days for r in late)}d: " + \
                     ", ".join(r.po_id for r in late[:3])
        elif cause == "SUPPLIER_CAPACITY":
            detail = "order quantity was cut to remaining supplier capacity; uncovered quantity caused the shortage"
        elif cause == "PRODUCTION_CAPACITY":
            detail = "planned production was cut to remaining plant line capacity"
        elif cause == "DEMAND_SPIKE":
            detail = f"forecast spikes add {int((D[p, :w + 1] - D0[p, :w + 1]).sum())} units above baseline up to the first short week"
        elif cause == "PO_CANCELLED":
            detail = "cancelled PO(s): " + ", ".join(r.po_id for r in pos_p if r.status == "CANCELLED")[:120]
        elif cause == "NO_INBOUND_PLANNED":
            detail = "no purchase order or production plan exists for this SKU-location"
        elif cause == "LEAD_TIME_GAP":
            detail = f"supply recovers in {wk_label(e + 2)} but is needed in {wk_label(w + 1)} (lead time too long to react)"
        else:
            detail = "planned inbound does not cover cumulative demand within the horizon"
        out.append(dict(pidx=int(p), fwk=int(w) + 1, ewk=int(e) + 1, shortage_qty=peak, cause_code=cause,
                        cause_detail=detail))
    short = pd.DataFrame(out)
    if short.empty:
        return short
    short["sku_id"] = pairs.sku_id.to_numpy(dtype=object)[short.pidx]
    short["location_id"] = pairs.location_id.to_numpy(dtype=object)[short.pidx]
    short = short.sort_values(["fwk", "sku_id", "location_id"]).reset_index(drop=True)
    short.insert(0, "shortage_id", [f"SHORT-{YEAR}-{i:06d}" for i in range(1, len(short) + 1)])
    short["first_week"] = [wk_label(w) for w in short.fwk]
    short["need_date"] = [iso(wk_start(w)) for w in short.fwk]
    short["end_week"] = [wk_label(w) for w in short.ewk]
    short["weeks_affected"] = short.ewk - short.fwk + 1
    short["value_at_risk"] = np.round(short.shortage_qty * cost[short.pidx], 2)
    short["lead_time_days_used"] = short.sku_id.map(lt_min).astype(int)
    short["latest_order_date"] = [iso(wk_start(w) - timedelta(days=int(l)))
                                  for w, l in zip(short.fwk, short.lead_time_days_used)]
    short["ordering_window_open"] = [int(wk_start(w) - timedelta(days=int(l)) >= PLAN_RUN_DATE)
                                     for w, l in zip(short.fwk, short.lead_time_days_used)]
    short["priority_score"] = np.round(short.value_at_risk * (1 + 4.0 / short.fwk), 2)
    short["priority_rank"] = short.priority_score.rank(ascending=False, method="first").astype(int)
    return short




# ----------------------------------------------------------------------------- mitigations
def build_mitigations(rng, short, pairs, skus, lead, subs, po, sup_cap, plan, prod_cap, C, pair_index):
    sku_cost = dict(zip(skus.sku_id, skus.unit_cost))
    sku_make = dict(zip(skus.sku_id, skus.is_make))
    lt = defaultdict(list)
    for r in lead.itertuples():
        lt[r.sku_id].append((int(r.lead_time_days), r.supplier_id, int(r.moq)))
    cap = {(r.supplier_id, wnum(r.week)): int(r.capacity_units) for r in sup_cap.itertuples()}
    act = po[po.status != "CANCELLED"]
    used = {k: int(v) for k, v in
            act.assign(pwk=[week_of(d) for d in act.promised_date]).groupby(["supplier_id", "pwk"]).qty_base.sum().items()}
    sup_rem = {k: max(0, cap[k] - used.get(k, 0)) for k in cap}
    pcap = {(r.location_id, wnum(r.week)): int(r.capacity_units) for r in prod_cap.itertuples()}
    pused = plan.groupby(["location_id", "w"]).planned_qty.sum().to_dict() if len(plan) else {}
    approved = defaultdict(list)
    for r in subs[subs.approval_status == "APPROVED"].itertuples():
        approved[r.sku_id].append((r.substitute_sku_id, date.fromisoformat(r.effective_from),
                                   None if r.effective_to is None or pd.isna(r.effective_to)
                                   else date.fromisoformat(r.effective_to)))
    po_by_p = defaultdict(list)
    for r in act.itertuples():
        po_by_p[r.pidx].append(r)

    rows = []
    for s in short.itertuples():
        need, fw, p = int(s.shortage_qty), int(s.fwk), int(s.pidx)
        sku, loc, c = s.sku_id, s.location_id, sku_cost[s.sku_id]
        opts = []

        def add(typ, qty, rec_w, lead_d, cost_x, supplier=None, sub=None, src=None):
            qty = int(qty)
            if qty < 1 or not 1 <= rec_w <= WEEKS:
                return
            late = max(0, rec_w - fw)
            service = round(100 * min(1.0, qty / need) * max(0.0, 1 - 0.1 * late), 1)
            opts.append(dict(option_type=typ, supplier_id=supplier, substitute_sku_id=sub, source_po_id=src,
                             recovery_qty=qty, lead_time_days=int(lead_d), recovery_week=wk_label(rec_w),
                             extra_cost=round(cost_x, 2), cost_per_unit=round(cost_x / qty, 2),
                             service_level_pct=service, resolves_shortage=int(qty >= need and rec_w <= fw)))

        # ALT_SUPPLIER: order today at the plan run date; respects lead time, MOQ and remaining capacity
        alts = []
        for lead_d, sup, moq in sorted(lt[sku]):
            rec_w = week_of(PLAN_RUN_DATE + timedelta(days=lead_d))
            rem = sup_rem.get((sup, rec_w), 0)
            qty = min(max(need, moq), rem)
            if 1 <= rec_w <= WEEKS and qty >= moq:
                alts.append((rec_w, lead_d, sup, qty))
        for rec_w, lead_d, sup, qty in alts[:2]:
            add("ALT_SUPPLIER", qty, rec_w, lead_d, qty * c * 0.03 + 150, supplier=sup)

        # EXPEDITE_PO: compress an existing late PO by up to 50% of its lead time
        best = None
        for r in po_by_p.get(p, []):
            if week_of(r.expected_arrival_date) <= fw:
                continue
            lead_d = (r.promised_date - r.order_date).days
            new_arr = max(r.order_date + timedelta(days=math.ceil(0.5 * lead_d)), PLAN_RUN_DATE + timedelta(days=3))
            if new_arr < r.expected_arrival_date and (best is None or r.qty_base > best[0].qty_base):
                best = (r, new_arr)
        if best:
            r, new_arr = best
            add("EXPEDITE_PO", r.qty_base, week_of(new_arr), (new_arr - r.order_date).days,
                r.qty_base * c * 0.12 + 200, src=r.po_id)

        # SUBSTITUTE: approved + effective substitute with projected surplus at the same location
        need_date = wk_start(fw)
        for sub, eff_from, eff_to in approved.get(sku, []):
            q = pair_index.get((sub, loc))
            if q is None or eff_from > need_date or (eff_to is not None and eff_to < need_date):
                continue
            surplus = int(max(0, C[q, fw - 1:].min()))
            add("SUBSTITUTE", min(need, surplus), fw, 0, min(need, surplus) * (max(0.0, sku_cost[sub] - c) + 0.5), sub=sub)

        # PRODUCTION_BOOST: spare line capacity at the plant before the need week
        if sku_make[sku] and (loc, 2) in pcap and fw >= 2:
            got, last_w = 0, None
            for w in range(2, fw + 1):
                spare = max(0, pcap.get((loc, w), 0) - int(pused.get((loc, w), 0)))
                if spare and got < need:
                    got += min(spare, need - got)
                    last_w = w
            if got:
                add("PRODUCTION_BOOST", got, last_w, 0, got * c * 0.10 + 100)

        # recommended: resolving options first (cheapest); otherwise best service then cheapest
        rec_i = None
        if opts:
            res = [i for i, o in enumerate(opts) if o["resolves_shortage"]]
            pool = res if res else range(len(opts))
            key = (lambda i: (opts[i]["extra_cost"], i)) if res else (lambda i: (-opts[i]["service_level_pct"], opts[i]["extra_cost"], i))
            rec_i = min(pool, key=key)
        for n, o in enumerate(opts, 1):
            o.update(mitigation_id=f"MIT-{s.shortage_id}-{n:02d}", shortage_id=s.shortage_id,
                     recommended=int(n - 1 == rec_i))
            rows.append(o)
    mit = pd.DataFrame(rows, columns=columns_of("mitigation_option")) if rows else \
        pd.DataFrame(columns=columns_of("mitigation_option"))
    return mit


def shortage_status(short, mit):
    has_res = set(mit.shortage_id[mit.resolves_shortage == 1])
    has_any = set(mit.shortage_id)
    return ["MITIGATION_PROPOSED" if s in has_res else ("OPEN" if s in has_any else "ESCALATED")
            for s in short.shortage_id]


# ----------------------------------------------------------------------------- injected shortage / mitigation anomalies
def inject_shortage_mitigation_anomalies(rng, short, mit, subs, skus, k, gt):
    short, mit, subs = short.copy(), mit.copy(), subs.copy()
    cost = dict(zip(skus.sku_id, skus.unit_cost))
    # 4) shortage calculated without lead time (prefer cases where the true ordering window is already closed)
    closed = [i for i in rng.permutation(short.index[short.ordering_window_open == 0].to_numpy())]
    opened = [i for i in rng.permutation(short.index[short.ordering_window_open == 1].to_numpy())]
    for i in (closed + opened)[:k]:
        r = short.loc[i]
        gt.append(dict(label_kind="ANOMALY", issue_type="SHORTAGE_WITHOUT_LEAD_TIME", entity="shortage",
                       entity_id=r.shortage_id, related_id=r.sku_id,
                       detail=f"lead_time_days_used recorded 0 (true {r.lead_time_days_used}); "
                              f"true latest_order_date {r.latest_order_date}, window_open={r.ordering_window_open}",
                       expected_decision=f"recompute with lead time {r.lead_time_days_used} days"))
        short.loc[i, "lead_time_days_used"] = 0
        short.loc[i, "latest_order_date"] = r.need_date
        short.loc[i, "ordering_window_open"] = 1
    # 5) substitute not approved: a SUBSTITUTE mitigation pointing at a PENDING/REJECTED substitution
    unapproved = {}
    for r in subs[subs.approval_status != "APPROVED"].itertuples():
        unapproved.setdefault(r.sku_id, []).append(r.substitute_sku_id)
    cand = [i for i in rng.permutation(short.index.to_numpy()) if short.sku_id[i] in unapproved]
    extra = [i for i in rng.permutation(short.index.to_numpy()) if short.sku_id[i] not in unapproved]
    new_sub_rows, rows, done = [], [], 0
    for i in cand + extra:
        if done >= k:
            break
        r = short.loc[i]
        if r.sku_id in unapproved:
            sub = unapproved[r.sku_id][0]
        else:                                           # create a PENDING substitution so the FK stays valid
            same_cat = skus[(skus.category == skus.category[skus.sku_id == r.sku_id].iat[0]) & (skus.sku_id != r.sku_id)]
            already = set(subs.substitute_sku_id[subs.sku_id == r.sku_id])
            same_cat = same_cat[~same_cat.sku_id.isin(already)]
            if same_cat.empty:
                continue
            sub = str(same_cat.sku_id.iloc[int(rng.integers(0, len(same_cat)))])
            new_sub_rows.append((r.sku_id, sub, "PENDING", "2025-01-01", None))
            unapproved[r.sku_id] = [sub]
        n = int((mit.shortage_id == r.shortage_id).sum()) + 1
        qty = int(r.shortage_qty)
        extra_cost = round(qty * (max(0.0, cost[sub] - cost[r.sku_id]) + 0.5), 2)
        mid = f"MIT-{r.shortage_id}-{n:02d}"
        rows.append(dict(mitigation_id=mid, shortage_id=r.shortage_id, option_type="SUBSTITUTE", supplier_id=None,
                         substitute_sku_id=sub, source_po_id=None, recovery_qty=qty, lead_time_days=0,
                         recovery_week=r.first_week, extra_cost=extra_cost, cost_per_unit=round(extra_cost / qty, 2),
                         service_level_pct=100.0, resolves_shortage=1, recommended=0))
        mit = pd.concat([mit, pd.DataFrame([rows[-1]])], ignore_index=True)
        gt.append(dict(label_kind="ANOMALY", issue_type="SUBSTITUTE_NOT_APPROVED", entity="mitigation_option",
                       entity_id=mid, related_id=f"{r.sku_id}->{sub}",
                       detail="substitution is not APPROVED in sku_substitute",
                       expected_decision="reject this option; only APPROVED, effective substitutes are allowed"))
        done += 1
    if new_sub_rows:
        subs = pd.concat([subs, pd.DataFrame(new_sub_rows, columns=subs.columns)], ignore_index=True)
    return short, mit, subs


# ----------------------------------------------------------------------------- output
def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_table(df, name, out, cols=None):
    cols = cols or columns_of(name)
    df = df[cols].copy()
    for c, spec in zip(cols, [f for f in schema.TABLES[name]["fields"]]):
        if spec[1] == "bool":
            df[c] = df[c].astype(int)
    df.to_csv(os.path.join(out, f"{name}.csv"), index=False, lineterminator="\n")


def build(scale, seed, out, verbose=True):
    cfg = SCALES[scale]
    rng = np.random.default_rng(seed)
    os.makedirs(out, exist_ok=True)
    log = (lambda *a: print(*a)) if verbose else (lambda *a: None)

    # 1. master data
    skus = make_skus(rng, cfg["skus"])
    locs = make_locations(rng, cfg["locations"])
    sups = make_suppliers(rng, cfg["suppliers"])
    uomc = make_uom_conversion()
    subs = make_substitutes(rng, skus)
    bom = make_bom(rng, skus)
    lead = make_lead_times(rng, skus, sups)
    sup_cap = make_supplier_capacity(rng, sups)
    prod_cap = make_production_capacity(rng, locs)

    # 2. demand + opening inventory
    pairs = make_pairs(rng, skus, locs, cfg["locs_per_sku"])
    P = len(pairs)
    lam0, D0, D, spikes = make_demand(rng, skus, pairs)
    demand = demand_table(pairs, skus, D)
    on_hand = np.floor(rng.uniform(0.65, 2.0, P) * D0.sum(axis=1)).astype(np.int64)
    thin = rng.random(P) < 0.06                      # ~6% start with only 1-7 weeks of cover -> early shortages
    cover = rng.integers(1, 8, P)
    thin_oh = np.floor(np.cumsum(D0, axis=1)[np.arange(P), cover - 1] * rng.uniform(0.8, 1.0, P)).astype(np.int64)
    on_hand = np.where(thin, thin_oh, on_hand)
    inventory = pd.DataFrame({
        "inventory_id": "INV-" + pairs.sku_id + "-" + pairs.location_id,
        "sku_id": pairs.sku_id, "location_id": pairs.location_id, "snapshot_date": iso(SNAPSHOT_DATE),
        "on_hand_qty": on_hand, "safety_stock_qty": np.ceil(lam0).astype(int)})

    # 3. supply: production for make SKUs at plants, purchase orders elsewhere
    C0 = closing_matrix(on_hand, np.zeros((P, WEEKS), dtype=np.int64), D)
    tot = np.maximum(0, -C0.min(axis=1))
    first_week = np.where((C0 < 0).any(axis=1), (C0 < 0).argmax(axis=1) + 1, 0)
    loc_type = locs.location_type.to_numpy()[pairs.loc_i.to_numpy()]
    is_plant_make = (skus.is_make.to_numpy()[pairs.sku_i.to_numpy()] == 1) & (loc_type == "PLANT")
    plan, req, nocap_prod = make_production(rng, pairs, skus, locs, bom, prod_cap, tot, first_week, is_plant_make)
    po, nocap_po = generate_pos(rng, cfg, pairs, skus, sups, lead, sup_cap, lam0, tot, first_week, ~is_plant_make)

    # 4. labelled PO anomalies
    gt = []
    k = max(5, round(0.005 * cfg["pos"]))
    po = inject_po_anomalies(rng, po, skus, sup_cap, lead, k, gt)
    events = make_po_events(rng, po)

    # 5. derived: projected balance, shortages, mitigations (all from the delivered tables)
    pair_index = {(s, l): i for i, (s, l) in enumerate(zip(pairs.sku_id, pairs.location_id))}
    po["pidx"] = [pair_index[(s, l)] for s, l in zip(po.sku_id, po.location_id)]
    active = po.status != "CANCELLED"
    pw = np.array([week_of(d) for d in po.promised_date])
    ew = np.array([week_of(d) for d in po.expected_arrival_date])
    S_po = supply_matrix(P, po.pidx[active], ew[active], po.qty_base[active])
    S_prod = supply_matrix(P, plan.pidx, plan.w, plan.planned_qty) if len(plan) else np.zeros((P, WEEKS), dtype=np.int64)
    S = S_po + S_prod
    C = closing_matrix(on_hand, S, D)
    S_a = supply_matrix(P, po.pidx[active], pw[active], po.qty_base[active]) + S_prod            # no transport delay
    S_b = S + extra_matrix(P, nocap_po)                                                        # no supplier cap cut
    S_c = S + extra_matrix(P, nocap_prod)                                                      # no production cap cut
    S_cancel = S + supply_matrix(P, po.pidx[~active], ew[~active], po.qty_base[~active])  # cancelled POs kept
    lt_min = lead.groupby("sku_id").lead_time_days.min().to_dict()
    short = build_shortages(pairs, skus, on_hand, C, S, S_a, S_b, S_c, S_cancel, D, D0, po, lt_min)
    if short.empty:
        raise RuntimeError("no shortages generated; adjust scale/parameters")
    mit = build_mitigations(rng, short, pairs, skus, lead, subs, po, sup_cap, plan, prod_cap, C, pair_index)
    short["status"] = shortage_status(short, mit)

    # 6. labelled shortage / mitigation anomalies
    k2 = max(3, round(0.02 * len(short)))
    short, mit, subs = inject_shortage_mitigation_anomalies(rng, short, mit, subs, skus, k2, gt)

    # 7. ground truth (separate file; never referenced by input tables)
    for p, start, length, mult in spikes:
        gt.append(dict(label_kind="SCENARIO", issue_type="DEMAND_SPIKE", entity="forecast_demand",
                       entity_id=f"DEM-{pairs.sku_id.iat[p]}-{pairs.location_id.iat[p]}-{wk_label(start)}",
                       related_id=f"{pairs.sku_id.iat[p]}|{pairs.location_id.iat[p]}",
                       detail=f"forecast x{mult} for {length} week(s) from {wk_label(start)}",
                       expected_decision="expect shortage risk; consider expedite or alternative supply"))
    gtdf = pd.DataFrame(gt)
    gtdf = gtdf.sort_values(["label_kind", "issue_type", "entity_id"]).reset_index(drop=True)
    gtdf.insert(0, "gt_id", [f"GT-{i:05d}" for i in range(1, len(gtdf) + 1)])

    # projected balance table
    opening = np.concatenate([on_hand[:, None], C[:, :-1]], axis=1)
    pb = pd.DataFrame({
        "sku_id": np.repeat(pairs.sku_id.to_numpy(dtype=object), WEEKS),
        "location_id": np.repeat(pairs.location_id.to_numpy(dtype=object), WEEKS),
        "week": np.tile([wk_label(w) for w in range(1, WEEKS + 1)], P),
        "opening_qty": opening.ravel(), "forecast_qty": D.ravel(), "po_receipts_qty": S_po.ravel(),
        "production_qty": S_prod.ravel(), "closing_qty": C.ravel()})

    # write everything
    tables = dict(sku=skus, location=locs, supplier=sups, uom_conversion=uomc, sku_substitute=subs, bom=bom,
                  lead_time=lead, supplier_capacity=sup_cap, production_capacity=prod_cap,
                  forecast_demand=demand, inventory=inventory, purchase_order=po, po_event=events,
                  production_plan=plan, production_component_requirement=req, projected_balance=pb,
                  shortage=short, mitigation_option=mit)
    for name in schema.TABLE_ORDER:
        write_table(tables[name], name, out)
    gtdf.to_csv(os.path.join(out, "ground_truth.csv"), index=False, lineterminator="\n")
    with open(os.path.join(out, "ground_truth.json"), "w") as f:
        json.dump(gtdf.to_dict(orient="records"), f, indent=1, default=str)

    files = sorted(fn for fn in os.listdir(out) if fn.endswith((".csv", ".json")) and fn != "manifest.json")
    manifest = dict(
        generator="generate.py", generator_version=GENERATOR_VERSION,
        command=f"python generate.py --scale {scale} --seed {seed}",
        seed=seed, scale=scale, parameters=cfg,
        provenance="100% synthetic data produced by this generator. No external or public datasets were used, "
                   "no personal or confidential data is included.",
        row_counts={fn[:-4]: int(sum(1 for _ in open(os.path.join(out, fn))) - 1) for fn in files if fn.endswith(".csv")},
        sha256={fn: sha256(os.path.join(out, fn)) for fn in files})
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    for n, c in manifest["row_counts"].items():
        log(f"  {n:34s} {c:>10,d} rows")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scale", choices=sorted(SCALES), default="starter")
    ap.add_argument("--seed", type=int, default=20261022)
    ap.add_argument("--out", default="output")
    a = ap.parse_args(argv)
    print(f"generating scale={a.scale} seed={a.seed} -> {a.out}")
    build(a.scale, a.seed, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

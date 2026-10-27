#!/usr/bin/env python3
"""Validate a generated dataset.

Three layers:
  1. INTEGRITY checks (must pass, zero violations): PK uniqueness, FK integrity, required fields, enums,
     ID formats, date ordering, arithmetic reconciliation, lifecycle transitions, mitigation policy.
  2. DETECTORS for the five injected edge cases. They only look at input tables. Their findings are then
     compared with ground_truth.csv (precision/recall must be 1.0).
  3. METRICS: service / supply KPIs written to metrics.json.

Usage:  python validate.py --data output
Exit code is 0 only if every check passes.
"""
import argparse
import json
import math
import os
import re
import sys
from datetime import date

import numpy as np
import pandas as pd

import schema
from generate import PLAN_RUN_DATE, WEEK1_START, UOM_FACTORS, WEEKS

ID_PATTERNS = {
    "sku": ("sku_id", r"^SKU-\d{6}$"), "location": ("location_id", r"^LOC-\d{3}$"),
    "supplier": ("supplier_id", r"^SUP-\d{4}$"), "purchase_order": ("po_id", r"^PO-2026-\d{6}$"),
    "shortage": ("shortage_id", r"^SHORT-2026-\d{6}$"), "production_plan": ("plan_id", r"^PP-2026-\d{6}$"),
    "mitigation_option": ("mitigation_id", r"^MIT-SHORT-2026-\d{6}-\d{2}$"),
    "forecast_demand": ("demand_id", r"^DEM-SKU-\d{6}-LOC-\d{3}-2026W\d{2}$"),
}
WEEK0 = pd.Timestamp(WEEK1_START)


def load(data_dir):
    t = {}
    for name in schema.TABLE_ORDER:
        t[name] = pd.read_csv(os.path.join(data_dir, f"{name}.csv"))
    return t


def week_idx(dates):
    return ((pd.to_datetime(dates) - WEEK0).dt.days // 7 + 1).astype(int)


class Report:
    def __init__(self):
        self.integrity, self.detectors = [], []

    def check(self, name, bad, detail=""):
        """bad = number of violations (0 == pass)."""
        self.integrity.append(dict(check=name, status="PASS" if bad == 0 else "FAIL", violations=int(bad), detail=detail))

    @property
    def ok(self):
        return all(c["status"] == "PASS" for c in self.integrity) and all(d["status"] == "PASS" for d in self.detectors)


# ----------------------------------------------------------------------------- layer 1: generic, schema-driven
def generic_checks(t, rep):
    for name in schema.TABLE_ORDER:
        df, spec = t[name], schema.TABLES[name]
        rep.check(f"{name}: primary key unique ({', '.join(spec['pk'])})", df.duplicated(spec["pk"]).sum())
        for u in spec["unique"]:
            rep.check(f"{name}: unique ({', '.join(u)})", df.duplicated(u).sum())
        missing = [c for c in schema.columns(name) if c not in df.columns]
        rep.check(f"{name}: all schema columns present", len(missing), ",".join(missing))
        nulls = sum(int(df[f[0]].isna().sum()) for f in spec["fields"] if f[2] and f[0] in df.columns)
        rep.check(f"{name}: required fields not null", nulls)
        enum_bad = sum(int((~df[f[0]].isin(f[3])).sum()) for f in spec["fields"]
                       if isinstance(f[3], list) and f[1] == "str" and f[0] in df.columns and f[2])
        rep.check(f"{name}: enum values allowed", enum_bad)
        for cols, ref, rcols in spec["fks"]:
            child = df[list(cols)].dropna()
            parent = t[ref][list(rcols)].drop_duplicates()
            m = child.merge(parent, left_on=list(cols), right_on=list(rcols), how="left", indicator=True)
            rep.check(f"{name}: FK ({', '.join(cols)}) -> {ref}", int((m["_merge"] == "left_only").sum()))
    for name, (col, pat) in ID_PATTERNS.items():
        rep.check(f"{name}: {col} format {pat}", int((~t[name][col].astype(str).str.match(pat)).sum()))
    fd = t["forecast_demand"]
    rep.check("forecast_demand: demand_id == DEM-<sku>-<loc>-<week>", int(
        (fd.demand_id != "DEM-" + fd.sku_id + "-" + fd.location_id + "-" + fd.week).sum()))
    inv = t["inventory"]
    rep.check("inventory: inventory_id == INV-<sku>-<loc>", int(
        (inv.inventory_id != "INV-" + inv.sku_id + "-" + inv.location_id).sum()))


# ----------------------------------------------------------------------------- layer 1: domain checks
def domain_checks(t, rep, flagged_options):
    po, lead, sku, inv = t["purchase_order"], t["lead_time"], t["sku"], t["inventory"]
    for col in ("order_date", "promised_date", "expected_arrival_date"):
        po[col] = pd.to_datetime(po[col])
    m = po.merge(lead[["sku_id", "supplier_id", "lead_time_days", "moq"]], on=["sku_id", "supplier_id"], how="left")
    rep.check("PO: order_date >= plan run date", int((po.order_date < pd.Timestamp(PLAN_RUN_DATE)).sum()))
    rep.check("PO: promised_date == order_date + lead_time_days",
              int(((m.promised_date - m.order_date).dt.days != m.lead_time_days).sum()))
    rep.check("PO: expected_arrival == promised + transport_delay",
              int(((po.expected_arrival_date - po.promised_date).dt.days != po.transport_delay_days).sum()))
    rep.check("PO: delay > 0 only for DELAYED POs", int(((po.transport_delay_days > 0) != (po.status == "DELAYED")).sum()))
    cost = po.sku_id.map(sku.set_index("sku_id").unit_cost)
    rep.check("PO: po_value == qty_base * unit_cost", int((np.abs(po.po_value - po.qty_base * cost) > 0.011).sum()))
    skup = sku.set_index("sku_id")
    rep.check("PO: no PO for a make SKU at a plant (produced there instead)", int(
        ((po.sku_id.map(skup.is_make) == 1) & po.location_id.map(t["location"].set_index("location_id").location_type).eq("PLANT")).sum()))
    # MOQ on the converted quantity
    conv = expected_base(po, skup)
    rep.check("PO: converted quantity >= MOQ", int((conv < m.moq).sum()))

    # lifecycle / event history
    ev = t["po_event"].sort_values(["po_id", "event_seq"])
    ev["event_date"] = pd.to_datetime(ev.event_date)
    g = ev.groupby("po_id")
    ev["prev"] = g.event_type.shift(1)
    allowed = {(a, b) for a, bs in schema.PO_TRANSITIONS.items() for b in bs}
    bad_tr = sum(1 for p, c in zip(ev.prev, ev.event_type) if (None if pd.isna(p) else p, c) not in allowed)
    rep.check("po_event: only allowed lifecycle transitions", bad_tr)
    rep.check("po_event: sequence is contiguous 1..n", int((g.event_seq.max() != g.event_seq.count()).sum()))
    rep.check("po_event: event dates non-decreasing", int((g.event_date.diff().dt.days < 0).sum()))
    last = ev.groupby("po_id").event_type.last()
    rep.check("po_event: last event == purchase_order.status",
              int((po.set_index("po_id").status != last.reindex(po.po_id).to_numpy()).sum()))
    rep.check("po_event: every PO has history", int((~po.po_id.isin(ev.po_id)).sum()))

    # substitution / BOM / production
    ss = t["sku_substitute"]
    rep.check("sku_substitute: substitute != sku", int((ss.sku_id == ss.substitute_sku_id).sum()))
    rep.check("sku_substitute: effective_to >= effective_from",
              int((pd.to_datetime(ss.effective_to) < pd.to_datetime(ss.effective_from)).sum()))
    bom = t["bom"]
    rep.check("bom: parent is a make SKU", int((bom.parent_sku_id.map(skup.is_make) != 1).sum()))
    rep.check("bom: component is RAW", int((bom.component_sku_id.map(skup.category) != "RAW").sum()))
    pp, pc, loc = t["production_plan"], t["production_capacity"], t["location"].set_index("location_id")
    rep.check("production_plan: make SKU at a PLANT", int(
        ((pp.sku_id.map(skup.is_make) != 1) | (pp.location_id.map(loc.location_type) != "PLANT")).sum()))
    rep.check("production_plan: week >= 2026W02", int((pp.week < "2026W02").sum()))
    used = pp.groupby(["location_id", "week"]).planned_qty.sum().rename("used").reset_index().merge(
        pc, on=["location_id", "week"], how="left")
    rep.check("production_plan: plant-week load <= production_capacity", int((used.used > used.capacity_units).sum()))
    cr = t["production_component_requirement"].merge(pp[["plan_id", "sku_id", "planned_qty"]], on="plan_id").merge(
        bom, left_on=["sku_id", "component_sku_id"], right_on=["parent_sku_id", "component_sku_id"], how="left")
    rep.check("component requirement == planned_qty * bom.qty_per", int((cr.required_qty != cr.planned_qty * cr.qty_per).sum()))
    exp_rows = pp[["plan_id", "sku_id"]].merge(bom, left_on="sku_id", right_on="parent_sku_id")
    rep.check("component requirement rows complete", abs(len(exp_rows) - len(t["production_component_requirement"])))

    # projected balance reconciliation
    pb = t["projected_balance"].sort_values(["sku_id", "location_id", "week"]).reset_index(drop=True)
    rep.check("balance: closing == opening + receipts + production - forecast", int(
        (pb.closing_qty != pb.opening_qty + pb.po_receipts_qty + pb.production_qty - pb.forecast_qty).sum()))
    key = pb.sku_id + "|" + pb.location_id
    prev_close = pb.groupby(key).closing_qty.shift(1)
    cont = prev_close.notna()
    rep.check("balance: opening(w) == closing(w-1)", int((pb.opening_qty[cont] != prev_close[cont]).sum()))
    first = pb[pb.week == "2026W01"].merge(inv[["sku_id", "location_id", "on_hand_qty"]], on=["sku_id", "location_id"])
    rep.check("balance: opening(W01) == inventory.on_hand_qty", int((first.opening_qty != first.on_hand_qty).sum()))
    rep.check("balance: 52 weeks per SKU-location", int((pb.groupby(key).size() != WEEKS).sum()))
    fd = pb.merge(t["forecast_demand"][["sku_id", "location_id", "week", "forecast_qty"]], on=["sku_id", "location_id", "week"],
                  suffixes=("", "_fd"), how="left")
    rep.check("balance: forecast == forecast_demand", int((fd.forecast_qty != fd.forecast_qty_fd).sum()))
    act = po[po.status != "CANCELLED"].copy()
    act["week"] = ["2026W%02d" % w for w in week_idx(act.expected_arrival_date)]
    rec = act[act.week.between("2026W01", "2026W52")].groupby(["sku_id", "location_id", "week"]).qty_base.sum().rename("r")
    chk = pb.merge(rec.reset_index(), on=["sku_id", "location_id", "week"], how="left").fillna({"r": 0})
    rep.check("balance: receipts == active PO qty_base by expected arrival week", int((chk.po_receipts_qty != chk.r).sum()))
    prod = pp.groupby(["sku_id", "location_id", "week"]).planned_qty.sum().rename("p").reset_index()
    chk = pb.merge(prod, on=["sku_id", "location_id", "week"], how="left").fillna({"p": 0})
    rep.check("balance: production == production_plan", int((chk.production_qty != chk.p).sum()))

    # shortages recomputed from the balance
    neg = pb.closing_qty < 0
    start = neg & ~neg.groupby(key).shift(1, fill_value=False)
    epi = start.groupby(key).cumsum()
    agg = pb[neg].assign(epi=epi[neg]).groupby(["sku_id", "location_id", "epi"]).agg(
        first_week=("week", "min"), end_week=("week", "max"), peak=("closing_qty", lambda x: int(-x.min()))).reset_index()
    sh = t["shortage"]
    j = sh.merge(agg, on=["sku_id", "location_id", "first_week"], how="outer", indicator=True, suffixes=("", "_re"))
    rep.check("shortage: episodes == negative-balance episodes (no missing / extra)", int((j["_merge"] != "both").sum()))
    both = j[j["_merge"] == "both"]
    rep.check("shortage: shortage_qty == peak backlog", int((both.shortage_qty != both.peak).sum()))
    rep.check("shortage: end_week matches", int((both.end_week != both.end_week_re).sum()))
    rep.check("shortage: value_at_risk == qty * unit_cost", int(
        (np.abs(sh.value_at_risk - sh.shortage_qty * sh.sku_id.map(skup.unit_cost)) > 0.011).sum()))
    rep.check("shortage: priority_rank is a permutation ordered by score", int(
        (sh.sort_values("priority_rank").priority_score.diff().dropna() > 0.0001).sum() +
        (sorted(sh.priority_rank) != list(range(1, len(sh) + 1)))))
    rep.check("shortage: every shortage has a cause code and explanation", int(sh.cause_detail.isna().sum() + sh.cause_code.isna().sum()))
    rep.check("shortage: status consistent with mitigation options", int(
        (sh.set_index("shortage_id").status != status_from_mit(sh, t["mitigation_option"], flagged_options)).sum()))

    mitigation_checks(t, rep, po, lead, skup, loc)


def expected_base(po, skup):
    f = [UOM_FACTORS[(a, b)] for a, b in zip(po.order_uom, po.sku_id.map(skup.uom))]
    return np.round(po.qty_ordered * np.array(f)).astype(int)


def status_from_mit(sh, mit, flagged_options):
    """Status is decided from valid options only: options flagged by a detector (e.g. unapproved substitute)
    must not make a shortage look resolved."""
    valid = mit[~mit.mitigation_id.isin(flagged_options)]
    res = set(valid.shortage_id[valid.resolves_shortage == 1])
    any_ = set(valid.shortage_id)
    return pd.Series(["MITIGATION_PROPOSED" if s in res else ("OPEN" if s in any_ else "ESCALATED")
                      for s in sh.shortage_id], index=sh.shortage_id)


def mitigation_checks(t, rep, po, lead, skup, loc):
    mit, sh = t["mitigation_option"], t["shortage"].set_index("shortage_id")
    cap = t["supplier_capacity"].assign(w=lambda d: d.week.str[-2:].astype(int))
    act = po[po.status != "CANCELLED"].copy()
    act["w"] = week_idx(act.promised_date)
    used = act.groupby(["supplier_id", "w"]).qty_base.sum().rename("used").reset_index()
    remaining = cap.merge(used, on=["supplier_id", "w"], how="left").fillna({"used": 0})
    remaining["rem"] = (remaining.capacity_units - remaining.used).clip(lower=0)
    rem = remaining.set_index(["supplier_id", "w"]).rem
    m = mit.join(sh[["sku_id", "location_id", "first_week", "shortage_qty"]], on="shortage_id")
    m["rec_w"] = m.recovery_week.str[-2:].astype(int)
    m["fw"] = m.first_week.str[-2:].astype(int)
    rep.check("mitigation: option ids contiguous per shortage (MIT-<shortage>-01..)", int(
        (m.mitigation_id != m.shortage_id.map(lambda s: "MIT-" + s) + "-" +
         (m.groupby("shortage_id").cumcount() + 1).map("{:02d}".format)).sum()))
    rep.check("mitigation: at most one recommended option per shortage", int((m.groupby("shortage_id").recommended.sum() > 1).sum()))
    rep.check("mitigation: resolves flag == (qty>=need and recovery<=need week)", int(
        (m.resolves_shortage != ((m.recovery_qty >= m.shortage_qty) & (m.rec_w <= m.fw)).astype(int)).sum()))
    rep.check("mitigation: cost_per_unit == extra_cost/qty", int(
        (np.abs(m.cost_per_unit - m.extra_cost / m.recovery_qty) > 0.011).sum()))
    rep.check("mitigation: service level within 0..100", int(((m.service_level_pct < 0) | (m.service_level_pct > 100)).sum()))
    a = m[m.option_type == "ALT_SUPPLIER"].merge(lead, left_on=["sku_id", "supplier_id"], right_on=["sku_id", "supplier_id"],
                                                  how="left", suffixes=("", "_lt"))
    rep.check("mitigation ALT_SUPPLIER: (sku, supplier) exists in lead_time with same lead time",
              int((a.lead_time_days != a.lead_time_days_lt).sum()))
    arr_w = week_idx(pd.Series(PLAN_RUN_DATE.isoformat(), index=a.index).pipe(pd.to_datetime) + pd.to_timedelta(a.lead_time_days, "D"))
    rep.check("mitigation ALT_SUPPLIER: recovery week == plan run date + lead time", int((a.rec_w != arr_w).sum()))
    rep.check("mitigation ALT_SUPPLIER: qty >= MOQ", int((a.recovery_qty < a.moq).sum()))
    rep.check("mitigation ALT_SUPPLIER: qty <= remaining supplier capacity", int(sum(
        q > rem.get((s, w), 0) for s, w, q in zip(a.supplier_id, a.rec_w, a.recovery_qty))))
    e = m[m.option_type == "EXPEDITE_PO"].merge(po[["po_id", "sku_id", "location_id", "order_date", "promised_date", "expected_arrival_date", "qty_base"]],
                                                 left_on="source_po_id", right_on="po_id", how="left", suffixes=("", "_po"))
    orig = (e.promised_date - e.order_date).dt.days
    rep.check("mitigation EXPEDITE_PO: source PO belongs to the same SKU-location", int(
        ((e.sku_id != e.sku_id_po) | (e.location_id != e.location_id_po)).sum()))
    rep.check("mitigation EXPEDITE_PO: compression <= 50% and actually earlier", int(
        ((e.lead_time_days < np.ceil(0.5 * orig)) | (e.order_date + pd.to_timedelta(e.lead_time_days, "D") >= e.expected_arrival_date)).sum()))
    p = m[m.option_type == "PRODUCTION_BOOST"]
    rep.check("mitigation PRODUCTION_BOOST: make SKU at a PLANT", int(
        ((p.sku_id.map(skup.is_make) != 1) | (p.location_id.map(loc.location_type) != "PLANT")).sum()))


# ----------------------------------------------------------------------------- layer 2: detectors vs ground truth
def detect(t):
    po, skup = t["purchase_order"].copy(), t["sku"].set_index("sku_id")
    found = {}
    key = ["sku_id", "supplier_id", "location_id", "order_date", "promised_date", "qty_ordered", "order_uom"]
    found["INBOUND_COUNTED_TWICE"] = set(po.sort_values("po_id")[po.sort_values("po_id").duplicated(key, keep="first")].po_id)
    found["UOM_MISMATCH"] = set(po.po_id[po.qty_base != expected_base(po, skup)])
    act = po[po.status != "CANCELLED"].copy()
    act["w"] = week_idx(act.promised_date)
    used = act.groupby(["supplier_id", "w"]).qty_base.sum().rename("used").reset_index()
    cap = t["supplier_capacity"].assign(w=lambda d: d.week.str[-2:].astype(int)).merge(used, on=["supplier_id", "w"])
    over = cap[cap.used > cap.capacity_units]
    found["SUPPLIER_CAPACITY_EXCEEDED"] = {f"{s}|{w}" for s, w in zip(over.supplier_id, over.week)}
    sh = t["shortage"]
    lt_min = t["lead_time"].groupby("sku_id").lead_time_days.min()
    exp = sh.sku_id.map(lt_min)
    exp_latest = pd.to_datetime(sh.need_date) - pd.to_timedelta(exp, "D")
    wrong = (sh.lead_time_days_used != exp) | (pd.to_datetime(sh.latest_order_date) != exp_latest) | (
        sh.ordering_window_open != (exp_latest >= pd.Timestamp(PLAN_RUN_DATE)).astype(int))
    found["SHORTAGE_WITHOUT_LEAD_TIME"] = set(sh.shortage_id[wrong])
    mit = t["mitigation_option"]
    s = mit[mit.option_type == "SUBSTITUTE"].join(sh.set_index("shortage_id")[["sku_id", "need_date"]], on="shortage_id")
    ss = t["sku_substitute"].rename(columns={"sku_id": "src"})
    j = s.merge(ss, left_on=["sku_id", "substitute_sku_id"], right_on=["src", "substitute_sku_id"], how="left")
    need = pd.to_datetime(j.need_date)
    bad = (j.approval_status != "APPROVED") | (pd.to_datetime(j.effective_from) > need) | (
        pd.to_datetime(j.effective_to).notna() & (pd.to_datetime(j.effective_to) < need))
    found["SUBSTITUTE_NOT_APPROVED"] = set(j.mitigation_id[bad])
    return found


def score_detectors(found, gt, rep):
    anomalies = gt[gt.label_kind == "ANOMALY"]
    for issue, ids in sorted(found.items()):
        truth_rows = anomalies[anomalies.issue_type == issue]
        truth = set(truth_rows.related_id if issue == "SUPPLIER_CAPACITY_EXCEEDED" else truth_rows.entity_id)
        tp, fp, fn = len(ids & truth), len(ids - truth), len(truth - ids)
        prec = tp / (tp + fp) if tp + fp else 1.0
        rec = tp / (tp + fn) if tp + fn else 1.0
        rep.detectors.append(dict(issue_type=issue, injected=len(truth), detected=len(ids), true_positive=tp,
                                  false_positive=fp, false_negative=fn, precision=round(prec, 3), recall=round(rec, 3),
                                  status="PASS" if fp == 0 and fn == 0 else "FAIL"))


def no_leakage_check(data_dir, rep):
    """Ground-truth labels must not appear in any input table."""
    bad = 0
    for name in schema.TABLE_ORDER:
        cols = pd.read_csv(os.path.join(data_dir, f"{name}.csv"), nrows=0).columns
        bad += sum(c in ("issue_type", "label_kind", "gt_id", "is_anomaly", "ground_truth") for c in cols)
    rep.check("ground truth not leaked into input tables (no label columns)", bad)


# ----------------------------------------------------------------------------- layer 3: metrics
def metrics(t, gt):
    pb, sh, mit, po = t["projected_balance"], t["shortage"], t["mitigation_option"], t["purchase_order"]
    total = int(pb.forecast_qty.sum())
    unmet = int(np.minimum(pb.forecast_qty, (-pb.closing_qty).clip(lower=0)).sum())
    n_pairs = len(t["inventory"])
    act = po[po.status != "CANCELLED"]
    cap = t["supplier_capacity"]
    res_by = mit.groupby("shortage_id").resolves_shortage.max()
    return dict(
        sku_location_pairs=n_pairs, shortage_episodes=len(sh),
        pairs_with_shortage_pct=round(100 * sh[["sku_id", "location_id"]].drop_duplicates().shape[0] / n_pairs, 2),
        approx_fill_rate_pct=round(100 * (1 - unmet / total), 2),
        shortage_by_cause=sh.cause_code.value_counts().to_dict(),
        shortage_by_status=sh.status.value_counts().to_dict(),
        shortages_with_resolving_option_pct=round(100 * float(res_by.reindex(sh.shortage_id).fillna(0).mean()), 1),
        avg_options_per_shortage=round(len(mit) / len(sh), 2),
        ordering_window_closed_pct=round(100 * float((sh.ordering_window_open == 0).mean()), 1),
        total_value_at_risk_usd=round(float(sh.value_at_risk.sum()), 2),
        avg_extra_cost_by_option_usd=mit.groupby("option_type").extra_cost.mean().round(2).to_dict(),
        avg_service_level_by_option_pct=mit.groupby("option_type").service_level_pct.mean().round(1).to_dict(),
        po_count=len(po), po_status=po.status.value_counts().to_dict(),
        po_delayed_pct=round(100 * float((po.status == "DELAYED").mean()), 2),
        po_avg_delay_days_when_delayed=round(float(po.transport_delay_days[po.status == "DELAYED"].mean()), 1),
        supplier_capacity_utilisation_pct=round(100 * float(act.qty_base.sum() / cap.capacity_units.sum()), 2),
        demand_spike_scenarios=int((gt.issue_type == "DEMAND_SPIKE").sum()),
    )


# ----------------------------------------------------------------------------- driver
def run(data_dir, write=True):
    t = load(data_dir)
    gt = pd.read_csv(os.path.join(data_dir, "ground_truth.csv"))
    rep = Report()
    generic_checks(t, rep)
    no_leakage_check(data_dir, rep)
    found = detect(t)
    domain_checks(t, rep, found["SUBSTITUTE_NOT_APPROVED"])
    score_detectors(found, gt, rep)
    met = metrics(t, gt)
    out = dict(data_dir=data_dir, integrity=rep.integrity, detectors=rep.detectors, metrics=met, passed=rep.ok,
               totals=dict(checks=len(rep.integrity) + len(rep.detectors),
                           failed=sum(c["status"] != "PASS" for c in rep.integrity + rep.detectors)))
    if write:
        with open(os.path.join(data_dir, "validation_summary.json"), "w") as f:
            json.dump(out, f, indent=1, default=str)
        with open(os.path.join(data_dir, "metrics.json"), "w") as f:
            json.dump(met, f, indent=1, default=str)
        with open(os.path.join(data_dir, "validation_summary.md"), "w") as f:
            f.write(render_md(out))
    return out


def render_md(out):
    L = ["# Validation summary", "", f"Result: **{'PASS' if out['passed'] else 'FAIL'}** "
         f"({out['totals']['checks'] - out['totals']['failed']}/{out['totals']['checks']} checks)", "",
         "## Injected edge cases vs detectors", "",
         "| Issue type | Injected | Detected | TP | FP | FN | Precision | Recall | Status |", "|---|---|---|---|---|---|---|---|---|"]
    for d in out["detectors"]:
        L.append(f"| {d['issue_type']} | {d['injected']} | {d['detected']} | {d['true_positive']} | {d['false_positive']} | "
                 f"{d['false_negative']} | {d['precision']} | {d['recall']} | {d['status']} |")
    L += ["", "## Integrity checks", "", "| Check | Status | Violations |", "|---|---|---|"]
    L += [f"| {c['check']} | {c['status']} | {c['violations']} |" for c in out["integrity"]]
    L += ["", "## Metrics", "", "```json", json.dumps(out["metrics"], indent=1, default=str), "```", ""]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="output")
    a = ap.parse_args(argv)
    out = run(a.data)
    for c in out["integrity"]:
        if c["status"] != "PASS":
            print("FAIL", c["check"], c["violations"], c["detail"])
    for d in out["detectors"]:
        print(f"{d['status']}  {d['issue_type']:30s} injected={d['injected']:3d} detected={d['detected']:3d} "
              f"P={d['precision']} R={d['recall']}")
    print(f"{out['totals']['checks'] - out['totals']['failed']}/{out['totals']['checks']} checks passed")
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

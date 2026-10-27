#!/usr/bin/env python3
"""Reproducibility demo: regenerate twice with the same seed and compare row counts + SHA-256 checksums.
Also regenerates once with a different seed to show the checksums really depend on the seed.

Usage:  python reproduce.py --scale starter --seed 20261022 [--report output/starter/reproducibility_report.json]
"""
import argparse
import json
import shutil
import sys
import tempfile

import generate


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scale", choices=sorted(generate.SCALES), default="starter")
    ap.add_argument("--seed", type=int, default=20261022)
    ap.add_argument("--report", default=None, help="optional path to write the JSON report")
    a = ap.parse_args(argv)

    tmp = tempfile.mkdtemp(prefix="repro_")
    try:
        run1 = generate.build(a.scale, a.seed, f"{tmp}/run1", verbose=False)
        run2 = generate.build(a.scale, a.seed, f"{tmp}/run2", verbose=False)
        other = generate.build(a.scale, a.seed + 1, f"{tmp}/other", verbose=False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    same_counts = run1["row_counts"] == run2["row_counts"]
    same_hash = run1["sha256"] == run2["sha256"]
    diff_seed = sum(run1["sha256"][f] != other["sha256"][f] for f in run1["sha256"] if f.endswith(".csv"))
    report = dict(scale=a.scale, seed=a.seed, run1_vs_run2_row_counts_identical=same_counts,
                  run1_vs_run2_checksums_identical=same_hash, files_compared=len(run1["sha256"]),
                  different_seed_files_that_differ=diff_seed, row_counts=run1["row_counts"], sha256=run1["sha256"])
    print(f"row counts identical : {same_counts}")
    print(f"sha256 identical     : {same_hash}  ({len(run1['sha256'])} files)")
    print(f"seed+1 changes {diff_seed} CSV files (expected: most of them)")
    if a.report:
        with open(a.report, "w") as f:
            json.dump(report, f, indent=1, sort_keys=True)
    return 0 if same_counts and same_hash and diff_seed > 0 else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Load the generated CSVs into SQLite with full PK/FK/CHECK constraints (schema.sql) and optionally dump seed SQL.

Usage:  python export_sql.py --data output/starter --db output/starter/supply_chain.db --dump output/starter/seed.sql
"""
import argparse
import os
import sqlite3
import sys

import pandas as pd

import schema


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="output/starter")
    ap.add_argument("--db", default=None, help="sqlite file to create (default: <data>/supply_chain.db)")
    ap.add_argument("--dump", default=None, help="also write a plain-SQL seed file (large for full scale)")
    a = ap.parse_args(argv)
    db = a.db or os.path.join(a.data, "supply_chain.db")
    if os.path.exists(db):
        os.remove(db)
    con = sqlite3.connect(db)
    con.executescript(schema.render_ddl())          # PRAGMA foreign_keys = ON is inside the DDL
    for name in schema.TABLE_ORDER:
        df = pd.read_csv(os.path.join(a.data, f"{name}.csv"))
        df.to_sql(name, con, if_exists="append", index=False, chunksize=50000)
        print(f"loaded {name:34s} {len(df):>10,d} rows")
    con.commit()
    bad = con.execute("PRAGMA foreign_key_check").fetchall()
    print("foreign_key_check violations:", len(bad))
    if a.dump:
        with open(a.dump, "w") as f:
            for line in con.iterdump():
                f.write(line + "\n")
        print("wrote", a.dump)
    con.close()
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())

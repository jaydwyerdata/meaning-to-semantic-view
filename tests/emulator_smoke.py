"""
Offline smoke test: runs the DDL, the data load and the reference queries against fakesnow,
a local DuckDB-backed Snowflake emulator, so the SQL can be checked without a Snowflake account.

What this proves: the scripts parse, every insert runs, row counts land where expected, and the
reference queries return values that show each designed trap actually exists in the data.
What it does not prove: Snowflake-specific behaviour. The emulator's HASH is unsigned and differs
from Snowflake's, so the harness rewrites the hash expressions and exact values will differ from a
real Snowflake load. The real check is running the scripts in Snowflake itself.

    pip install fakesnow sqlglot
    python tests/emulator_smoke.py
"""
import re
import sys
from pathlib import Path

import fakesnow
import snowflake.connector
import sqlglot

ROOT = Path(__file__).resolve().parents[1]
FILES = ["sql/01_setup_and_ddl.sql", "sql/02_load_data.sql", "eval/reference_queries.sql"]

# Minimum row counts per table; a load that silently drops rows fails here.
EXPECTED_MIN = {
    "ERP.CUSMST": 5000, "ERP.LOCMST": 125, "ERP.ITMMST": 800, "POS.TXN_HDR": 150000,
    "OMS.ORD_HDR": 20000, "LOY.MBR": 2900, "WMS.INV_SNP": 340000, "BIL.SUB": 800,
}


def emulator_sql() -> list[str]:
    txt = "\n".join((ROOT / f).read_text() for f in FILES)
    # Emulator only: signed-hash semantics, and no session variables or IDENTIFIER().
    txt = re.sub(r"MOD\(ABS\(HASH\(([^()]*)\)\), (\$?\w+)\)", r"CAST(MOD(HASH(\1), \2) AS BIGINT)", txt)
    txt = re.sub(r"SET (DB_NAME|WH_NAME|AS_OF) = .*?;\n", "", txt)
    txt = txt.replace("IDENTIFIER($DB_NAME)", "ALDERGLEN_RAW").replace("IDENTIFIER($WH_NAME)", "SVC_WH")
    txt = txt.replace("$AS_OF", "CURRENT_DATE()")
    stmts = sqlglot.transpile(txt, read="snowflake", write="snowflake", comments=False)
    return [s.strip() for s in stmts if s.strip()]


def main() -> int:
    results = {}
    n_mbr = 0
    with fakesnow.patch():
        cur = snowflake.connector.connect(database="ALDERGLEN_RAW", schema="ERP").cursor()
        for stmt in emulator_sql():
            upper = stmt.upper()
            if upper.startswith(("CREATE WAREHOUSE", "USE WAREHOUSE")):
                continue
            if upper.startswith("SET N_MBR"):
                cur.execute("SELECT COUNT(*) FROM LOY.MBR")
                n_mbr = cur.fetchone()[0]
                continue
            cur.execute(stmt.replace("$N_MBR", str(n_mbr)))
            if upper.startswith(("SELECT", "WITH")):
                for name, value in cur.fetchall():
                    results[name] = value

    failures = []
    for table, minimum in EXPECTED_MIN.items():
        if results.get(table, 0) < minimum:
            failures.append(f"{table}: {results.get(table)} rows, expected at least {minimum}")
    checks = {
        "marketing and finance 'active customer' disagree":
            results["T1 active customer (marketing)"] != results["T2 active customer (finance)"],
        "some SKUs at risk without being at zero": results["T6 at risk but not at zero"] > 0,
        "some SKUs at zero without being at risk": results["T6 at zero but not at risk (no recent sales)"] > 0,
        "stale LSTPURDT undercounts active customers":
            results["Decoy: active per ERP.CUSMST.LSTPURDT"] < results["T1 active customer (marketing)"],
        "card status overstates engagement":
            results["Decoy: LOY CARD_STAT = ACT"] > results["T3 engaged member"],
    }
    failures += [name for name, ok in checks.items() if not ok]

    for name, value in sorted(results.items()):
        print(f"{name:50} {value}")
    print("\nFAILED:\n  " + "\n  ".join(failures) if failures else "\nAll checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

"""PROFILE_ESTATE: one pass over every estate table, storing per-column statistics the mapper
uses as evidence (catalog metadata and sample values, ADR-010). Writes MAPPER.COLUMN_PROFILE."""
import json

PROFILE_TABLE = "COLUMN_PROFILE"
DATE_TYPES = ("DATE", "TIMESTAMP_NTZ", "TIMESTAMP_LTZ", "TIMESTAMP_TZ")


def type_label(data_type, precision, scale, char_len):
    if data_type == "NUMBER" and precision is not None:
        return f"NUMBER({precision},{scale})"
    if data_type == "TEXT" and char_len is not None:
        return f"VARCHAR({char_len})"
    return data_type


def table_profile_sql(db, schema, table, columns):
    """columns: list of (name, data_type). One scan per table."""
    parts = ["COUNT(*)"]
    for name, data_type in columns:
        c = f'"{name}"'
        parts += [
            f"COUNT({c})",
            f"APPROX_COUNT_DISTINCT({c})",
            f"MIN({c})::VARCHAR",
            f"MAX({c})::VARCHAR",
            f"APPROX_TOP_K({c}, 8)",
            f"DATEDIFF('day', MAX({c}), CURRENT_DATE())" if data_type in DATE_TYPES else "NULL",
        ]
    return f"SELECT {', '.join(parts)} FROM {db}.{schema}.{table}"


def main(session, raw_db):
    require_mapper_role(session)
    db = check_ident(raw_db.upper())
    cols = session.sql(
        f"SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE, NUMERIC_PRECISION, NUMERIC_SCALE, "
        f"CHARACTER_MAXIMUM_LENGTH FROM {db}.INFORMATION_SCHEMA.COLUMNS "
        f"WHERE TABLE_SCHEMA <> 'INFORMATION_SCHEMA' ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION"
    ).collect()
    tables = {}
    for r in cols:
        tables.setdefault((r[0], r[1]), []).append(r)

    session.sql(
        f"CREATE OR REPLACE TABLE {PROFILE_TABLE} (TABLE_SCHEMA STRING, TABLE_NAME STRING, "
        "COLUMN_NAME STRING, ORDINAL NUMBER, DATA_TYPE STRING, ROW_COUNT NUMBER, NON_NULL NUMBER, "
        "DISTINCT_APPROX NUMBER, MIN_VALUE STRING, MAX_VALUE STRING, DAYS_SINCE_MAX NUMBER, "
        "TOP_VALUES VARIANT, PROFILED_AT TIMESTAMP_LTZ)"
    ).collect()

    n = 0
    for (schema, table), rows in tables.items():
        s, t = check_ident(schema), check_ident(table)
        stats = session.sql(table_profile_sql(db, s, t, [(r[2], r[3]) for r in rows])).collect()[0]
        row_count = stats[0]
        for i, r in enumerate(rows):
            base = 1 + i * 6
            non_null, distinct, mn, mx, top, age = stats[base:base + 6]
            session.sql(
                f"INSERT INTO {PROFILE_TABLE} SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, PARSE_JSON(?), "
                "CURRENT_TIMESTAMP()",
                params=[s, t, r[2], i + 1, type_label(r[3], r[4], r[5], r[6]), row_count, non_null,
                        distinct, mn, mx, age, top if isinstance(top, str) else json.dumps(top)],
            ).collect()
            n += 1
    return {"tables": len(tables), "columns": n}

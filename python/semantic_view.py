"""GENERATE_SEMANTIC_VIEW: turns a mapped term into a Snowflake semantic view, then checks it.

Layer 3 thin slice (ADR-016). No model call: the mapping step proposed the logic and proved it with a
number; this step only translates a supported shape into DDL and proves the translation by comparing
the semantic view's answer with the mapping's own measure query, run at the same moment.

Supported shape, "counted once per <entity>, if it had a qualifying event in the last N days, in any of
these sources": every time window is SCHEMA.TABLE.COLUMN >= DATEADD(day, -N, CURRENT_DATE), joined with
OR across sources; every filter or exclusion is a plain predicate on one table. Anything else (aggregate
conditions, subqueries, windows combined with AND, filters spanning tables) is refused with the reason,
never guessed.
"""
import json
import re

COLUMN_REF = re.compile(r"\b([A-Z][A-Z0-9_]*)\.([A-Z][A-Z0-9_]*)\.([A-Z][A-Z0-9_]*)\b", re.IGNORECASE)
WINDOW = re.compile(
    r"^\s*([A-Z][A-Z0-9_]*\.[A-Z][A-Z0-9_]*)\.([A-Z][A-Z0-9_]*)\s*>=\s*"
    r"DATEADD\(\s*DAY\s*,\s*-\s*(\d{1,4})\s*,\s*CURRENT_DATE\s*(\(\s*\))?\s*\)\s*$",
    re.IGNORECASE,
)
# Model-written fragments become part of a view. Refuse anything that is not a plain predicate.
UNSAFE = re.compile(
    r";|\$\$|--|/\*|\bSELECT\b|\bHAVING\b|\bOVER\b|\b(SUM|COUNT|AVG|MIN|MAX)\s*\(|"
    r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|DROP|ALTER|GRANT|REVOKE|CALL|COPY|PUT|TRUNCATE|EXECUTE|USE)\b",
    re.IGNORECASE,
)
PREDICATE = re.compile(r"(=|<>|!=|<|>|\bIN\b|\bLIKE\b|\bIS\b|\bBETWEEN\b)", re.IGNORECASE)
SUBJECT, EVENTS = "subject", "qualifying_events"


class Unsupported(ValueError):
    """The mapping is valid but not a shape this slice can generate. The message says why."""


def is_note(expr: str) -> bool:
    t = (expr or "").strip()
    return t == "" or t.startswith("--") or t.upper().startswith("N/A")


def tables_in(expr: str) -> set:
    return {f"{a}.{b}".upper() for a, b, _ in COLUMN_REF.findall(expr or "")}


def split_top(expr: str, word: str) -> list:
    """Split on a keyword (AND / OR) at parenthesis depth 0, outside string literals."""
    parts, depth, quote, start, i, s = [], 0, False, 0, 0, expr
    pat = re.compile(rf"\s{word}\s", re.IGNORECASE)
    while i < len(s):
        ch = s[i]
        if ch == "'":
            quote = not quote
        elif not quote and ch == "(":
            depth += 1
        elif not quote and ch == ")":
            depth -= 1
        elif not quote and depth == 0:
            m = pat.match(s, i)
            if m:
                parts.append(s[start:i])
                start = i = m.end()
                continue
        i += 1
    parts.append(s[start:])
    return [p.strip() for p in parts if p.strip()]


def build_spec(proposal: dict) -> dict:
    """The supported shape, extracted from a proposal, or Unsupported with the reason."""
    entity = proposal.get("entity") or {}
    e_table = (entity.get("table") or "").upper()
    keys = [k.upper() for k in entity.get("key_columns") or []]
    if not re.match(r"^[A-Z][A-Z0-9_]*\.[A-Z][A-Z0-9_]*$", e_table) or len(keys) != 1 \
            or not re.match(r"^[A-Z][A-Z0-9_]*$", keys[0]):
        raise Unsupported("the counted thing needs one table and one key column")
    key = keys[0]
    comps = [c for c in proposal.get("components") or [] if isinstance(c, dict)]
    ignored = []

    windows = {}
    for c in comps:
        if c.get("role") != "time_window" or is_note(c.get("expression")):
            continue
        expr = c["expression"]
        for part in split_top(expr, "OR"):
            if len(split_top(part, "AND")) > 1:
                raise Unsupported(f"time window combines conditions with AND: {expr}")
            m = WINDOW.match(part)
            if not m:
                raise Unsupported(f"time window is not TABLE.COLUMN >= DATEADD(day, -N, CURRENT_DATE): {part}")
            table, column, days = m.group(1).upper(), m.group(2).upper(), int(m.group(3))
            if table == e_table:
                raise Unsupported(f"time window is on the counted table itself: {part}")
            if table in windows and windows[table]["column"] != column:
                raise Unsupported(f"two different time windows on {table}")
            windows[table] = {"column": column, "days": days, "expression": part}
    if not windows:
        raise Unsupported("no time window: this slice generates 'had a qualifying event in the last N days' terms")

    filters = {t: [] for t in windows}
    subject_filters = []
    for c in comps:
        if c.get("role") not in ("filter", "exclusion"):
            continue
        expr = (c.get("expression") or "").strip()
        if is_note(expr) or not PREDICATE.search(expr):
            ignored.append({"role": c.get("role"), "expression": expr, "why": "a note, not a condition"})
            continue
        if UNSAFE.search(expr):
            raise Unsupported(f"{c.get('role')} needs an aggregate, subquery or keyword this slice does not generate: {expr}")
        ts = tables_in(expr)
        if len(ts) != 1:
            raise Unsupported(f"{c.get('role')} spans tables or names none: {expr}")
        t = ts.pop()
        if t == e_table:
            subject_filters.append(expr)
        elif t in filters:
            filters[t].append(expr)
        else:
            raise Unsupported(f"{c.get('role')} is on {t}, which has no time window: {expr}")

    joins = {}
    for c in comps:
        if c.get("role") != "join" or is_note(c.get("expression")):
            continue
        expr = c["expression"].strip()
        ts = tables_in(expr)
        linked = [t for t in windows if ts == {e_table, t}]
        if not linked or UNSAFE.search(expr) or "=" not in expr or len(split_top(expr, "AND")) > 1 \
                or len(split_top(expr, "OR")) > 1:
            ignored.append({"role": "join", "expression": expr, "why": "does not link the counted table to an event source"})
            continue
        t = linked[0]
        if t in joins and joins[t] != expr:
            raise Unsupported(f"two different joins to {t}")
        joins[t] = expr
    every_expr = " ".join(c.get("expression") or "" for c in comps).upper()
    for t in windows:
        if t not in joins:
            if f"{t}.{key}" in every_expr:
                joins[t] = f"{e_table}.{key} = {t}.{key}"
            else:
                raise Unsupported(f"no join from {t} to {e_table}")

    sources = [{"table": t, **windows[t], "filters": filters[t], "join": joins[t]} for t in sorted(windows)]
    return {"entity_table": e_table, "key": key, "sources": sources,
            "subject_filters": subject_filters, "ignored": ignored}


def aliased(expr: str, aliases: dict) -> str:
    """SCHEMA.TABLE.COLUMN -> alias.COLUMN, so the view never depends on three-part column names."""
    def swap(m):
        table = f"{m.group(1)}.{m.group(2)}".upper()
        if table not in aliases:
            raise Unsupported(f"{table} is not part of this branch")
        return f"{aliases[table]}.{m.group(3).upper()}"
    return COLUMN_REF.sub(swap, expr)


def lit(text) -> str:
    """A SQL string literal."""
    s = str(text or "")
    if "$" * 2 in s:
        raise ValueError("text contains a double dollar sign")
    return "'" + s.replace("\\", "\\\\").replace("'", "''") + "'"


def metric_name(term: str) -> str:
    slug = re.sub(r"[^A-Z0-9]+", "_", (term or "").upper()).strip("_")
    name = f"{slug}_COUNT" if slug else "TERM_COUNT"
    if not re.match(r"^[A-Z][A-Z0-9_]{0,200}$", name):
        raise ValueError(f"Cannot name a metric from {term!r}")
    return name


def view_sql(spec: dict, view: str, raw_db: str) -> str:
    branches = []
    for src in spec["sources"]:
        aliases = {spec["entity_table"]: "e", src["table"]: "s"}
        where = [src["expression"], *src["filters"], *spec["subject_filters"]]
        branches.append(
            f"SELECT e.{spec['key']} AS ENTITY_KEY, s.{src['column']}::DATE AS EVENT_DATE, "
            f"{lit(src['table'])} AS EVENT_SOURCE\n"
            f"FROM {raw_db}.{src['table']} s\n"
            f"JOIN {raw_db}.{spec['entity_table']} e ON {aliased(src['join'], aliases)}\n"
            f"WHERE " + "\n  AND ".join(f"({aliased(w, aliases)})" for w in where)
        )
    return (f"CREATE OR REPLACE VIEW {view}\n"
            f"  COMMENT = 'Qualifying events in the window, one row per event, generated from a confirmed mapping'\n"
            f"AS\n" + "\nUNION ALL\n".join(branches))


def semantic_view_sql(spec: dict, name: str, view: str, raw_db: str, term: dict, run_id: str) -> str:
    metric = metric_name(term.get("term"))
    synonyms = [s for s in term.get("synonyms") or [] if isinstance(s, str) and s.strip()]
    syn = f" WITH SYNONYMS = ({', '.join(lit(s) for s in synonyms)})" if synonyms else ""
    definition = " ".join(str(term.get("definition") or "").split())
    view_comment = f"{term.get('term')}, as defined by {term.get('owner')}. Generated from mapping run {run_id}."
    return (
        f"CREATE OR REPLACE SEMANTIC VIEW {name}\n"
        f"  TABLES (\n"
        f"    {SUBJECT} AS {raw_db}.{spec['entity_table']} PRIMARY KEY ({spec['key']})\n"
        f"      COMMENT = {lit('One row per ' + str(term.get('counted_per') or 'counted thing'))},\n"
        f"    {EVENTS} AS {view}\n"
        f"      COMMENT = 'Events that qualify under the business definition, inside its time window'\n"
        f"  )\n"
        f"  RELATIONSHIPS (\n"
        f"    events_to_subject AS {EVENTS} (ENTITY_KEY) REFERENCES {SUBJECT}\n"
        f"  )\n"
        f"  DIMENSIONS (\n"
        f"    {EVENTS}.event_day AS {EVENTS}.EVENT_DATE COMMENT = 'Day of the qualifying event',\n"
        f"    {EVENTS}.source_system AS {EVENTS}.EVENT_SOURCE COMMENT = 'Which source the event came from'\n"
        f"  )\n"
        f"  METRICS (\n"
        f"    {EVENTS}.{metric} AS COUNT(DISTINCT {EVENTS}.ENTITY_KEY){syn}\n"
        f"      COMMENT = {lit(definition)}\n"
        f"  )\n"
        f"  COMMENT = {lit(view_comment)}"
    )


def main(session, term_id, use_history, raw_db):
    require_mapper_role(session)
    db = check_ident((raw_db or "").upper())
    tid = check_ident((term_id or "").upper())
    app_db, app_schema = session.sql("SELECT CURRENT_DATABASE(), CURRENT_SCHEMA()").collect()[0]
    app = f"{check_ident(app_db)}.{check_ident(app_schema)}"

    term_rows = session.sql(f"SELECT TERM FROM {app}.GLOSSARY WHERE TERM_ID = ?", params=[tid]).collect()
    if not term_rows:
        raise ValueError(f"No glossary term {tid!r}")
    term = json.loads(term_rows[0][0])

    history_clause = "" if use_history is None else "AND USE_HISTORY = ? "
    params = [tid] + ([] if use_history is None else [bool(use_history)])
    rows = session.sql(
        f"SELECT RUN_ID, PROPOSAL, MEASURE_SQL FROM {app}.PROPOSALS WHERE TERM_ID = ? {history_clause}"
        "AND MEASURE_ERROR IS NULL AND PROPOSAL IS NOT NULL ORDER BY CREATED_AT DESC LIMIT 1",
        params=params,
    ).collect()
    if not rows:
        raise ValueError(f"No successful mapping run for {tid!r}: CALL MAP_TERM first")
    run_id, proposal, measure_sql = rows[0][0], json.loads(rows[0][1]), rows[0][2]

    spec = build_spec(proposal)
    view, name = f"{app}.SV_{tid}_EVENTS", f"{app}.SV_{tid}"
    v_sql, sv_sql = view_sql(spec, view, db), semantic_view_sql(spec, name, view, db, term, run_id)
    session.sql(v_sql).collect()
    session.sql(sv_sql).collect()

    metric = metric_name(term.get("term"))
    sv_value = session.sql(f"SELECT * FROM SEMANTIC_VIEW({name} METRICS {EVENTS}.{metric})").collect()[0][0]
    m = (measure_sql or "").strip().rstrip(";").strip()
    if not re.match(r"^(SELECT|WITH)\b", m, re.IGNORECASE) or ";" in m or "$" * 2 in m:
        raise ValueError("The mapping's measure query is not a single SELECT")
    session.sql(f"USE DATABASE {db}").collect()          # measure_sql names SCHEMA.TABLE only
    measure_now = session.sql(m).collect()[0][0]
    session.sql(f"USE SCHEMA {app}").collect()
    matched = sv_value is not None and measure_now is not None and float(sv_value) == float(measure_now)

    session.sql(
        f"INSERT INTO {app}.SEMANTIC_VIEWS SELECT ?, ?, CURRENT_TIMESTAMP(), ?, ?, "
        "TRY_TO_DOUBLE(NULLIF(?, '')), TRY_TO_DOUBLE(NULLIF(?, '')), ?, PARSE_JSON(?), ?",
        params=[tid, run_id, name, view, _nz(sv_value), _nz(measure_now), matched,
                json.dumps(spec["ignored"]), v_sql + ";\n\n" + sv_sql + ";"],
    ).collect()
    return {"semantic_view": name, "metric": f"{EVENTS}.{metric}", "mapping_run": run_id,
            "semantic_view_value": sv_value, "mapping_measure_now": measure_now, "matched": matched,
            "sources": [s["table"] for s in spec["sources"]], "ignored_components": spec["ignored"]}

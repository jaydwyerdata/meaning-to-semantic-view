"""Unit tests for the stored procedure code, run locally with no Snowflake account.

Loads each handler exactly as tools/build_sql.py inlines it, so the tested code is the deployed
code. A fake session stands in for Snowpark and answers the SQL each procedure issues.

    python -m unittest discover -s tests
"""
import json
import re
import sys
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_sql  # noqa: E402


def load(module: str) -> dict:
    ns: dict = {}
    exec(compile(build_sql.handler_source(module), module, "exec"), ns)
    return ns


MT = load("map_term.py")
PE = load("profile_estate.py")


class Row(tuple):
    """Enough of snowpark.Row: a tuple of values (so unpacking and [i] work) plus as_dict()."""
    def __new__(cls, d: dict):
        row = super().__new__(cls, d.values())
        row._d = dict(d)
        return row

    def as_dict(self):
        return dict(self._d)


class Result:
    def __init__(self, rows):
        self.rows = rows

    def collect(self):
        return self.rows


PROFILE = [
    {"TABLE_SCHEMA": "LOY", "TABLE_NAME": "MBR", "COLUMN_NAME": "MBR_ID", "ORDINAL": 1,
     "DATA_TYPE": "NUMBER(10,0)", "ROW_COUNT": 100, "NON_NULL": 100, "DISTINCT_APPROX": 100,
     "MIN_VALUE": "1", "MAX_VALUE": "100", "DAYS_SINCE_MAX": None, "TOP_VALUES": "[[1,1]]"},
    {"TABLE_SCHEMA": "LOY", "TABLE_NAME": "MBR", "COLUMN_NAME": "CARD_STAT", "ORDINAL": 2,
     "DATA_TYPE": "VARCHAR(3)", "ROW_COUNT": 100, "NON_NULL": 100, "DISTINCT_APPROX": 3,
     "MIN_VALUE": "ACT", "MAX_VALUE": "LST", "DAYS_SINCE_MAX": None,
     "TOP_VALUES": '[["ACT", 90], ["LST", 5], ["CLS", 5]]'},
    {"TABLE_SCHEMA": "ERP", "TABLE_NAME": "CUSMST", "COLUMN_NAME": "LSTPURDT", "ORDINAL": 7,
     "DATA_TYPE": "DATE", "ROW_COUNT": 100, "NON_NULL": 60, "DISTINCT_APPROX": 80,
     "MIN_VALUE": "2024-01-01", "MAX_VALUE": "2026-04-06", "DAYS_SINCE_MAX": 180, "TOP_VALUES": "[]"},
]

PROPOSAL = {
    "entity": {"table": "LOY.MBR", "key_columns": ["MBR_ID"], "counted_per": "one member",
               "evidence": [{"kind": "metadata", "detail": "one row per MBR_ID"}]},
    "components": [], "rejected": [], "questions_for_business": ["Does a click count as an open?"],
    "measure_sql": "SELECT COUNT(*) FROM LOY.MBR",
}


class FakeSession:
    def __init__(self, role="SVC_MAPPER", secondary='{"roles":"","value":""}', models=None,
                 proposal=PROPOSAL, history=None, structured_nulls=0, plain_reply=None):
        self.structured_nulls, self.plain_reply, self.structured_calls = structured_nulls, plain_reply, 0
        self.role, self.secondary = role, secondary
        self.models = models if models is not None else [
            Row({"name": "CLAUDE-SONNET-5", "lifecycle_status": "GA"}),
            Row({"name": "CLAUDE-4-SONNET", "lifecycle_status": "LEGACY"})]
        self.proposal, self.history = proposal, history or []
        self.calls, self.inserted, self.prompt = [], None, None

    def sql(self, q, params=None):
        self.calls.append((q, params))
        if q.startswith("SELECT CURRENT_ROLE()"):
            return Result([Row({"r": self.role, "s": self.secondary})])
        if q.startswith("SELECT CURRENT_DATABASE()"):
            return Result([Row({"d": "SVC_APP", "s": "MAPPER"})])
        if q.startswith("SHOW CORTEX BASE MODELS"):
            return Result(self.models)
        if "GLOSSARY" in q:
            return Result([Row({"TERM": json.dumps({"id": "T3", "term": "engaged member"})})])
        if "COLUMN_PROFILE" in q:
            return Result([Row(p) for p in PROFILE])
        if "ACCOUNT_USAGE.QUERY_HISTORY" in q:
            return Result([Row(h) for h in self.history])
        if q.startswith("SELECT AI_COMPLETE") and "'type': 'json'" not in q:
            self.prompt = params[0]
            return Result([Row({"r": self.plain_reply})])
        if q.startswith("SELECT AI_COMPLETE"):
            self.prompt = params[0]
            self.structured_calls += 1
            if self.structured_calls <= self.structured_nulls:
                return Result([Row({"r": None})])
            return Result([Row({"r": json.dumps({"structured_output": [{"raw_message": self.proposal}],
                                                 "usage": {"input_tokens": 10}})})])
        if q.startswith("USE "):
            return Result([])
        if q.startswith("SELECT COUNT(*) FROM LOY.MBR"):
            return Result([Row({"n": 42})])
        if "PROPOSALS" in q:
            self.inserted = params
            return Result([])
        raise AssertionError(f"Unexpected SQL: {q[:80]}")


class CommonTests(unittest.TestCase):
    def test_identifiers(self):
        self.assertEqual(MT["check_ident"]("ALDERGLEN_RAW"), "ALDERGLEN_RAW")
        for bad in ["x; DROP TABLE y", "a.b", "", "1ABC", '"Q"']:
            with self.assertRaises(ValueError):
                MT["check_ident"](bad)

    def test_secondary_roles(self):
        self.assertTrue(MT["secondary_roles_off"]('{"roles":"","value":""}'))
        self.assertFalse(MT["secondary_roles_off"]('{"roles":"ALL","value":"ALL"}'))
        self.assertFalse(MT["secondary_roles_off"]("not json"))


class MapTermUnitTests(unittest.TestCase):
    def test_schema_is_a_valid_sql_object_constant(self):
        lit = MT["schema_literal"](MT["RESPONSE_SCHEMA"])
        self.assertNotIn('"', lit)
        self.assertTrue(lit.startswith("{'type': 'object'"))

    def test_schema_keys_follow_cortex_rules(self):
        def walk(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertFalse(node.get("additionalProperties", True))
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                    for k in node["properties"]:
                        self.assertRegex(k, r"^[A-Za-z0-9_-]{1,64}$")
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        walk(MT["RESPONSE_SCHEMA"])

    def test_catalog_shows_codes_and_staleness(self):
        cat = MT["format_catalog"](PROFILE)
        self.assertIn("LOY.MBR (100 rows)", cat)
        self.assertIn("top: ACT (90%), LST (5%), CLS (5%)", cat)
        self.assertIn("latest value 180 days ago", cat)
        self.assertIn("nulls 40%", cat)
        self.assertNotIn("top: 1 (1%)", cat)  # high-cardinality columns get no top values

    def test_extract_structured_shapes(self):
        ex = MT["extract_structured"]
        self.assertEqual(ex({"structured_output": [{"raw_message": {"a": 1}}]}), {"a": 1})
        self.assertEqual(ex(json.dumps({"structured_output": {"a": 1}})), {"a": 1})
        self.assertEqual(ex({"structured_output": [{"raw_message": '{"a": 1}'}]}), {"a": 1})

    def test_safe_select(self):
        ok = MT["safe_select"]
        self.assertEqual(ok("SELECT COUNT(*) FROM LOY.MBR;"), "SELECT COUNT(*) FROM LOY.MBR")
        self.assertTrue(ok("WITH a AS (SELECT 1) SELECT * FROM a").startswith("WITH"))
        for bad in ["DELETE FROM LOY.MBR", "SELECT 1; DROP TABLE X", "SELECT 1 FROM X WHERE 1=1 UNION ALL "
                    "SELECT 1 FROM (CREATE TABLE Y)", "", None, "CALL X()"]:
            with self.assertRaises(ValueError):
                ok(bad)

    def test_ga_models(self):
        rows = [{'"name"': "A", '"lifecycle_status"': "GA"}, {"name": "B", "lifecycle_status": "LEGACY"}]
        self.assertEqual(MT["ga_models"](rows), {"A"})

    def test_prompt_drops_id_and_marks_missing_history(self):
        p = MT["build_prompt"]({"id": "T3", "term": "engaged member"}, "CAT", "")
        self.assertNotIn('"id"', p)
        self.assertIn("QUERY HISTORY: not provided", p)


class MapTermEndToEnd(unittest.TestCase):
    def test_happy_path_records_run(self):
        s = FakeSession(history=[{"QUERY_TEXT": "SELECT 1 FROM LOY.MBR", "RUNS": 2, "USERS": 1}])
        out = MT["main"](s, "T3", "claude-sonnet-5", True, "ALDERGLEN_RAW", None)
        self.assertEqual(out["measure_value"], 42.0)
        self.assertEqual(out["history_queries"], 1)
        self.assertIn("-- run 2 time(s)", s.prompt)
        self.assertEqual(s.inserted[1:6], ["T3", "CLAUDE-SONNET-5", True, len(s.prompt), 1])
        self.assertEqual(s.calls[-2][0], "USE SCHEMA SVC_APP.MAPPER")  # context restored
        hist_sql = next(q for q, _ in s.calls if "QUERY_HISTORY" in q)
        for excluded in ("'SVC_BUILD'", "'SVC_EVAL'", "'SVC_MAPPER'", "'SVC_EVALUATOR'"):
            self.assertIn(excluded, hist_sql)
        self.assertIn("QUERY_TYPE = 'SELECT'", hist_sql)

    def test_history_tag_restricts_history_query(self):
        s = FakeSession(history=[{"QUERY_TEXT": "SELECT 1 FROM LOY.MBR", "RUNS": 1, "USERS": 1}])
        MT["main"](s, "T3", "CLAUDE-SONNET-5", True, "ALDERGLEN_RAW", "SVC_WORKLOAD")
        hist_sql, params = next((q, p) for q, p in s.calls if "QUERY_HISTORY" in q)
        self.assertIn("AND QUERY_TAG = ?", hist_sql)
        self.assertEqual(params, ["ALDERGLEN_RAW", "SVC_WORKLOAD"])
        self.assertIn("history restricted to query tag SVC_WORKLOAD", s.inserted[-1])

    def test_no_history_tag_leaves_query_unrestricted(self):
        s = FakeSession(history=[{"QUERY_TEXT": "SELECT 1 FROM LOY.MBR", "RUNS": 1, "USERS": 1}])
        MT["main"](s, "T3", "CLAUDE-SONNET-5", True, "ALDERGLEN_RAW", None)
        hist_sql, params = next((q, p) for q, p in s.calls if "QUERY_HISTORY" in q)
        self.assertNotIn("AND QUERY_TAG = ?", hist_sql)
        self.assertEqual(params, ["ALDERGLEN_RAW"])

    def test_structured_nulls_then_success_records_retries(self):
        s = FakeSession(structured_nulls=2)
        with mock.patch.object(MT["time"], "sleep") as sleeper:
            out = MT["main"](s, "T3", "CLAUDE-SONNET-5", False, "ALDERGLEN_RAW", None)
        self.assertEqual(s.structured_calls, 3)
        self.assertEqual(sleeper.call_count, 2)
        self.assertEqual(out["measure_value"], 42.0)
        self.assertIn("NULL or empty 2 time(s)", s.inserted[-1])

    def test_all_structured_nulls_fall_back_to_a_plain_reply(self):
        s = FakeSession(structured_nulls=99, plain_reply="```json\n" + json.dumps(PROPOSAL) + "\n```")
        with mock.patch.object(MT["time"], "sleep"):
            out = MT["main"](s, "T3", "CLAUDE-SONNET-5", False, "ALDERGLEN_RAW", None)
        self.assertEqual(s.structured_calls, MT["MODEL_ATTEMPTS"])
        self.assertEqual(out["measure_value"], 42.0)
        self.assertIn("parsed from a plain reply", s.inserted[-1])
        self.assertIn("conforms to this JSON schema", s.prompt)

    def test_total_failure_reports_what_the_plain_reply_was(self):
        s = FakeSession(structured_nulls=99, plain_reply="Sorry, I cannot do that.")
        with mock.patch.object(MT["time"], "sleep"):
            with self.assertRaises(ValueError) as cm:
                MT["main"](s, "T3", "CLAUDE-SONNET-5", False, "ALDERGLEN_RAW", None)
        self.assertIn("plain-reply fallback returned", str(cm.exception))
        self.assertIn("Sorry, I cannot do that", str(cm.exception))
        self.assertIsNone(s.inserted)                         # nothing recorded for a failed run

    def test_parse_json_reply(self):
        pj = MT["parse_json_reply"]
        # Seen in Snowflake: the plain reply arrives as a VARIANT string, i.e. quoted and escaped JSON text.
        self.assertEqual(pj(json.dumps('{\n  "entity": {"table": "LOY.MBR"}\n}')), {"entity": {"table": "LOY.MBR"}})
        self.assertEqual(pj(json.dumps('```json\n{"a": 1}\n```')), {"a": 1})
        self.assertEqual(pj('Here you go: {"a": 1} done'), {"a": 1})
        self.assertEqual(pj('```json\n{"a": 1}\n```'), {"a": 1})
        for bad in [None, "", "no json", "{broken", "[1, 2]"]:
            self.assertIsNone(pj(bad))

    def test_without_history_skips_query_history(self):
        s = FakeSession()
        MT["main"](s, "T3", "CLAUDE-SONNET-5", False, "ALDERGLEN_RAW", None)
        self.assertFalse(any("QUERY_HISTORY" in q for q, _ in s.calls))
        self.assertIn("QUERY HISTORY: not provided", s.prompt)

    def test_refuses_without_isolation(self):
        with self.assertRaises(PermissionError):
            MT["main"](FakeSession(role="SYSADMIN"), "T3", "CLAUDE-SONNET-5", False, "ALDERGLEN_RAW", None)
        with self.assertRaises(PermissionError):
            MT["main"](FakeSession(secondary='{"roles":"ALL"}'), "T3", "CLAUDE-SONNET-5", False, "ALDERGLEN_RAW", None)

    def test_rejects_non_ga_model(self):
        with self.assertRaises(ValueError):
            MT["main"](FakeSession(), "T3", "CLAUDE-4-SONNET", False, "ALDERGLEN_RAW", None)

    def test_bad_measure_is_recorded_not_raised(self):
        bad = dict(PROPOSAL, measure_sql="DELETE FROM LOY.MBR")
        out = MT["main"](FakeSession(proposal=bad), "T3", "CLAUDE-SONNET-5", False, "ALDERGLEN_RAW", None)
        self.assertIsNone(out["measure_value"])
        self.assertIn("read-only", out["measure_error"])


class ProfileTests(unittest.TestCase):
    def test_profile_sql_scans_each_table_once(self):
        sql = PE["table_profile_sql"]("DB", "LOY", "MBR", [("MBR_ID", "NUMBER"), ("ENRL_DT", "DATE")])
        self.assertEqual(sql.count("FROM DB.LOY.MBR"), 1)
        self.assertIn("APPROX_TOP_K(\"ENRL_DT\", 8)", sql)
        self.assertIn("DATEDIFF('day', MAX(\"ENRL_DT\"), CURRENT_DATE())", sql)
        self.assertEqual(sql.count("DATEDIFF"), 1)

    def test_type_labels(self):
        self.assertEqual(PE["type_label"]("NUMBER", 10, 0, None), "NUMBER(10,0)")
        self.assertEqual(PE["type_label"]("TEXT", None, None, 40), "VARCHAR(40)")
        self.assertEqual(PE["type_label"]("DATE", None, None, None), "DATE")


class GeneratedSqlTests(unittest.TestCase):
    def test_generated_sql_is_current(self):
        self.assertEqual((ROOT / "sql" / "05_glossary.sql").read_text(), build_sql.glossary_sql())
        self.assertEqual((ROOT / "sql" / "06_procedures.sql").read_text(), build_sql.procedures_sql())

    def test_glossary_names_no_estate_columns(self):
        ddl = (ROOT / "sql" / "01_setup_and_ddl.sql").read_text()
        names = set(re.findall(r"^\s+([A-Z][A-Z0-9_]{2,})\s+(?:NUMBER|VARCHAR|CHAR|DATE|TIMESTAMP)", ddl, re.M))
        names |= set(re.findall(r"TABLE \w+\.(\w+)", ddl))
        text = (ROOT / "glossary" / "terms.yaml").read_text().upper()
        business_words = {"SKU"}  # the Store Ops manager's own word, which happens to be a column name too
        leaked = sorted(n for n in names - business_words if re.search(rf"\b{n}\b", text))
        self.assertEqual(leaked, [], f"glossary names estate objects: {leaked}")


if __name__ == "__main__":
    unittest.main()

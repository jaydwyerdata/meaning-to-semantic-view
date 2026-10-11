"""Unit tests for GENERATE_SEMANTIC_VIEW, run locally with no Snowflake account.

Loads the handler exactly as tools/build_sql.py inlines it, and runs the shape extraction against the
13 real proposals the mapper produced in Snowflake on 7 and 9 October 2026 (tests/fixtures, trimmed to
the fields the generator reads).

    python -m unittest discover -s tests
"""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_sql  # noqa: E402

NS: dict = {}
exec(compile(build_sql.handler_source("semantic_view.py"), "semantic_view.py", "exec"), NS)
FIXTURES = json.loads((ROOT / "tests" / "fixtures" / "proposals_2026-10.json").read_text())
Unsupported = NS["Unsupported"]


def runs(term_id, use_history=None):
    return [r for r in FIXTURES if r["term_id"] == term_id and (use_history is None or r["use_history"] == use_history)]


TERM = {"term": "engaged member", "owner": "Loyalty", "counted_per": "one member",
        "definition": "Redeemed points or opened a programme email in the last 60 days.",
        "synonyms": ["active loyalty member"]}


class ShapeExtraction(unittest.TestCase):
    def test_every_engaged_member_run_is_supported_with_the_same_two_sources(self):
        for r in runs("T3") + runs("T3I"):
            spec = NS["build_spec"](r["proposal"])
            self.assertEqual(spec["entity_table"], "LOY.MBR")
            self.assertEqual(spec["key"], "MBR_ID")
            self.assertEqual([s["table"] for s in spec["sources"]], ["LOY.EML_EVT", "LOY.PTS_TXN"])
            by = {s["table"]: s for s in spec["sources"]}
            self.assertEqual(by["LOY.PTS_TXN"]["column"], "TXN_DT")
            self.assertEqual(by["LOY.EML_EVT"]["column"], "EVT_TS")
            self.assertEqual({s["days"] for s in spec["sources"]}, {60})
            self.assertEqual(by["LOY.PTS_TXN"]["filters"], ["LOY.PTS_TXN.TXN_CD = 'RDM'"])
            self.assertEqual(by["LOY.EML_EVT"]["filters"], ["LOY.EML_EVT.EVT_TYP = 'OPN'"])

    def test_a_run_with_no_join_components_joins_on_the_shared_key(self):
        r = [x for x in runs("T3", False)][0]
        self.assertFalse(any(c["role"] == "join" for c in r["proposal"]["components"]))
        spec = NS["build_spec"](r["proposal"])
        self.assertEqual({s["join"] for s in spec["sources"]},
                         {"LOY.MBR.MBR_ID = LOY.PTS_TXN.MBR_ID", "LOY.MBR.MBR_ID = LOY.EML_EVT.MBR_ID"})

    def test_a_stray_join_is_ignored_and_reported(self):
        r = runs("T3I", True)[0]
        spec = NS["build_spec"](r["proposal"])
        stray = [i for i in spec["ignored"] if "ERP.CUSMST" in i["expression"]]
        self.assertEqual(len(stray), 1)

    def test_marketing_active_customer_with_history_is_supported(self):
        for r in runs("T1", True):
            spec = NS["build_spec"](r["proposal"])
            self.assertEqual(spec["entity_table"], "ERP.CUSMST")
            self.assertEqual([s["table"] for s in spec["sources"]], ["OMS.ORD_HDR", "POS.TXN_HDR"])
            self.assertIn("ERP.CUSMST.CUSTYP <> 'I'", spec["subject_filters"])
            self.assertIn("OMS.ORD_HDR.ORD_STAT <> 'CNL'", spec["sources"][0]["filters"])

    def test_windows_joined_with_and_are_refused_not_rewritten(self):
        r = [x for x in runs("T1", False) if "AND" in " ".join(
            c["expression"] for c in x["proposal"]["components"] if c["role"] == "time_window")][0]
        with self.assertRaisesRegex(Unsupported, "AND"):
            NS["build_spec"](r["proposal"])

    def test_finance_active_customer_is_refused_because_it_needs_an_aggregate(self):
        for r in runs("T2"):
            with self.assertRaises(Unsupported):
                NS["build_spec"](r["proposal"])

    def test_injection_in_a_filter_is_refused(self):
        p = json.loads(json.dumps(runs("T3I", True)[0]["proposal"]))
        p["components"].append({"role": "filter", "expression": "LOY.PTS_TXN.TXN_CD = 'RDM'); DROP TABLE X; SELECT ('"})
        with self.assertRaises(Unsupported):
            NS["build_spec"](p)

    def test_a_filter_on_a_table_with_no_window_is_refused(self):
        p = json.loads(json.dumps(runs("T3I", True)[0]["proposal"]))
        p["components"].append({"role": "filter", "expression": "LOY.MBR_TIER.TIER = 'GOLD'"})
        with self.assertRaisesRegex(Unsupported, "no time window"):
            NS["build_spec"](p)


class Generation(unittest.TestCase):
    def setUp(self):
        self.spec = NS["build_spec"](runs("T3I", True)[0]["proposal"])

    def test_view_uses_aliases_and_keeps_the_window_live(self):
        sql = NS["view_sql"](self.spec, "SVC_APP.MAPPER.SV_T3I_EVENTS", "ALDERGLEN_RAW")
        body = sql.split("AS\n", 1)[1]
        self.assertEqual(body.count("UNION ALL"), 1)
        self.assertIn("FROM ALDERGLEN_RAW.LOY.PTS_TXN s", body)
        self.assertIn("JOIN ALDERGLEN_RAW.LOY.MBR e ON", body)
        self.assertIn("(s.TXN_DT >= DATEADD(day, -60, CURRENT_DATE()))", body)
        self.assertIn("(s.TXN_CD = 'RDM')", body)
        self.assertNotRegex(body.replace("ALDERGLEN_RAW.LOY.", ""), r"\bLOY\.[A-Z_]+\.")

    def test_semantic_view_has_the_clauses_in_documented_order(self):
        sql = NS["semantic_view_sql"](self.spec, "SVC_APP.MAPPER.SV_T3I", "SVC_APP.MAPPER.SV_T3I_EVENTS",
                                      "ALDERGLEN_RAW", TERM, "run-1")
        order = [sql.index(k) for k in ("TABLES (", "RELATIONSHIPS (", "DIMENSIONS (", "METRICS (", "\n  COMMENT =")]
        self.assertEqual(order, sorted(order))
        self.assertIn("subject AS ALDERGLEN_RAW.LOY.MBR PRIMARY KEY (MBR_ID)", sql)
        self.assertIn("qualifying_events.ENGAGED_MEMBER_COUNT AS COUNT(DISTINCT qualifying_events.ENTITY_KEY)", sql)
        self.assertIn("WITH SYNONYMS = ('active loyalty member')", sql)
        self.assertNotIn("\u2014", sql)

    def test_quotes_in_business_text_are_escaped(self):
        term = dict(TERM, definition="Members who've redeemed", owner="Loyalty's team")
        sql = NS["semantic_view_sql"](self.spec, "A.B.SV", "A.B.V", "RAW", term, "r")
        self.assertIn("'Members who''ve redeemed'", sql)
        self.assertIn("Loyalty''s team", sql)


class Result:
    def __init__(self, rows):
        self.rows = rows

    def collect(self):
        return self.rows


class FakeSession:
    def __init__(self, sv_value=769, measure_value=769):
        self.sv_value, self.measure_value, self.calls, self.inserted = sv_value, measure_value, [], None
        self.proposal = runs("T3I", True)[0]["proposal"]

    def sql(self, text, params=None):
        self.calls.append(text)
        if "CURRENT_ROLE()" in text:
            return Result([("SVC_MAPPER", '{"roles":"","value":""}')])
        if "CURRENT_DATABASE()" in text:
            return Result([("SVC_APP", "MAPPER")])
        if "FROM SVC_APP.MAPPER.GLOSSARY" in text:
            return Result([(json.dumps(TERM),)])
        if "FROM SVC_APP.MAPPER.PROPOSALS" in text:
            return Result([("run-1", json.dumps(self.proposal), self.proposal["measure_sql"])])
        if text.startswith("CREATE OR REPLACE") or text.startswith("USE "):
            return Result([])
        if text.startswith("SELECT * FROM SEMANTIC_VIEW("):
            return Result([(self.sv_value,)])
        if text.startswith("SELECT COUNT(DISTINCT"):
            return Result([(self.measure_value,)])
        if text.startswith("INSERT INTO SVC_APP.MAPPER.SEMANTIC_VIEWS"):
            self.inserted = params
            return Result([])
        raise AssertionError(f"Unexpected SQL: {text[:120]}")


class Procedure(unittest.TestCase):
    def test_creates_queries_compares_and_records(self):
        s = FakeSession()
        out = NS["main"](s, "T3I", True, "ALDERGLEN_RAW")
        self.assertTrue(out["matched"])
        self.assertEqual(out["semantic_view"], "SVC_APP.MAPPER.SV_T3I")
        self.assertTrue(any(c.startswith("CREATE OR REPLACE SEMANTIC VIEW SVC_APP.MAPPER.SV_T3I\n") for c in s.calls))
        self.assertIn("SELECT * FROM SEMANTIC_VIEW(SVC_APP.MAPPER.SV_T3I METRICS qualifying_events.ENGAGED_MEMBER_COUNT)", s.calls)
        self.assertEqual(s.inserted[6], True)

    def test_a_mismatch_is_recorded_not_hidden(self):
        s = FakeSession(sv_value=700)
        out = NS["main"](s, "T3I", True, "ALDERGLEN_RAW")
        self.assertFalse(out["matched"])
        self.assertEqual(s.inserted[6], False)

    def test_refuses_without_isolation(self):
        s = FakeSession()
        s.sql = lambda text, params=None: Result([("ACCOUNTADMIN", '{"roles":"ALL"}')])
        with self.assertRaises(PermissionError):
            NS["main"](s, "T3I", True, "ALDERGLEN_RAW")

    def test_term_id_is_checked_before_it_reaches_sql(self):
        with self.assertRaises(ValueError):
            NS["main"](FakeSession(), "T3I; DROP", True, "ALDERGLEN_RAW")


if __name__ == "__main__":
    unittest.main()

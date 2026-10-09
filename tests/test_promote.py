"""Unit tests for PROMOTE_TERM, run locally with no Snowflake account.

Loads the handler exactly as tools/build_sql.py inlines it (common.py, interview.py, promote_term.py),
so the tested code is the deployed code.

    python -m unittest discover -s tests
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_sql  # noqa: E402

NS: dict = {}
exec(compile(build_sql.handler_source("promote_term.py", ["interview.py"]), "promote_term.py", "exec"), NS)

FULL = {
    "term": "engaged member", "owner": "Loyalty", "said_by": "Loyalty Programme Manager",
    "definition": "Redeemed points or opened a programme email in the last 60 days, not just an active card.",
    "counted_per": "one member",
    "questions": ["How many engaged members do we have?", "What share of members are engaged?"],
}


class Result:
    def __init__(self, rows):
        self.rows = rows

    def collect(self):
        return self.rows


class FakeSession:
    def __init__(self, status="CONFIRMED", term=None, existing=False, denylist=("CARD_STAT", "MBR")):
        self.status, self.term = status, json.dumps(term if term is not None else FULL)
        self.existing, self.denylist, self.inserts = existing, list(denylist), []
        self.role = ("SVC_MAPPER", '{"roles":"","value":""}')

    def sql(self, text, params=None):
        if "CURRENT_ROLE()" in text:
            return Result([self.role])
        if "INTERVIEW.TERM_DRAFTS" in text:
            return Result([(self.status, self.term)] if params[0] == "D1" else [])
        if "FROM SVC_APP.MAPPER.GLOSSARY" in text:
            return Result([(1,)] if self.existing else [])
        if "COLUMN_PROFILE" in text:
            return Result([(n,) for n in self.denylist])
        if text.startswith("INSERT INTO"):
            self.inserts.append((text, params))
            return Result([])
        raise AssertionError(f"Unexpected SQL: {text}")


class PromoteTerm(unittest.TestCase):
    def test_confirmed_draft_lands_in_glossary_and_promotions(self):
        s = FakeSession()
        out = NS["main"](s, "D1", "T3I")
        self.assertEqual(out["term_id"], "T3I")
        self.assertEqual(len(s.inserts), 2)
        glossary_sql, glossary_params = s.inserts[0]
        self.assertIn("MAPPER.GLOSSARY", glossary_sql)
        self.assertEqual(json.loads(glossary_params[1])["id"], "T3I")
        self.assertIn("MAPPER.PROMOTIONS", s.inserts[1][0])

    def test_unconfirmed_draft_is_refused(self):
        with self.assertRaises(ValueError):
            NS["main"](FakeSession(status="DRAFT"), "D1", "T3I")

    def test_missing_draft_is_refused(self):
        with self.assertRaises(ValueError):
            NS["main"](FakeSession(), "NOPE", "T3I")

    def test_existing_term_id_is_not_overwritten(self):
        s = FakeSession(existing=True)
        with self.assertRaises(ValueError):
            NS["main"](s, "D1", "T3")
        self.assertEqual(s.inserts, [])

    def test_catalog_names_are_refused(self):
        s = FakeSession(term=dict(FULL, definition="Anyone whose CARD_STAT is fine, or who redeemed."))
        with self.assertRaises(ValueError):
            NS["main"](s, "D1", "T3I")
        self.assertEqual(s.inserts, [])

    def test_incomplete_draft_is_refused(self):
        with self.assertRaises(ValueError):
            NS["main"](FakeSession(term={"term": "engaged member"}), "D1", "T3I")

    def test_wrong_role_is_refused(self):
        s = FakeSession()
        s.role = ("ACCOUNTADMIN", '{"roles":"","value":""}')
        with self.assertRaises(PermissionError):
            NS["main"](s, "D1", "T3I")


if __name__ == "__main__":
    unittest.main()

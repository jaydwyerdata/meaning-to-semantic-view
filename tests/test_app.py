"""Offline test of the Streamlit interview app, driven by Streamlit's own AppTest with a fake Snowpark
session. Skipped where streamlit is not installed. Run: python -m unittest discover -s tests"""
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_app  # noqa: E402


class Result:
    def __init__(self, rows):
        self.rows = rows

    def collect(self):
        return self.rows


class FakeSession:
    """extractions: one dict (or None for a failed call) per user message. questions: model replies in order."""

    def __init__(self, extractions=(), questions=()):
        self.extractions, self.questions = list(extractions), list(questions)
        self.turns, self.merges, self.extract_calls = [], [], 0

    def sql(self, q, params=None):
        if "AI_COMPLETE" in q and "'type': 'json'" in q:
            self.extract_calls += 1
            e = self.extractions.pop(0) if self.extractions else None
            if e is None:
                return Result([(None,)])
            return Result([(json.dumps({"structured_output": [{"raw_message": e}]}),)])
        if "AI_COMPLETE" in q:
            return Result([(self.questions.pop(0) if self.questions else "",)])
        if "SCHEMA_DENYLIST" in q:
            return Result([("CUSMST",), ("TXN_CD",)])
        if "INTERVIEW_TURNS" in q:
            self.turns.append(params)
            return Result([])
        if "MERGE INTO" in q:
            self.merges.append(params)
            return Result([])
        raise AssertionError(f"Unexpected SQL: {q[:80]}")


def run_app(fake):
    app_file = ROOT / "app" / "interview_app.py"
    app_file.write_text(build_app.build())
    mod = types.ModuleType("snowflake.snowpark.context")
    mod.get_active_session = lambda: fake
    stubs = {"snowflake": types.ModuleType("snowflake"), "snowflake.snowpark": types.ModuleType("snowflake.snowpark"),
             "snowflake.snowpark.context": mod}
    patcher = mock.patch.dict(sys.modules, stubs)
    patcher.start()
    sleeper = mock.patch("time.sleep")
    sleeper.start()
    at = AppTest.from_file(str(app_file), default_timeout=30)
    at._patchers = (patcher, sleeper)
    return at.run()


def say(at, text):
    at.chat_input[0].set_value(text).run()
    return at


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class InterviewApp(unittest.TestCase):
    def tearDown(self):
        for p in getattr(self, "at", None) and self.at._patchers or ():
            p.stop()

    def test_full_interview_to_confirmation(self):
        fake = FakeSession(
            extractions=[{"term": "engaged member"}, {"owner": "Loyalty"}, {"said_by": "Programme Manager"},
                         {"definition": "Redeemed points or opened a programme email in the last 60 days."},
                         {"counted_per": "one member"},
                         {"questions": ["How many engaged members do we have?", "What share are engaged?"]}],
            questions=["Which team owns it?", "What is your role?", "When does a member count as engaged?",
                       "What is one of them?", "What questions do people ask?", "Is anything left out?"])
        self.at = at = run_app(fake)
        self.assertFalse(at.exception)
        self.assertIn("Hello", at.chat_message[0].markdown[0].value)
        for line in ["engaged member", "Loyalty", "Programme Manager",
                     "Redeemed points or opened an email in the last 60 days", "one member",
                     "How many engaged members do we have? What share are engaged?"]:
            say(at, line)
            self.assertFalse(at.exception)
        self.assertEqual(at.session_state["draft"]["term"], "engaged member")
        self.assertEqual(len(at.session_state["draft"]["questions"]), 2)
        at.sidebar.button[0].click().run()                       # "That is enough, show me the summary"
        self.assertEqual(at.session_state["stage"], "readback")
        self.assertIn('The term is "engaged member", owned by Loyalty.', at.info[0].value)
        at.button[0].click().run()                               # "Yes, that is right"
        self.assertEqual(at.session_state["stage"], "done")
        self.assertTrue(at.success)
        self.assertEqual(json.loads(fake.merges[-1][3])["owner"], "Loyalty")
        self.assertEqual(fake.merges[-1][2], "CONFIRMED")
        self.assertGreaterEqual(len(fake.turns), 12)             # every turn, both speakers, is stored

    def test_schema_words_are_refused_and_never_stored(self):
        fake = FakeSession(extractions=[{"term": "engaged member"}])
        self.at = at = run_app(fake)
        say(at, "engaged member")
        say(at, "it is TXN_CD = 'RDM'")
        self.assertEqual(fake.extract_calls, 1)                  # the technical message was not even extracted
        last = at.session_state["turns"][-1]["content"]
        self.assertIn("everyday business words", last)
        self.assertNotIn("TXN_CD", json.dumps(at.session_state["draft"]))

    def test_failed_extraction_falls_back_to_the_users_words(self):
        fake = FakeSession(extractions=[None, None, None, None])
        self.at = at = run_app(fake)
        say(at, "engaged member")
        self.assertEqual(at.session_state["draft"].get("term"), "engaged member")
        say(at, "Loyalty")
        self.assertEqual(at.session_state["draft"].get("owner"), "Loyalty")

    def test_model_question_with_schema_words_is_replaced(self):
        fake = FakeSession(extractions=[{"term": "engaged member"}], questions=["Which column in CUSMST holds the owner?"])
        self.at = at = run_app(fake)
        say(at, "engaged member")
        question = at.session_state["turns"][-1]["content"]
        self.assertNotIn("CUSMST", question)
        self.assertEqual(question, "Which team owns this term?")

    def test_empty_model_question_uses_the_fixed_prompt(self):
        fake = FakeSession(extractions=[{"term": "engaged member"}], questions=[])
        self.at = at = run_app(fake)
        say(at, "engaged member")
        self.assertEqual(at.session_state["turns"][-1]["content"], "Which team owns this term?")


if __name__ == "__main__":
    unittest.main()

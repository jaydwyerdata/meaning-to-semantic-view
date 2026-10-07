"""Offline tests for python/interview.py. Run: python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import interview as iv  # noqa: E402

FULL = {
    "term": "engaged member", "owner": "Loyalty", "said_by": "Loyalty Programme Manager",
    "definition": "Redeemed points or opened a programme email in the last 60 days, not just an active card.",
    "counted_per": "one member",
    "questions": ["How many engaged members do we have?", "What share of members are engaged?"],
}


class Completeness(unittest.TestCase):
    def test_empty_draft_misses_everything_required(self):
        self.assertEqual(iv.missing_fields({}), iv.REQUIRED)

    def test_questions_need_two(self):
        d = dict(FULL, questions=["Only one?"])
        self.assertEqual(iv.missing_fields(d), ["questions"])
        self.assertFalse(iv.can_confirm(d))

    def test_blank_strings_do_not_count(self):
        self.assertIn("definition", iv.missing_fields(dict(FULL, definition="   ")))

    def test_full_draft_can_confirm(self):
        self.assertTrue(iv.can_confirm(FULL))

    def test_checklist_orders_required_first_then_each_optional_once(self):
        self.assertEqual(iv.next_focus({}), "term")
        self.assertEqual(iv.next_focus(FULL), "excludes")
        self.assertEqual(iv.next_focus(FULL, asked_optional=("excludes",)), "synonyms")
        done = ("excludes", "synonyms", "broken_down_by", "systems_mentioned", "why_it_matters")
        self.assertIsNone(iv.next_focus(FULL, asked_optional=done))
        self.assertTrue(iv.is_complete(FULL, asked_optional=done))


class Merge(unittest.TestCase):
    def test_empty_extraction_never_erases(self):
        out = iv.merge_extraction(FULL, {"definition": "", "questions": [], "owner": None})
        self.assertEqual(out, FULL)

    def test_new_values_replace_and_strings_are_tidied(self):
        out = iv.merge_extraction({"term": "x"}, {"term": "  engaged   member ", "synonyms": ["active member", " "]})
        self.assertEqual(out["term"], "engaged member")
        self.assertEqual(out["synonyms"], ["active member"])

    def test_unknown_fields_are_ignored(self):
        self.assertNotIn("table", iv.merge_extraction({}, {"table": "LOY.MBR"}))


class SchemaWords(unittest.TestCase):
    def test_flags_shapes_and_denylist(self):
        self.assertEqual(iv.find_schema_words("count rows in LOY.MBR"), ["LOY.MBR"])
        self.assertEqual(iv.find_schema_words("where TXN_CD is RDM"), ["TXN_CD"])
        self.assertEqual(iv.find_schema_words("the card status flag", denylist=["card status"]), ["card status"])

    def test_plain_business_language_passes(self):
        text = "Someone counts as active if they placed an order in the last 90 days, online or in store."
        self.assertEqual(iv.find_schema_words(text, denylist=["CUSMST", "TXN_CD"]), [])

    def test_denylist_is_word_bounded(self):
        self.assertEqual(iv.find_schema_words("a customer is great", denylist=["CUS"]), [])


class Prompts(unittest.TestCase):
    def test_system_prompt_forbids_schema_and_asks_one_question(self):
        p = iv.build_system_prompt({"term": "engaged member"}, "owner")
        self.assertIn("Never mention tables, columns", p)
        self.assertIn("exactly one short question", p)
        self.assertIn("engaged member", p)
        self.assertIn("owner", p)

    def test_extraction_prompt_carries_the_conversation(self):
        p = iv.build_extraction_prompt([{"speaker": "assistant", "content": "Who owns it?"},
                                         {"speaker": "user", "content": "Loyalty."}])
        self.assertIn("USER: Loyalty.", p)


class ReadbackAndPromotion(unittest.TestCase):
    def test_readback_is_plain_sentences(self):
        r = iv.readback(FULL)
        self.assertIn('The term is "engaged member", owned by Loyalty.', r)
        self.assertIn("  - How many engaged members do we have?", r)

    def test_promotion_shape_matches_glossary(self):
        e = iv.to_glossary_term(FULL, "T7")
        self.assertEqual(e["id"], "T7")
        self.assertEqual(e["counted_per"], "one member")
        self.assertNotIn("excludes", e)

    def test_promotion_refuses_incomplete_drafts(self):
        with self.assertRaises(ValueError):
            iv.to_glossary_term({"term": "x"}, "T7")

    def test_promotion_refuses_schema_words(self):
        with self.assertRaises(ValueError):
            iv.to_glossary_term(dict(FULL, definition="TXN_CD = 'RDM' in LOY.PTS_TXN"), "T7")


if __name__ == "__main__":
    unittest.main()

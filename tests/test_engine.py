"""Checks rendering behavior that the validator can't: what goes in the motion and what's reported as a gap.

Run from the repo root:  python3 -m unittest discover tests
"""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import engine as E  # noqa: E402
import render as R  # noqa: E402

STATE = {"q_filing_court": "ak"}
FEDERAL = {"q_filing_court": "9th_cir"}


class StatementApplicableCourts(unittest.TestCase):
    def setUp(self):
        self.config, _questions, issues = E.load_repo(ROOT)
        issue = next(i for i in issues if i["id"] == "prolonged-stop")
        self.issue = copy.deepcopy(issue)
        # A statement with only Alaska authority, first without and then with applicable_courts.
        self.st = {"id": "alaska_only", "text": "An Alaska-only proposition.",
                   "authorities": [{"type": "statute", "name": "Example statute", "citation": "", "court": "ak"}]}
        self.issue["law_paragraph"]["rule_statements"] = [self.st]

    def render(self, answers):
        return E.render_law_paragraph(self.issue, answers, E.binding_courts(answers), self.config)

    def test_without_field_it_is_a_gap_in_federal_court(self):
        text, _used, gaps = self.render(FEDERAL)
        self.assertEqual(text, "")
        self.assertEqual(gaps, [self.st["text"]])

    def test_limited_to_alaska_it_is_skipped_silently_in_federal_court(self):
        self.st["applicable_courts"] = ["ak"]
        text, _used, gaps = self.render(FEDERAL)
        self.assertEqual((text, gaps), ("", []))

    def test_limited_to_alaska_it_renders_in_state_court(self):
        self.st["applicable_courts"] = ["ak"]
        text, _used, gaps = self.render(STATE)
        self.assertIn("An Alaska-only proposition. Example statute.", text)
        self.assertEqual(gaps, [])

    def test_applicable_but_unsupported_is_still_a_gap(self):
        self.st["applicable_courts"] = ["9th_cir"]
        self.assertEqual(self.render(FEDERAL)[2], [self.st["text"]])
        self.assertEqual(self.render(STATE)[2], [])


class MatchedButNoParagraph(unittest.TestCase):
    """The memo must say whether an empty issue needs research or has a content problem."""

    def setUp(self):
        self.config, _questions, issues = E.load_repo(ROOT)
        self.issue = copy.deepcopy(next(i for i in issues if i["id"] == "passenger-frisk-suspicionless"))
        self.answers = {**FEDERAL, "q_occupant_role": "passenger", "q_passenger_frisked": "yes",
                        "q_frisk_suspicion_basis": "none_articulated"}

    def memo(self):
        result = E.evaluate_session(self.config, [self.issue], {"answers": self.answers})
        self.assertEqual(result["included"], [])
        self.assertEqual(len(result["no_paragraph"]), 1)
        return R.render_memo(result, self.config)

    def test_every_statement_a_gap_says_research_needed(self):
        for st in self.issue["law_paragraph"]["rule_statements"]:
            st["authorities"] = []
        self.assertIn("Research needed", self.memo())

    def test_every_statement_filtered_says_content_problem(self):
        for st in self.issue["law_paragraph"]["rule_statements"]:
            st["when"] = {"question": "q_frisk_suspicion_basis", "op": "equals", "value": "generalized_only"}
        memo = self.memo()
        self.assertIn("problem with the issue's content", memo)
        self.assertNotIn("Research needed", memo)


if __name__ == "__main__":
    unittest.main()

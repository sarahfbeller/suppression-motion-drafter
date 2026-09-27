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


if __name__ == "__main__":
    unittest.main()

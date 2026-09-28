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
        """(markdown paragraph, statements, gaps)"""
        statements, gaps = E.law_paragraph(self.issue, answers, E.binding_courts(answers), self.config)
        return R.paragraph(statements), statements, gaps

    def test_without_field_it_is_a_gap_in_federal_court(self):
        text, _statements, gaps = self.render(FEDERAL)
        self.assertEqual(text, "")
        self.assertEqual(gaps, [self.st["text"]])

    def test_limited_to_alaska_it_is_skipped_silently_in_federal_court(self):
        self.st["applicable_courts"] = ["ak"]
        text, _statements, gaps = self.render(FEDERAL)
        self.assertEqual((text, gaps), ("", []))

    def test_limited_to_alaska_it_renders_in_state_court(self):
        self.st["applicable_courts"] = ["ak"]
        text, _statements, gaps = self.render(STATE)
        self.assertIn("An Alaska-only proposition. Example statute.", text)
        self.assertEqual(gaps, [])

    def test_applicable_but_unsupported_is_still_a_gap(self):
        self.st["applicable_courts"] = ["9th_cir"]
        self.assertEqual(self.render(FEDERAL)[2], [self.st["text"]])
        self.assertEqual(self.render(STATE)[2], [])


class StructuredStatements(unittest.TestCase):
    """The engine returns each statement's text and authorities separately, so a renderer can put
    citations inline or in footnotes."""

    def setUp(self):
        self.config, _questions, issues = E.load_repo(ROOT)
        self.issue = copy.deepcopy(next(i for i in issues if i["id"] == "prolonged-stop"))
        self.issue["law_paragraph"]["rule_statements"] = [{
            "id": "mixed", "text": "A proposition.",
            "authorities": [
                {"type": "statute", "name": "Example statute", "citation": "", "court": "ak"},
                {"type": "case", "name": "Example v. Case", "citation": "1 U.S. 1 (2000)",
                 "pincite": "5", "court": "scotus"},
            ]}]

    def test_statement_keeps_text_and_ordered_authorities_apart(self):
        statements, _gaps = E.law_paragraph(self.issue, STATE, E.binding_courts(STATE), self.config)
        self.assertEqual([st["text"] for st in statements], ["A proposition."])
        self.assertEqual([a["court"] for a in statements[0]["authorities"]], ["scotus", "ak"])

    def test_authorities_filtered_to_forum(self):
        statements, _gaps = E.law_paragraph(self.issue, FEDERAL, E.binding_courts(FEDERAL), self.config)
        self.assertEqual([a["court"] for a in statements[0]["authorities"]], ["scotus"])

    def test_citation_parts_leave_markup_to_the_renderer(self):
        case, statute = self.issue["law_paragraph"]["rule_statements"][0]["authorities"][1::-1]
        self.assertEqual(E.citation_parts(case), {"name": "Example v. Case", "italic": True, "rest": "1 U.S. 1, 5 (2000)"})
        self.assertEqual(E.citation_parts(statute), {"name": "Example statute", "italic": False, "rest": ""})


class MatchedButNoParagraph(unittest.TestCase):
    """The memo must say whether an empty issue needs research or has a content problem."""

    def setUp(self):
        self.config, _questions, issues = E.load_repo(ROOT)
        self.issue = copy.deepcopy(next(i for i in issues if i["id"] == "passenger-frisk-suspicionless"))
        self.answers = {**FEDERAL, "q_encounter_events": ["vehicle_stop", "frisk"], "q_occupant_role": "passenger",
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

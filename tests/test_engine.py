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
GENERIC = "\n\n**[Fill in: Apply the law to your client's facts.]**"
FEDERAL = {"q_filing_court": "9th_cir"}


def case(name, pincite="", **extra):
    return {"type": "case", "name": name, "citation": "1 P.3d 1 (Alaska 2000)", "pincite": pincite,
            "court": "ak", **extra}


class ParagraphApplicableCourts(unittest.TestCase):
    def setUp(self):
        self.config, _questions, issues = E.load_repo(ROOT)
        issue = next(i for i in issues if i["id"] == "prolonged-stop")
        self.issue = copy.deepcopy(issue)
        # A sentence with only Alaska authority, in a paragraph first without and then with applicable_courts.
        self.st = {"id": "alaska_only", "text": "An Alaska-only proposition.",
                   "authorities": [{"type": "statute", "name": "Example statute", "citation": "", "court": "ak"}]}
        self.para = {"id": "p", "sentences": [self.st]}
        self.issue["law_paragraphs"] = [self.para]

    def render(self, answers):
        """(markdown section, paragraphs, gaps)"""
        paragraphs, gaps = E.law_paragraphs(self.issue, answers, E.binding_courts(answers), self.config)
        return R.section(paragraphs), paragraphs, gaps

    def test_without_field_it_is_a_gap_in_federal_court(self):
        text, _paragraphs, gaps = self.render(FEDERAL)
        self.assertEqual(text, "")
        self.assertEqual(gaps, [self.st["text"]])

    def test_limited_to_alaska_it_is_skipped_silently_in_federal_court(self):
        self.para["applicable_courts"] = ["ak"]
        text, _paragraphs, gaps = self.render(FEDERAL)
        self.assertEqual((text, gaps), ("", []))

    def test_limited_to_alaska_it_renders_in_state_court(self):
        self.para["applicable_courts"] = ["ak"]
        text, _paragraphs, gaps = self.render(STATE)
        self.assertIn("An Alaska-only proposition. Example statute.", text)
        self.assertEqual(gaps, [])

    def test_applicable_but_unsupported_is_still_a_gap(self):
        self.para["applicable_courts"] = ["9th_cir"]
        self.assertEqual(self.render(FEDERAL)[2], [self.st["text"]])
        self.assertEqual(self.render(STATE)[2], [])


class Paragraphs(unittest.TestCase):
    def setUp(self):
        self.config, _questions, issues = E.load_repo(ROOT)
        self.issue = copy.deepcopy(next(i for i in issues if i["id"] == "prolonged-stop"))

    def render(self, *paragraphs, answers=STATE):
        self.issue["law_paragraphs"] = list(paragraphs)
        result, gaps = E.law_paragraphs(self.issue, answers, E.binding_courts(answers), self.config)
        return R.section(result), gaps

    def test_paragraphs_are_separated(self):
        text, _ = self.render({"id": "a", "sentences": [{"id": "x", "text": "One.", "authorities": [case("A v. B")]}]},
                              {"id": "b", "sentences": [{"id": "y", "text": "Two.", "authorities": [case("C v. D")]}]})
        self.assertEqual(text, "One. *A v. B*, 1 P.3d 1 (Alaska 2000).\n\nTwo. *C v. D*, 1 P.3d 1 (Alaska 2000)." + GENERIC)

    def test_when_gates_the_whole_paragraph(self):
        para = {"id": "a", "when": {"question": "q_independent_suspicion", "op": "equals", "value": "yes"},
                "sentences": [{"id": "x", "text": "One.", "authorities": [case("A v. B")]}]}
        self.assertEqual(self.render(para, answers={**STATE, "q_independent_suspicion": "no"}), ("", []))
        self.assertIn("One.", self.render(para, answers={**STATE, "q_independent_suspicion": "yes"})[0])

    def test_argument_sentence_renders_without_citation_and_is_not_a_gap(self):
        text, gaps = self.render({"id": "a", "sentences": [
            {"id": "x", "text": "Rule.", "authorities": [case("A v. B")]},
            {"id": "y", "kind": "argument", "text": "So it follows.", "authorities": []}]})
        self.assertEqual(text, "Rule. *A v. B*, 1 P.3d 1 (Alaska 2000). So it follows." + GENERIC)
        self.assertEqual(gaps, [])

    def test_argument_only_paragraph_renders(self):
        text, gaps = self.render({"id": "a", "sentences": [{"id": "x", "text": "Rule.", "authorities": [case("A v. B")]}]},
                                 {"id": "b", "sentences": [{"id": "y", "kind": "argument", "text": "Applied.", "authorities": []}]})
        self.assertEqual(text, "Rule. *A v. B*, 1 P.3d 1 (Alaska 2000).\n\nApplied." + GENERIC)
        self.assertEqual(gaps, [])

    def test_mixed_paragraph_whose_law_was_all_dropped_does_not_render(self):
        text, gaps = self.render({"id": "a", "sentences": [
            {"id": "x", "text": "Rule.", "authorities": []},
            {"id": "y", "kind": "argument", "text": "So it follows.", "authorities": []}]})
        self.assertEqual((text, gaps), ("", ["Rule."]))


class FillIns(unittest.TestCase):
    """Application text the answers can't decide is left to the attorney as a bracketed prompt."""

    def setUp(self):
        self.config, _questions, issues = E.load_repo(ROOT)
        self.issue = copy.deepcopy(next(i for i in issues if i["id"] == "prolonged-stop"))
        self.law = {"id": "law", "sentences": [{"id": "x", "text": "Rule.", "authorities": [case("A v. B")]}]}

    def render(self, *paragraphs, answers=STATE):
        self.issue["law_paragraphs"] = [self.law, *paragraphs]
        return R.section(E.law_paragraphs(self.issue, answers, E.binding_courts(answers), self.config)[0])

    def test_generic_fill_in_ends_every_section(self):
        self.assertTrue(self.render().endswith(GENERIC))

    def test_own_fill_in_replaces_the_generic_one(self):
        text = self.render({"id": "apply", "fill_in": "Explain the hunch."})
        self.assertEqual(text, "Rule. *A v. B*, 1 P.3d 1 (Alaska 2000).\n\n**[Fill in: Explain the hunch.]**")

    def test_generic_comes_back_when_the_own_fill_in_does_not_apply(self):
        text = self.render({"id": "apply", "fill_in": "Explain the hunch.",
                            "when": {"question": "q_independent_suspicion", "op": "equals", "value": "yes"}},
                           answers={**STATE, "q_independent_suspicion": "no"})
        self.assertTrue(text.endswith(GENERIC))
        self.assertNotIn("hunch", text)

    def test_memo_counts_fill_ins(self):
        config, _questions, issues = E.load_repo(ROOT)
        issue = next(i for i in issues if i["id"] == "frisk-without-reasonable-suspicion")
        answers = {**FEDERAL, "q_encounter_events": ["vehicle_stop", "frisk"],
                   "q_occupant_role": "driver", "q_frisk_suspicion_basis": "none_articulated"}
        result = E.evaluate_session(config, [issue], {"answers": answers})
        motion = R.render_motion(result)
        self.assertIn("the motion has 1 bracketed [Fill in: …] prompt.", R.render_memo(result, config, motion))


class Citations(unittest.TestCase):
    """Signals, parentheticals, and Id., as the markdown renderer prints them."""

    def cite(self, *sentences):
        return R.section([{"id": "p", "sentences": [
            {"id": f"s{i}", "text": f"S{i}.", "kind": "rule", "authorities": auths}
            for i, auths in enumerate(sentences)]}])

    def test_signal(self):
        self.assertEqual(self.cite([case("A v. B", "5", signal="See")]), "S0. *See* *A v. B*, 1 P.3d 1, 5 (Alaska 2000).")

    def test_later_signal_is_lowercase_and_not_repeated(self):
        text = self.cite([case("A v. B", signal="See"), case("C v. D", signal="See"), case("E v. F", signal="See also")])
        self.assertIn("*See* *A v. B*, 1 P.3d 1 (Alaska 2000); *C v. D*, 1 P.3d 1 (Alaska 2000); *see also* *E v. F*", text)

    def test_parenthetical_with_a_case(self):
        a = case("A v. B", "5", parenthetical={"text": "discussing the test set forth in", "authority": case("C v. D", "7")})
        self.assertEqual(self.cite([a]), "S0. *A v. B*, 1 P.3d 1, 5 (Alaska 2000) "
                                         "(discussing the test set forth in *C v. D*, 1 P.3d 1, 7 (Alaska 2000)).")

    def test_id_same_page(self):
        self.assertEqual(self.cite([case("A v. B", "5")], [case("A v. B", "5")]),
                         "S0. *A v. B*, 1 P.3d 1, 5 (Alaska 2000). S1. *Id.*")

    def test_id_at_another_page_with_signal(self):
        self.assertTrue(self.cite([case("A v. B", "5")], [case("A v. B", "6", signal="See")])
                        .endswith("S1. *See* *id.* at 6."))

    def test_no_id_after_a_string_cite_or_another_case(self):
        text = self.cite([case("A v. B", "5"), case("C v. D")], [case("A v. B", "5")])
        self.assertNotIn("Id.", text)

    def test_id_never_refers_to_a_parenthetical(self):
        a = case("A v. B", "5", parenthetical={"text": "citing", "authority": case("C v. D", "7")})
        self.assertNotIn("Id.", self.cite([a], [case("C v. D", "7")]))

    def test_no_id_when_the_pinpoint_is_missing(self):
        self.assertNotIn("Id.", self.cite([case("A v. B", "5")], [case("A v. B", "")]))


class StructuredSentences(unittest.TestCase):
    """The engine returns each sentence's text and authorities separately, so a renderer can put
    citations inline or in footnotes."""

    def setUp(self):
        self.config, _questions, issues = E.load_repo(ROOT)
        self.issue = copy.deepcopy(next(i for i in issues if i["id"] == "prolonged-stop"))
        self.issue["law_paragraphs"] = [{"id": "p", "sentences": [{
            "id": "mixed", "text": "A proposition.",
            "authorities": [
                {"type": "statute", "name": "Example statute", "citation": "", "court": "ak"},
                {"type": "case", "name": "Example v. Case", "citation": "1 U.S. 1 (2000)",
                 "pincite": "5", "court": "scotus"},
            ]}]}]

    def sentences(self, answers):
        paragraphs, _gaps = E.law_paragraphs(self.issue, answers, E.binding_courts(answers), self.config)
        return paragraphs[0]["sentences"]

    def test_sentence_keeps_text_and_ordered_authorities_apart(self):
        sentences = self.sentences(STATE)
        self.assertEqual([st["text"] for st in sentences], ["A proposition."])
        self.assertEqual([a["court"] for a in sentences[0]["authorities"]], ["scotus", "ak"])

    def test_authorities_filtered_to_forum(self):
        self.assertEqual([a["court"] for a in self.sentences(FEDERAL)[0]["authorities"]], ["scotus"])

    def test_citation_parts_leave_markup_to_the_renderer(self):
        case, statute = self.issue["law_paragraphs"][0]["sentences"][0]["authorities"][1::-1]
        self.assertEqual(E.citation_parts(case), {"name": "Example v. Case", "italic": True, "rest": "1 U.S. 1, 5 (2000)"})
        self.assertEqual(E.citation_parts(statute), {"name": "Example statute", "italic": False, "rest": ""})


class ClientTokens(unittest.TestCase):
    TEXT = "{They} {were} told {their} rights by {client}'s lawyer, and {they} {do} not deny it."

    def test_each_pronoun_choice(self):
        expected = {
            "he_him": "He was told his rights by [Client]'s lawyer, and he does not deny it.",
            "she_her": "She was told her rights by [Client]'s lawyer, and she does not deny it.",
            "they_them": "They were told their rights by [Client]'s lawyer, and they do not deny it.",
            "no_pronouns": "[Client] was told [Client]'s rights by [Client]'s lawyer, and [Client] does not deny it.",
        }
        for pronouns, text in expected.items():
            with self.subTest(pronouns=pronouns):
                self.assertEqual(E.fill_client(self.TEXT, pronouns), text)

    def test_unanswered_repeats_the_name_instead_of_guessing(self):
        self.assertEqual(E.fill_client(self.TEXT, None), E.fill_client(self.TEXT, "no_pronouns"))

    def test_heading_and_memo_count(self):
        config, _questions, issues = E.load_repo(ROOT)
        issue = next(i for i in issues if i["id"] == "frisk-without-reasonable-suspicion")
        answers = {**FEDERAL, "q_client_pronouns": "she_her", "q_encounter_events": ["vehicle_stop", "frisk"],
                   "q_occupant_role": "driver", "q_frisk_suspicion_basis": "none_articulated"}
        result = E.evaluate_session(config, [issue], {"answers": answers})
        motion = R.render_motion(result)
        self.assertIn("The Frisk of [Client] Was Not Supported by Reasonable Suspicion That She Was Armed", motion)
        memo = R.render_memo(result, config, motion)
        self.assertIn("the motion says [Client] in 1 place. Replace each one with your client's name the way you "
                      "want it to appear in the motion, e.g. \"Mr. Smith\" or \"Smith\".", memo)
        self.assertIn("**Pronouns for your client:** she/her.", memo)


class EventGroups(unittest.TestCase):
    def setUp(self):
        self.config, _questions, self.issues = E.load_repo(ROOT)

    def included(self, answers):
        result = E.evaluate_session(self.config, self.issues, {"answers": answers})
        return {e["issue"]["id"] for e in result["included"] + result["no_paragraph"]}

    def test_plain_view_starts_from_any_member_of_either_group(self):
        facts = {"q_how_found": ["plain_view"], "q_officer_location_lawful": "disputed"}
        for event in ("digital_device", "field_sobriety_tests", "entry_home"):
            with self.subTest(event=event):
                self.assertIn("plain-view-not-lawfully-present",
                              self.included({**STATE, "q_encounter_events": [event], **facts}))

    def test_plain_view_not_reached_outside_the_groups(self):
        facts = {"q_how_found": ["plain_view"], "q_officer_location_lawful": "disputed"}
        self.assertNotIn("plain-view-not-lawfully-present",
                         self.included({**STATE, "q_encounter_events": ["third_party_data"], **facts}))


class MatchedButNoParagraph(unittest.TestCase):
    """The memo must say whether an empty issue needs research or has a content problem."""

    def setUp(self):
        self.config, _questions, issues = E.load_repo(ROOT)
        self.issue = copy.deepcopy(next(i for i in issues if i["id"] == "frisk-without-reasonable-suspicion"))
        self.answers = {**FEDERAL, "q_encounter_events": ["vehicle_stop", "frisk"], "q_occupant_role": "passenger",
                        "q_frisk_suspicion_basis": "none_articulated"}

    def memo(self):
        result = E.evaluate_session(self.config, [self.issue], {"answers": self.answers})
        self.assertEqual(result["included"], [])
        self.assertEqual(len(result["no_paragraph"]), 1)
        return R.render_memo(result, self.config)

    def test_every_sentence_a_gap_says_research_needed(self):
        for p in self.issue["law_paragraphs"]:
            for st in p["sentences"]:
                st["authorities"] = []
        self.assertIn("Research needed", self.memo())

    def test_every_paragraph_filtered_says_content_problem(self):
        for p in self.issue["law_paragraphs"]:
            p["when"] = {"question": "q_frisk_suspicion_basis", "op": "equals", "value": "generalized_only"}
        memo = self.memo()
        self.assertIn("problem with the issue's content", memo)
        self.assertNotIn("Research needed", memo)

    def test_argument_alone_is_not_a_section(self):
        for p in self.issue["law_paragraphs"]:
            for st in p["sentences"]:
                st["authorities"] = []
        self.issue["law_paragraphs"].append({"id": "application", "sentences": [
            {"id": "reasoning", "kind": "argument", "text": "That is what happened here.", "authorities": []}]})
        self.assertIn("Research needed", self.memo())


if __name__ == "__main__":
    unittest.main()

"""Checks that the validator catches every class of bug found while designing this project.

Each test copies the repo to a temp dir, injects one known bug, and asserts the
validator reports it. Run from the repo root:  python3 -m unittest discover tests
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import validate as V  # noqa: E402

ISSUES = "content/issues"


def edit(root, rel, fn):
    path = os.path.join(root, rel)
    with open(path) as f:
        data = json.load(f)
    fn(data)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def stmt(issue, sid):
    return next(s for s in issue["law_paragraph"]["rule_statements"] if s["id"] == sid)


class ValidatorCatchesKnownBugs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for d in ("content", "examples"):
            shutil.copytree(os.path.join(ROOT, d), os.path.join(self.tmp, d))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_with(self, rel, fn):
        edit(self.tmp, rel, fn)
        return V.validate(self.tmp)

    def assertError(self, report, needle):
        self.assertTrue(any(needle in e for e in report.errors),
                        f"expected an error containing {needle!r}; got:\n" + "\n".join(report.errors))

    def assertWarning(self, report, needle):
        self.assertTrue(any(needle in w for w in report.warnings),
                        f"expected a warning containing {needle!r}; got:\n" + "\n".join(report.warnings))

    # ---- baseline

    def test_clean_content_has_no_errors(self):
        r = V.validate(ROOT)
        self.assertEqual(r.errors, [], "\n".join(r.errors))

    # ---- dead conditions (found twice during design)

    def test_review_condition_contradicting_match(self):
        # Original bug: review note on q_independent_suspicion == yes, while match requires no/not_sure.
        def f(d):
            d["trigger"]["review_conditions"][0]["when"]["value"] = "yes"
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "can never fire on an included issue")

    def test_negligence_as_review_condition(self):
        # Original bug: Franks negligence note filed as a review condition, but negligence fails the match.
        def f(d):
            d["trigger"]["review_conditions"] = [
                {"when": {"question": "q_intent", "op": "equals", "value": "negligent"},
                 "flag": "intent_below_standard", "display_note": "Negligence isn't enough."}]
        self.assertError(self.run_with(f"{ISSUES}/franks-violation.json", f), "can never fire on an included issue")

    def test_excluded_explanation_that_implies_a_match(self):
        def f(d):
            d["trigger"]["excluded_explanations"].append(
                {"when": d["trigger"]["match_condition"], "flag": "impossible", "display_note": "x"})
        self.assertError(self.run_with(f"{ISSUES}/franks-violation.json", f), "can never fire")

    def test_statement_when_that_contradicts_match(self):
        def f(d):
            stmt(d, "dog_sniff_no_added_time")["when"] = {
                "question": "q_original_purpose_completed", "op": "equals", "value": "no"}
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "never renders")

    def test_match_condition_that_is_never_true(self):
        def f(d):
            d["trigger"]["match_condition"]["all"].append(
                {"question": "q_occupant_role", "op": "equals", "value": "driver"})
        self.assertError(self.run_with(f"{ISSUES}/passenger-frisk-suspicionless.json", f), "can never be true")

    # ---- op / type mismatches (not_equals null on a multi_select)

    def test_not_equals_null_on_multi_select(self):
        def f(d):
            d["trigger"]["match_condition"]["all"][1] = {
                "question": "q_extension_event", "op": "not_equals", "value": None}
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "can't be used with multi_select")

    def test_equals_on_multi_select(self):
        def f(d):
            d["trigger"]["match_condition"]["all"][0] = {
                "question": "q_contact_requested", "op": "equals", "value": "attorney"}
        self.assertError(self.run_with(f"{ISSUES}/denial-of-contact-before-breath-test.json", f),
                         "can't be used with multi_select")

    def test_short_text_in_condition(self):
        def f(d):
            d["trigger"]["match_condition"]["all"].append(
                {"question": "q_duration", "op": "equals", "value": "5 minutes"})
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "short_text")

    # ---- references

    def test_label_text_instead_of_option_id(self):
        def f(d):
            d["trigger"]["match_condition"]["all"][0]["value"] = "Passenger"
        self.assertError(self.run_with(f"{ISSUES}/passenger-frisk-suspicionless.json", f), "not valid option ids")

    def test_capitalized_yes_no(self):
        def f(d):
            d["trigger"]["match_condition"]["all"][0]["value"] = "Yes"
        self.assertError(self.run_with(f"{ISSUES}/franks-violation.json", f), "not valid option ids")

    def test_unknown_question(self):
        def f(d):
            d["trigger"]["match_condition"]["all"][0]["question"] = "q_requested_attorney_contact"
        self.assertError(self.run_with(f"{ISSUES}/denial-of-contact-before-breath-test.json", f),
                         "unknown question")

    # ---- stale fields left behind by redesigns

    def test_stale_issue_fields(self):
        for field in ("uses_questions", "question_bank_file", "related_issues",
                      "jurisdiction", "circuits_reviewed", "applicable_forums", "category"):
            with self.subTest(field=field):
                self.setUp()
                r = self.run_with(f"{ISSUES}/prolonged-stop.json", lambda d: d.update({field: []}))
                self.assertError(r, "unknown field")

    def test_stale_authority_and_paragraph_fields(self):
        cases = [
            lambda d: stmt(d, "core_prolongation_rule")["authorities"][0].update({"propositions": []}),
            lambda d: stmt(d, "core_prolongation_rule")["authorities"][0].update({"jurisdiction": "federal"}),
            lambda d: stmt(d, "core_prolongation_rule").update({"citations": []}),
            lambda d: d["law_paragraph"].update({"segments": []}),
        ]
        for i, fn in enumerate(cases):
            with self.subTest(case=i):
                self.setUp()
                self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", fn), "unknown field")

    def test_stale_config_fields(self):
        for field in ("category_order", "issues", "question_bank_topics", "cross_cutting_reminders",
                      "case_session_schema", "desired_courts"):
            with self.subTest(field=field):
                self.setUp()
                r = self.run_with("content/config.json", lambda c: c.update({field: []}))
                self.assertError(r, "unknown field")

    def test_manifest_reintroduced(self):
        with open(os.path.join(self.tmp, "content", "manifest.json"), "w") as f:
            json.dump({}, f)
        self.assertError(V.validate(self.tmp), "the manifest was split up")

    # ---- rule statement text

    def test_case_name_embedded_in_text(self):
        # Original bug: "Illinois v. Caballes, 543 U.S. 405 (2005), permits a dog sniff..."
        def f(d):
            stmt(d, "dog_sniff_no_added_time")["text"] = "Illinois v. Caballes permits a dog sniff only if it adds no time."
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "a case name")

    def test_reporter_citation_embedded_in_text(self):
        def f(d):
            stmt(d, "dog_sniff_no_added_time")["text"] = "Under 543 U.S. 405, a dog sniff must not add time."
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "a reporter citation")

    def test_statute_embedded_in_text(self):
        def f(d):
            stmt(d, "core_communication_right")["text"] = "Under AS 12.25.150(b), an arrestee may call an attorney."
        self.assertError(self.run_with(f"{ISSUES}/denial-of-contact-before-breath-test.json", f), "statute")

    def test_placeholder_text(self):
        def f(d):
            stmt(d, "core_prolongation_rule")["authorities"].append(
                {"type": "case", "name": "PLACEHOLDER — insert controlling Alaska case",
                 "citation": "1 P.3d 1 (Alaska 2000)", "pincite": "", "court": "AK"})
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "placeholder")

    # ---- audience

    def test_author_note_in_practice_notes(self):
        # Original bug: the "20-minute observation period" note left in practice_notes.
        def f(d):
            d["practice_notes"].append(
                "A prior draft of this rule asserted a per se reasonable period; removed because no "
                "citation was actually confirmed for it.")
        self.assertWarning(self.run_with(f"{ISSUES}/denial-of-contact-before-breath-test.json", f),
                           "reads like a note to the author")

    # ---- authorities

    def test_case_missing_pincite_key(self):
        def f(d):
            del stmt(d, "core_prolongation_rule")["authorities"][0]["pincite"]
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "missing required field")

    def test_pincite_on_statute(self):
        def f(d):
            stmt(d, "core_communication_right")["authorities"][0]["pincite"] = "1"
        self.assertError(self.run_with(f"{ISSUES}/denial-of-contact-before-breath-test.json", f), "unknown field")

    def test_malformed_case_citation(self):
        def f(d):
            stmt(d, "core_prolongation_rule")["authorities"][0]["citation"] = "575 U.S. 348"
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "must look like")

    def test_circuit_authority_on_alaska_only_issue(self):
        def f(d):
            stmt(d, "core_communication_right")["authorities"].append(
                {"type": "case", "name": "United States v. Example", "citation": "1 F.3d 1 (9th Cir. 2000)",
                 "pincite": "", "court": "9th Circuit"})
        self.assertError(self.run_with(f"{ISSUES}/denial-of-contact-before-breath-test.json", f), "can never be cited")

    # ---- review status and applicability

    def test_reviewed_without_signoff(self):
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", lambda d: d.update({"status": "reviewed"})),
                         "reviewed issues need")

    def test_scotus_plus_redundant_courts(self):
        def f(d):
            d["applicable_courts"] = ["SCOTUS", "9th Circuit", "AK"]
        self.assertWarning(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "SCOTUS alone already covers")

    # ---- config, file layout, and question bank

    def test_issue_id_not_matching_file_name(self):
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", lambda d: d.update({"id": "prolonged"})),
                         "doesn't match the file name")

    def test_phase_not_in_phase_order(self):
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", lambda d: d.update({"phase": "stop"})),
                         "not in config phase_order")

    def test_session_option_not_a_court(self):
        def f(s):
            s["state"]["options"].append({"id": "WA", "label": "Washington"})
        self.assertError(self.run_with("content/session.json", f), "is not a state in config courts")

    def test_duplicate_option_id(self):
        def f(qs):
            q = next(q for q in qs if q["id"] == "q_intent")
            q["options"][1]["id"] = "deliberate"
        self.assertError(self.run_with("content/questions/warrant-affidavit.json", f), "duplicate option id")

    def test_option_as_plain_string(self):
        def f(qs):
            q = next(q for q in qs if q["id"] == "q_occupant_role")
            q["options"][0] = "Driver"
        self.assertError(self.run_with("content/questions/vehicle-occupants.json", f), "exactly {id, label}")

    # ---- unknown-answer policy

    def test_silent_exclusion_on_unknown_is_flagged_and_can_be_resolved(self):
        self.assertWarning(V.validate(self.tmp), "silently excludes")

        def f(d):
            d["trigger"]["excluded_explanations"].append(
                {"when": {"question": "q_intent", "op": "equals", "value": "unknown"},
                 "flag": "intent_unknown", "display_note": "Intent is unknown; develop it in discovery."})
        r = self.run_with(f"{ISSUES}/franks-violation.json", f)
        self.assertFalse(any("silently excludes" in w for w in r.warnings))


if __name__ == "__main__":
    unittest.main()

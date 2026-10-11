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
    """The sentence with this id, in whichever paragraph it is."""
    return next(s for p in issue["law_paragraphs"] for s in p["sentences"] if s["id"] == sid)


def para(issue, sid):
    """The paragraph containing the sentence with this id."""
    return next(p for p in issue["law_paragraphs"] if any(s["id"] == sid for s in p["sentences"]))


class ValidatorCatchesKnownBugs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for d in ("content", "examples"):
            shutil.copytree(os.path.join(ROOT, d), os.path.join(self.tmp, d))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_with(self, rel, fn):
        """Inject a bug into one file and validate. A bug in an issue file only needs that issue
        checked (much faster); anything else (config, questions, sessions) gets a full check."""
        edit(self.tmp, rel, fn)
        if rel.startswith(ISSUES + "/"):
            return V.validate(self.tmp, only={os.path.splitext(os.path.basename(rel))[0]})
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

    def test_checking_one_issue_matches_the_full_check(self):
        # The fast path the other tests use must report exactly what a full check reports for that issue.
        full = V.validate(ROOT)
        for iid in ("prolonged-stop", "search-incident-to-arrest-exceeded-scope", "consent-not-voluntary"):
            with self.subTest(issue=iid):
                part = V.validate(ROOT, only={iid})
                mine = lambda msgs: [m for m in msgs if m.startswith(f"{ISSUES}/{iid}.json")]
                self.assertEqual((mine(part.errors), mine(part.warnings)), (mine(full.errors), mine(full.warnings)))

    # ---- dead conditions (found twice during design)

    def test_review_condition_contradicting_match(self):
        # Original bug: review note on q_independent_suspicion == yes, while match requires no.
        def f(d):
            d["trigger"].setdefault("review_conditions", []).append(
                {"when": {"question": "q_independent_suspicion", "op": "equals", "value": "yes"},
                 "flag": "suspicion_found", "display_note": "x"})
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

    def test_paragraph_when_that_contradicts_match(self):
        def f(d):
            para(d, "dog_sniff_no_added_time")["when"] = {
                "question": "q_independent_suspicion", "op": "equals", "value": "yes"}
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "never renders")

    def test_match_condition_that_is_never_true(self):
        def f(d):
            d["trigger"]["match_condition"]["all"].append(
                {"question": "q_frisk_suspicion_basis", "op": "equals", "value": "specific_to_client"})
        self.assertError(self.run_with(f"{ISSUES}/frisk-without-reasonable-suspicion.json", f), "can never be true")

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
        self.assertError(self.run_with(f"{ISSUES}/frisk-without-reasonable-suspicion.json", f), "not valid option ids")

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

    def test_stale_trigger_fields(self):
        r = self.run_with(f"{ISSUES}/prolonged-stop.json",
                          lambda d: d["trigger"].update({"non_gating_questions": {"q_stop_type": "x"}}))
        self.assertError(r, "unknown field")

    def test_stale_issue_fields(self):
        for field in ("uses_questions", "question_bank_file", "related_issues",
                      "jurisdiction", "circuits_reviewed", "applicable_forums", "category", "phase"):
            with self.subTest(field=field):
                self.setUp()
                r = self.run_with(f"{ISSUES}/prolonged-stop.json", lambda d: d.update({field: []}))
                self.assertError(r, "unknown field")

    def test_stale_authority_and_paragraph_fields(self):
        cases = [
            lambda d: stmt(d, "core_prolongation_rule")["authorities"][0].update({"propositions": []}),
            lambda d: stmt(d, "core_prolongation_rule")["authorities"][0].update({"jurisdiction": "federal"}),
            lambda d: stmt(d, "core_prolongation_rule").update({"citations": []}),
            lambda d: d["law_paragraphs"][0].update({"segments": []}),
        ]
        for i, fn in enumerate(cases):
            with self.subTest(case=i):
                self.setUp()
                self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", fn), "unknown field")

    def test_stale_config_fields(self):
        for field in ("category_order", "issues", "question_bank_topics", "cross_cutting_reminders",
                      "case_session_schema", "desired_courts", "session", "phase_order"):
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
                 "citation": "1 P.3d 1 (Alaska 2000)", "pincite": "", "court": "ak"})
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
                 "pincite": "", "court": "9th_cir"})
        self.assertError(self.run_with(f"{ISSUES}/denial-of-contact-before-breath-test.json", f), "can never be cited")

    # ---- review status and applicability

    def test_reviewed_without_signoff(self):
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", lambda d: d.update({"status": "reviewed"})),
                         "reviewed issues need")

    def test_scotus_plus_redundant_courts(self):
        def f(d):
            d["applicable_courts"] = ["scotus", "9th_cir", "ak"]
        self.assertWarning(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "alone already covers every forum")

    # ---- paragraph-level applicable_courts

    def test_paragraph_courts_broader_than_issue(self):
        def f(d):
            para(d, "core_communication_right")["applicable_courts"] = ["9th_cir"]
        self.assertError(self.run_with(f"{ISSUES}/denial-of-contact-before-breath-test.json", f),
                         "but the issue only applies in")

    def test_paragraph_courts_same_as_issue(self):
        def f(d):
            para(d, "dog_sniff_no_added_time")["applicable_courts"] = ["scotus"]
        self.assertWarning(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "same as the issue's")

    def test_paragraph_unknown_court(self):
        def f(d):
            para(d, "dog_sniff_no_added_time")["applicable_courts"] = ["wa"]
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "unknown court 'wa'")

    def test_authority_not_citable_where_paragraph_applies(self):
        # core_prolongation_rule cites SCOTUS and Alaska; limiting its paragraph to the Ninth Circuit strands the Alaska case.
        def f(d):
            para(d, "core_prolongation_rule")["applicable_courts"] = ["9th_cir"]
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "this paragraph only applies in")

    # ---- "your client" in questions, "the defendant" in the motion

    def test_defendant_in_question(self):
        def f(qs):
            next(q for q in qs if q["id"] == "q_occupant_role")["prompt"] = "Was the defendant the driver?"
        self.assertError(self.run_with("content/questions/vehicle-occupants.json", f), "say 'your client'")

    def test_defendant_in_option_label(self):
        def f(qs):
            next(q for q in qs if q["id"] == "q_encounter_events")["options"][0]["label"] = "The defendant was stopped"
        self.assertError(self.run_with("content/questions/case-setup.json", f), "say 'your client'")

    def test_client_in_motion_text(self):
        cases = [lambda d: d.update({"motion_heading": "The Stop of My Client Was Unlawfully Prolonged"}),
                 lambda d: stmt(d, "dog_sniff_no_added_time").update({"text": "Police may not hold a client longer."})]
        for i, fn in enumerate(cases):
            with self.subTest(case=i):
                self.setUp()
                self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", fn), "write {client}")

    # ---- encounter events

    def test_issue_without_event_gate(self):
        def f(d):
            d["trigger"]["match_condition"]["all"] = [
                c for c in d["trigger"]["match_condition"]["all"] if c.get("question") != "q_encounter_events"]
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "must require an encounter event")

    def test_event_gate_as_any(self):
        def f(d):
            d["trigger"]["match_condition"]["all"][0] = {"any": [
                {"question": "q_encounter_events", "op": "includes", "value": "vehicle_stop"},
                {"question": "q_encounter_events", "op": "includes", "value": "pedestrian_stop"}]}
        r = self.run_with(f"{ISSUES}/prolonged-stop.json", f)
        self.assertFalse(any("encounter event" in e for e in r.errors), "\n".join(r.errors))

    def test_superseded_questions_are_gone(self):
        for qid in ("q_warrant_used", "q_passenger_frisked", "q_original_purpose_completed", "q_breath_test_administered"):
            with self.subTest(qid=qid):
                self.setUp()
                def f(d):
                    d["trigger"]["match_condition"]["all"].append({"question": qid, "op": "equals", "value": "yes"})
                self.assertError(self.run_with(f"{ISSUES}/franks-violation.json", f), "unknown question")

    def test_reachability_still_checked_with_many_events(self):
        # 20 event options would be 2^20 subsets; the validator must still enumerate, not skip.
        r = V.validate(self.tmp)
        self.assertFalse(any("too many answer combinations" in w for w in r.warnings), "\n".join(r.warnings))

    def test_skipped_check_warns(self):
        # Above the enumeration limit a check is skipped; it must say so, never skip silently.
        old = V.ENUMERATION_LIMIT
        V.ENUMERATION_LIMIT = 10
        try:
            r = V.validate(ROOT, only={"search-incident-to-arrest-exceeded-scope"})
        finally:
            V.ENUMERATION_LIMIT = old
        skipped = [w for w in r.warnings if "too many answer combinations" in w]
        self.assertTrue(skipped, "\n".join(r.warnings))
        self.assertTrue(all("Questions involved:" in w for w in skipped))

    def test_missing_precondition_on_an_answer(self):
        # The container bug: a paragraph reaches q_container_use only after a closed container was
        # searched, but a review note reached it without that, so the interview asked about "the
        # container" in every search-incident-to-arrest case.
        def f(d):
            rc = next(r for r in d["trigger"]["review_conditions"] if r["flag"] == "container_personal_effects")
            rc["when"] = rc["when"]["all"][1]
        self.assertWarning(self.run_with(f"{ISSUES}/search-incident-to-arrest-exceeded-scope.json", f),
                           "q_container_use may be missing a precondition")

    def test_near_miss_contradicting_the_event_gate(self):
        # Near misses show only when the issue's event happened, so one that needs no event can never fire.
        def f(d):
            d["trigger"].setdefault("excluded_explanations", []).append(
                {"when": {"question": "q_encounter_events", "op": "empty"}, "flag": "no_events", "display_note": "x"})
        self.assertError(self.run_with(f"{ISSUES}/plain-view-object-moved.json", f), "encounter event didn't happen")

    def test_warrant_not_a_search_justification(self):
        def f(qs):
            qs[0]["options"].insert(0, {"id": "warrant", "label": "A search warrant"})
        self.assertError(self.run_with("content/questions/search-justification.json", f), "warrantless searches only")

    def test_unknown_event_group(self):
        def f(d):
            d["trigger"]["match_condition"]["all"][0] = {"event_group": "any_serch"}
        self.assertError(self.run_with(f"{ISSUES}/consent-not-voluntary.json", f), "unknown event_group 'any_serch'")

    def test_event_group_member_not_an_event(self):
        self.assertError(self.run_with("content/config.json", lambda c: c["event_groups"]["any_search"].append("search_boat")),
                         "'search_boat' isn't an option of q_encounter_events")

    def test_unused_event_group(self):
        self.assertWarning(self.run_with("content/config.json", lambda c: c["event_groups"].update({"any_test": ["breath_test"]})),
                           "group 'any_test' isn't used by any issue")

    def test_contradiction_still_caught_with_grouped_events(self):
        # Plain view starts from any of ten events; the validator enumerates them as one group.
        # A review note that needs none of those events must still be caught as dead.
        def f(d):
            d["trigger"].setdefault("review_conditions", []).append(
                {"when": {"question": "q_encounter_events", "op": "empty"},
                 "flag": "impossible", "display_note": "x"})
        self.assertError(self.run_with(f"{ISSUES}/plain-view-object-moved.json", f),
                         "can never fire on an included issue")

    def test_event_outside_the_group_still_enumerated_separately(self):
        # frisk is in plain view's event group but also used on its own here, so it can't be
        # collapsed with the others: requiring frisk AND not frisk must be caught.
        def f(d):
            d["law_paragraphs"][0]["when"] = {"all": [
                {"question": "q_encounter_events", "op": "includes", "value": "frisk"},
                {"question": "q_encounter_events", "op": "not_includes", "value": "frisk"}]}
        self.assertError(self.run_with(f"{ISSUES}/plain-view-object-moved.json", f), "never renders")

    # ---- an issue that matches but produces nothing

    def test_match_with_every_paragraph_filtered_by_when(self):
        # Matches on none_articulated too, but every paragraph now needs generalized_only.
        def f(d):
            for p in d["law_paragraphs"]:
                p["when"] = {"question": "q_frisk_suspicion_basis", "op": "equals", "value": "generalized_only"}
        self.assertError(self.run_with(f"{ISSUES}/frisk-without-reasonable-suspicion.json", f),
                         "no paragraph of law left")

    def test_match_with_every_paragraph_limited_to_another_forum(self):
        def f(d):
            for p in d["law_paragraphs"]:
                p["applicable_courts"] = ["ak"]
        self.assertError(self.run_with(f"{ISSUES}/frisk-without-reasonable-suspicion.json", f),
                         "in Ninth Circuit, the issue can match with no paragraph of law left")

    # ---- config, file layout, and question bank

    def test_issue_id_not_matching_file_name(self):
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", lambda d: d.update({"id": "prolonged"})),
                         "doesn't match the file name")

    def test_issue_missing_from_motion_order(self):
        def f(c):
            c["motion_order"]["stop-conduct"].remove("prolonged-stop")
        self.assertError(self.run_with("content/config.json", f), "prolonged-stop.json isn't in motion_order")

    def test_motion_order_lists_unknown_issue(self):
        self.assertError(self.run_with("content/config.json", lambda c: c["motion_order"]["arrest"].append("no-such-issue")),
                         "there's no content/issues/no-such-issue.json")

    def test_issue_listed_twice_in_motion_order(self):
        self.assertError(self.run_with("content/config.json", lambda c: c["motion_order"]["arrest"].append("prolonged-stop")),
                         "more than once")

    # ---- filing court

    def test_session_json_reintroduced(self):
        with open(os.path.join(self.tmp, "content", "session.json"), "w") as f:
            json.dump({}, f)
        self.assertError(V.validate(self.tmp), "replaced by the q_filing_court question")

    def test_old_session_fields(self):
        for field, value in (("forum", "state_court"), ("state", "ak"), ("federal_circuit", "9th_cir")):
            with self.subTest(field=field):
                self.setUp()
                r = self.run_with("examples/sessions/state-dui.json", lambda s: s.update({field: value}))
                self.assertError(r, "unknown field")

    def test_null_answer_in_session(self):
        r = self.run_with("examples/sessions/state-dui.json", lambda s: s["answers"].update({"q_client_pronouns": None}))
        self.assertError(r, "every question asked gets a real answer")

    def test_session_without_filing_court(self):
        r = self.run_with("examples/sessions/state-dui.json", lambda s: s["answers"].pop("q_filing_court"))
        self.assertError(r, "no answer for q_filing_court")

    def test_filing_court_option_not_a_court(self):
        def f(qs):
            qs[0]["options"].append({"id": "wa", "label": "Washington state court"})
        self.assertError(self.run_with("content/questions/case-setup.json", f),
                         "is not a state or circuit court")

    def test_scotus_as_filing_court(self):
        def f(qs):
            qs[0]["options"].append({"id": "scotus", "label": "Supreme Court"})
        self.assertError(self.run_with("content/questions/case-setup.json", f),
                         "is not a state or circuit court")

    def test_court_code_not_snake_case(self):
        def f(c):
            c["courts"]["9th Circuit"] = c["courts"].pop("9th_cir")
        self.assertError(self.run_with("content/config.json", f), "must be snake_case")

    def test_condition_on_filing_court(self):
        def f(d):
            para(d, "core_prolongation_rule")["when"] = {"question": "q_filing_court", "op": "equals", "value": "ak"}
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "conditions can't use q_filing_court")

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

    # ---- paragraphs (replaced the flat rule_statements list)

    def test_old_law_paragraph_reintroduced(self):
        def f(d):
            d["law_paragraph"] = {"rule_statements": d["law_paragraphs"][0]["sentences"]}
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "was replaced by law_paragraphs")

    def test_condition_on_a_sentence(self):
        for field, value in (("when", {"question": "q_independent_suspicion", "op": "equals", "value": "yes"}),
                             ("applicable_courts", ["ak"])):
            with self.subTest(field=field):
                self.setUp()
                r = self.run_with(f"{ISSUES}/prolonged-stop.json",
                                  lambda d: stmt(d, "core_prolongation_rule").update({field: value}))
                self.assertError(r, "put the condition on the paragraph")

    def test_duplicate_sentence_id_across_paragraphs(self):
        def f(d):
            stmt(d, "dog_sniff_no_added_time")["id"] = "core_prolongation_rule"
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "duplicate sentence id")

    def test_argument_sentence_with_authority(self):
        def f(d):
            stmt(d, "core_prolongation_rule")["kind"] = "argument"
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "argument sentences have no authorities")

    def test_argument_sentence_is_not_a_gap(self):
        def f(d):
            d["law_paragraphs"][0]["sentences"].append(
                {"id": "reasoning", "kind": "argument", "text": "That is what happened here.", "authorities": []})
        r = self.run_with(f"{ISSUES}/prolonged-stop.json", f)
        self.assertEqual(r.errors, [], "\n".join(r.errors))
        self.assertFalse(any("reasoning" in w for w in r.warnings), "\n".join(r.warnings))

    def test_application_paragraph_of_only_argument_is_fine(self):
        def f(d):
            d["law_paragraphs"].append({"id": "application", "sentences": [
                {"id": "reasoning", "kind": "argument", "text": "That is what happened here.", "authorities": []}]})
        r = self.run_with(f"{ISSUES}/prolonged-stop.json", f)
        self.assertEqual(r.errors, [], "\n".join(r.errors))

    def test_match_leaving_only_argument(self):
        # Every paragraph of law needs generalized_only; an unconditional argument paragraph isn't enough.
        def f(d):
            for p in d["law_paragraphs"]:
                p["when"] = {"question": "q_frisk_suspicion_basis", "op": "equals", "value": "generalized_only"}
            d["law_paragraphs"].append({"id": "application", "sentences": [
                {"id": "reasoning", "kind": "argument", "text": "That is what happened here.", "authorities": []}]})
        self.assertError(self.run_with(f"{ISSUES}/frisk-without-reasonable-suspicion.json", f),
                         "no paragraph of law left")

    def test_unknown_signal(self):
        def f(d):
            stmt(d, "core_prolongation_rule")["authorities"][0]["signal"] = "see"
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "signal 'see' isn't one of")

    def test_parenthetical_authority_checked(self):
        def f(d):
            stmt(d, "core_prolongation_rule")["authorities"][0]["parenthetical"] = {
                "text": "citing", "authority": {"type": "case", "name": "Example v. Case",
                                                "citation": "575 U.S. 348", "pincite": "", "court": "scotus"}}
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "must look like")

    def test_secondary_source_in_parenthetical(self):
        def f(d):
            stmt(d, "core_prolongation_rule")["authorities"][0]["parenthetical"] = {
                "text": "citing", "authority": {"type": "secondary", "name": "1 A. Treatise § 2 (3d ed. 2020)"}}
        r = self.run_with(f"{ISSUES}/prolonged-stop.json", f)
        self.assertEqual(r.errors, [], "\n".join(r.errors))

    def test_secondary_source_as_authority(self):
        def f(d):
            stmt(d, "core_prolongation_rule")["authorities"].append({"type": "secondary", "name": "1 A. Treatise § 2"})
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "only appear inside a parenthetical")

    def test_case_in_parenthetical_text(self):
        def f(d):
            stmt(d, "core_prolongation_rule")["authorities"][0]["parenthetical"] = {
                "text": "discussing Terry v. Ohio"}
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "put the case in its 'authority'")

    def add_paragraph(self, para):
        return self.run_with(f"{ISSUES}/prolonged-stop.json", lambda d: d["law_paragraphs"].append(para))

    def test_fill_in_is_fine(self):
        r = self.add_paragraph({"id": "apply", "fill_in": "Explain what your client was told."})
        self.assertEqual(r.errors, [], "\n".join(r.errors))

    def test_fill_in_and_sentences_together(self):
        self.assertError(self.add_paragraph({"id": "apply", "fill_in": "Explain.", "sentences": []}), "and not both")

    def test_fill_in_with_token(self):
        self.assertError(self.add_paragraph({"id": "apply", "fill_in": "Explain what {client} was told."}),
                         "doesn't use client tokens")

    def test_fill_in_with_brackets(self):
        self.assertError(self.add_paragraph({"id": "apply", "fill_in": "[Explain.]"}), "can't contain brackets")

    def test_empty_fill_in(self):
        self.assertError(self.add_paragraph({"id": "apply", "fill_in": ""}), "non-empty instruction")

    # ---- client tokens (the motion never names the client)

    def heading(self, h):
        return self.run_with(f"{ISSUES}/prolonged-stop.json", lambda d: d.update({"motion_heading": h}))

    def test_the_defendant_in_heading(self):
        self.assertError(self.heading("The Stop of the Defendant Was Prolonged"), "write {client}")

    def test_the_defendant_fine_in_rule_sentence(self):
        r = V.validate(ROOT)  # franks_hearing_standard: "A defendant is entitled to..."
        self.assertFalse(any("defendant" in e for e in r.errors), "\n".join(r.errors))

    def test_the_defendant_in_argument_sentence(self):
        def f(d):
            d["law_paragraphs"].append({"id": "application", "sentences": [
                {"id": "applied", "kind": "argument", "text": "The defendant was held too long.", "authorities": []}]})
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "only for rule sentences")

    def test_unknown_token(self):
        for h in ("{Client} Was Held Too Long", "{his} Stop Was Prolonged", "The {client Stop"):
            with self.subTest(heading=h):
                self.setUp()
                self.assertError(self.heading(h), "unknown token")

    def test_verb_needs_a_token_after_they(self):
        self.assertError(self.heading("The Stop Was Prolonged After {They} Were Cited"), "write {were}")

    def test_verb_token_not_after_they(self):
        self.assertError(self.heading("{client} {Were} Held Too Long"), "must come right after {they}")

    def test_good_tokens(self):
        r = self.heading("The Stop Was Prolonged After {They} {Were} Cited and {Their} License Returned")
        self.assertEqual(r.errors, [], "\n".join(r.errors))

    def test_token_in_rule_sentence(self):
        def f(d):
            stmt(d, "core_prolongation_rule")["text"] = "{client} was held too long."
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "in a rule sentence")

    def test_condition_on_client_pronouns(self):
        def f(d):
            para(d, "core_prolongation_rule")["when"] = {"question": "q_client_pronouns", "op": "equals", "value": "he_him"}
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "conditions can't use q_client_pronouns")

    def test_pronoun_options_fixed(self):
        def f(qs):
            next(q for q in qs if q["id"] == "q_client_pronouns")["options"].append({"id": "ze_zir", "label": "Ze/zir"})
        self.assertError(self.run_with("content/questions/case-setup.json", f), "exactly the options")

    def test_unbalanced_italics(self):
        def f(d):
            stmt(d, "dog_sniff_no_added_time")["text"] = "Under *Caballes, a dog sniff must not add time."
        self.assertError(self.run_with(f"{ISSUES}/prolonged-stop.json", f), "unbalanced '*'")

    # ---- unknown-answer policy

    def test_silent_exclusion_on_unknown_is_an_error(self):
        # Original bug: Franks excluded on q_intent = unknown with nothing in the memo.
        def f(d):
            intent = next(c for c in d["trigger"]["match_condition"]["all"] if c["question"] == "q_intent")
            intent["value"] = ["deliberate", "reckless"]
            del d["trigger"]["review_conditions"]
        self.assertError(self.run_with(f"{ISSUES}/franks-violation.json", f), "silently excludes")

    def test_silent_exclusion_on_checklist_not_sure(self):
        # Requiring one specific problem means "not sure" checked alone excludes the issue, silently.
        def f(d):
            m = d["trigger"]["match_condition"]["all"]
            i = next(i for i, c in enumerate(m) if c.get("question") == "q_sita_problems")
            m[i] = {"question": "q_sita_problems", "op": "includes", "value": "vehicle_after_secured"}
        self.assertError(self.run_with(f"{ISSUES}/search-incident-to-arrest-exceeded-scope.json", f),
                         "q_sita_problems = 'not_sure' (checked alone) silently excludes")

    def test_uncertain_inclusion_without_review_note(self):
        # Franks is drafted on intent = unknown; without its review note the attorney wouldn't know.
        def f(d):
            d["trigger"]["review_conditions"] = [
                n for n in d["trigger"]["review_conditions"] if n["flag"] != "franks_intent_unknown"]
        self.assertError(self.run_with(f"{ISSUES}/franks-violation.json", f),
                         "q_intent = 'unknown' can include this issue with no review note")

    def test_uncertain_inclusion_without_review_note_on_checklist(self):
        def f(d):
            d["trigger"]["review_conditions"] = [
                n for n in d["trigger"]["review_conditions"] if n["flag"] != "sita_scope_unknown"]
        self.assertError(self.run_with(f"{ISSUES}/search-incident-to-arrest-exceeded-scope.json", f),
                         "q_sita_problems = 'not_sure' (checked alone) can include this issue")

    def test_silent_exclusion_resolved_by_excluded_explanation(self):
        def f(d):
            intent = next(c for c in d["trigger"]["match_condition"]["all"] if c["question"] == "q_intent")
            intent["value"] = ["deliberate", "reckless"]
            del d["trigger"]["review_conditions"]
            d["trigger"]["excluded_explanations"].append(
                {"when": {"question": "q_intent", "op": "equals", "value": "unknown"},
                 "flag": "intent_unknown", "display_note": "Intent is unknown; develop it in discovery."})
        r = self.run_with(f"{ISSUES}/franks-violation.json", f)
        self.assertFalse(any("silently excludes" in e for e in r.errors), "\n".join(r.errors))

if __name__ == "__main__":
    unittest.main()

"""Checks the decision tree: the interview asks only what can change the output, and skipping the rest
never changes it.

Run from the repo root:  python3 -m unittest discover tests
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import engine as E  # noqa: E402
import render as R  # noqa: E402
import simulate as S  # noqa: E402

PER_ISSUE = 60  # simulated cases per issue (with its event happening), plus as many fully random ones


def rendered(config, issues, answers):
    result = E.evaluate_session(config, issues, {"answers": answers})
    motion = R.render_motion(result)
    return motion, R.render_memo(result, config, motion)


class SimulatedInterviews(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config, cls.questions, cls.issues = E.load_repo(ROOT)
        cls.cases = list(S.cases(cls.questions, cls.issues, PER_ISSUE))

    def test_skipped_questions_never_change_the_output(self):
        # Interview each case, answering from its complete answers; the motion and memo must be exactly
        # what the complete answers produce. If the tree skips a question that matters, this fails.
        for target, full in self.cases:
            answers, asked = S.run_interview(self.issues, full)
            if rendered(self.config, self.issues, answers) != rendered(self.config, self.issues, full):
                skipped = sorted(set(full) - set(answers))
                self.fail(f"interview for {target or 'a random case'} changed the output. "
                          f"Asked {asked}; skipped {skipped}; full answers {full}")

    def test_top_questions_come_first(self):
        _, full = self.cases[0]
        _, asked = S.run_interview(self.issues, full)
        self.assertEqual(asked[:3], list(E.TOP_QUESTIONS))

    def test_answering_never_reopens_a_question(self):
        # The set of questions that could still be asked only shrinks as answers come in, so the
        # interview never jumps back to an earlier topic (unless the attorney changes an answer).
        for target, full in self.cases[::5]:
            answers = {}
            before = None
            while True:
                now = S.all_open(self.issues, answers)
                if before is not None and now is not None:
                    self.assertLessEqual(now, before, f"{target}: answering reopened {sorted(now - before)}")
                qid = E.next_question(self.issues, answers)
                if qid is None:
                    break
                answers[qid] = full[qid]
                before = None if now is None else now - {qid}

    def test_unused_questions_are_never_asked(self):
        asked = set()
        for _, full in self.cases:
            asked |= set(S.run_interview(self.issues, full)[1])
        self.assertNotIn("q_duration", asked)


class InterviewDetails(unittest.TestCase):
    def setUp(self):
        self.config, self.questions, self.issues = E.load_repo(ROOT)

    def interview(self, answers):
        """Interview, answering every question after the given ones with its first option (or nothing
        checked, for a checklist)."""
        answers = dict(answers)
        asked = []
        while (qid := E.next_question(self.issues, answers)) is not None:
            asked.append(qid)
            q = self.questions[qid]
            answers[qid] = ([] if q["type"] == "multi_select" else
                            "yes" if q["type"] == "yes_no" else q["options"][0]["id"])
        return asked

    def test_no_vehicle_question_after_a_pedestrian_frisk(self):
        asked = self.interview({"q_filing_court": "ak", "q_client_pronouns": "she_her",
                                "q_encounter_events": ["pedestrian_stop", "frisk"],
                                "q_frisk_suspicion_basis": "none_articulated"})
        self.assertNotIn("q_occupant_role", asked)

    def test_no_events_means_a_short_interview(self):
        self.assertEqual(self.interview({"q_filing_court": "9th_cir", "q_client_pronouns": "he_him",
                                         "q_encounter_events": []}), [])

    def test_other_courts_questions_are_skipped(self):
        # inventory-search-before-bail is Alaska-only, so a federal case never asks about bail.
        asked = self.interview({"q_filing_court": "9th_cir", "q_client_pronouns": "he_him",
                                "q_encounter_events": ["arrest", "search_person"]})
        self.assertNotIn("q_bail_established", asked)


class CommandLineInterviewer(unittest.TestCase):
    def test_scripted_interview(self):
        import interview as I
        replies = iter(["2", "4", "", ])  # federal court, no pronouns, no events
        out = []
        answers = I.run(ROOT, {}, read=lambda _prompt: next(replies), write=out.append)
        self.assertEqual(answers, {"q_filing_court": "9th_cir", "q_client_pronouns": "no_pronouns",
                                   "q_encounter_events": []})

    def test_invalid_reply_is_asked_again(self):
        import interview as I
        q = {"id": "q_x", "type": "multiple_choice", "prompt": "Pick one",
             "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}
        replies = iter(["7", "x", "2"])
        self.assertEqual(I.ask(q, read=lambda _p: next(replies), write=lambda _m: None), "b")
        replies = iter(["?", "1"])  # there's no skip
        self.assertEqual(I.ask(q, read=lambda _p: next(replies), write=lambda _m: None), "a")


if __name__ == "__main__":
    unittest.main()

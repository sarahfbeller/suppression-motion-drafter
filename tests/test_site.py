"""Checks what the website relies on: replaying the interview from saved answers, the step list, and
the Word files.

Run from the repo root:  python3 -m unittest discover tests
The Word-file tests need python-docx (`pip install python-docx`) and are skipped without it.
"""
import io
import json
import os
import sys
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import engine as E  # noqa: E402
import simulate as S  # noqa: E402
import site_api as A  # noqa: E402

try:
    import docx  # noqa: F401
    HAVE_DOCX = True
except ImportError:
    HAVE_DOCX = False

FEDERAL_STOP = os.path.join(ROOT, "examples", "sessions", "federal-stop.json")


def session_answers():
    with open(FEDERAL_STOP) as f:
        return json.load(f)["answers"]


class InterviewPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config, cls.questions, cls.issues = E.load_repo(ROOT)
        cls.cases = list(S.cases(cls.config, cls.questions, cls.issues, 10))

    def test_path_is_the_interview(self):
        # Replaying complete answers asks exactly what the live interview asks, in the same order.
        for _target, full in self.cases:
            _answers, asked = S.run_interview(self.config, self.issues, full)
            path, pending, _ = E.interview_path(self.config, self.issues, full)
            self.assertEqual([q for q, _ in path], asked)
            self.assertEqual(pending, (None, None))

    def test_phases_only_move_forward(self):
        # The step list relies on this: the opening, then motion_order phases in order.
        order = [E.OPENING] + list(self.config["motion_order"])
        for _target, full in self.cases:
            path, _, _ = E.interview_path(self.config, self.issues, full)
            ranks = [order.index(p) for _, p in path]
            self.assertEqual(ranks, sorted(ranks), f"phases went backward: {[p for _, p in path]}")

    def test_possible_phases_only_shrink(self):
        for _target, full in self.cases[::3]:
            path, _, _ = E.interview_path(self.config, self.issues, full)
            answers, before = {}, None
            for qid, _ in path:
                now = set(E.possible_phases(self.config, self.issues, answers))
                if before is not None:
                    self.assertLessEqual(now, before)
                before = now
                answers[qid] = full[qid]

    def test_stops_at_the_first_unanswered_question(self):
        full = session_answers()
        partial = {q: full[q] for q in ("q_filing_court", "q_client_pronouns")}
        path, pending, asked = E.interview_path(self.config, self.issues, partial)
        self.assertEqual([q for q, _ in path], ["q_filing_court", "q_client_pronouns"])
        self.assertEqual(pending, ("q_encounter", E.OPENING))
        self.assertEqual(asked, partial)

    def test_answers_off_the_path_are_ignored(self):
        # After un-checking the frisk, the frisk answers stay saved but no longer count.
        answers = session_answers()
        answers["q_searched"] = ["search_vehicle"]
        _path, _pending, asked = E.interview_path(self.config, self.issues, answers)
        self.assertIn("q_frisk_reasons", answers)
        self.assertNotIn("q_frisk_reasons", asked)
        result = E.evaluate_session(self.config, self.issues, {"answers": asked})
        self.assertNotIn("frisk-without-reasonable-suspicion", [e["issue"]["id"] for e in result["included"]])


class SiteApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        A.load(ROOT)

    def state(self, answers):
        return json.loads(A.state(json.dumps(answers)))

    def test_every_phase_is_a_step_before_the_court_is_known(self):
        st = self.state({})
        self.assertEqual(st["pending"], {"id": "q_filing_court", "phase": E.OPENING})
        self.assertEqual([s["name"] for s in st["steps"]][:2], [A.OPENING_NAME, "The stop"])
        self.assertEqual(len(st["steps"]), 1 + len(A._repo[0]["motion_order"]))

    def test_steps_drop_phases_that_cannot_apply(self):
        st = self.state({"q_filing_court": "ak", "q_client_pronouns": "he_him", "q_encounter": ["statements"]})
        self.assertEqual([s["name"] for s in st["steps"]], [A.OPENING_NAME, "Statements"])

    def test_questions_leave_out_the_derived_events(self):
        qs = json.loads(A.questions())
        self.assertIn("q_filing_court", qs)
        self.assertNotIn(E.ENCOUNTER_EVENTS, qs)


@unittest.skipUnless(HAVE_DOCX, "python-docx isn't installed")
class WordFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        A.load(ROOT)
        cls.motion, cls.memo = A.documents(json.dumps(session_answers()))

    def part(self, data, name):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return z.read(name).decode("utf-8")

    def test_citations_are_footnotes(self):
        body = self.part(self.motion, "word/document.xml")
        notes = self.part(self.motion, "word/footnotes.xml")
        self.assertIn("w:footnoteReference", body)
        self.assertIn("Rodriguez v. United States", notes)
        self.assertNotIn("575 U.S. 348", body)  # citations never in the body text

    def test_memo_has_the_memo_text(self):
        body = self.part(self.memo, "word/document.xml")
        self.assertIn("Attorney memo: suppression issues", body)
        self.assertIn("Check before filing:", body)
        self.assertNotIn("**", body)  # Markdown marks became formatting


if __name__ == "__main__":
    unittest.main()

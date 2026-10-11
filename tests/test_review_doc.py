"""Checks that the review document builds and covers every issue and question.

Run from the repo root:  python3 -m unittest discover tests
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import engine as E  # noqa: E402
import review_doc as D  # noqa: E402


class ReviewDocument(unittest.TestCase):
    def test_covers_every_issue_and_question(self):
        text = D.build(ROOT)
        config, questions, issues = E.load_repo(ROOT)
        for issue in issues:
            self.assertIn(issue["label"], text)
            self.assertIn(f"content/issues/{issue['id']}.json", text)
        for qid in questions:
            self.assertIn(f"`{qid}`", text)

    def test_marks_unused_options(self):
        # q_arrest_offense's "drugs" option isn't used by any issue yet.
        self.assertIn("`drugs`: A drug offense *(no issue uses this option)*", D.build(ROOT))


    def test_shows_question_author_notes(self):
        _config, questions, _issues = E.load_repo(ROOT)
        text = D.build(ROOT)
        for q in questions.values():
            for note in q.get("_author_notes", []):
                self.assertIn(note, text)


if __name__ == "__main__":
    unittest.main()

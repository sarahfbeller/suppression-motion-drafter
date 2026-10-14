# CLAUDE.md

Standing instructions for working in this repo. Read this first, then `README.md`,
`docs/SCHEMA.md`, and `docs/AUTHORING_GUIDE.md`.

## What this is

A suppression motion generator for defense attorneys. An attorney answers a question
wizard about a case; the app produces a **motion** (court-facing argument sections with
rule paragraphs and citations) and an **attorney memo** (review notes, practice notes,
near misses, gaps — never filed).

The maintainer is a public defender and former software engineer. Legal content is
reviewed by lawyers before use.

Current scope: U.S. Supreme Court, the Ninth Circuit, and Alaska. Nothing else.

## Legal content: hard rules

- **Never fabricate or guess a citation, pincite, or holding.** If you aren't sure a case
  says something, don't attach it. Leave the authority off the sentence and record
  the gap in `_author_notes`. A missing citation is safe; a plausible wrong one is not.
- **No placeholder text in content.** If something is unknown, leave it out or leave the
  field empty. Never write prose that could be mistaken for real content at a glance.
- **Binding authority only.** No persuasive out-of-circuit or out-of-state authority.
  Ninth Circuit law is never cited in a state-court motion; Alaska law is never cited in a
  federal one; SCOTUS is cited in both.
- **Don't research or assume other states' law.** Issues confirmed only under Alaska law
  stay `applicable_courts: ["ak"]` until the maintainer says otherwise.
- *Palmer v. State* (Alaska 1979) is superseded by AS 28.35.033(e) and later cases. Don't cite it.
- Flag anything you added from memory or secondary sources as unverified in
  `_author_notes`, and say so in your reply.

## Review status

- Every new issue file starts `status: "unreviewed"`, with empty `last_reviewed` and `reviewed_by`.
- Only the maintainer (or another lawyer) marks an issue reviewed. Never set it yourself.
- If you change an issue's legal content (any field listed under "Review status" in
  `docs/SCHEMA.md`), set it back to `unreviewed` and say so.

## Who reads what

- **Motion text** (the court): `motion_heading`, sentence `text`, authorities.
- **Memo text** (the attorney): `practice_notes`, `review_conditions` and
  `excluded_explanations` display notes, and `fill_in` prompts (printed in the motion in
  brackets, for the attorney to replace).
- **Author notes** (the maintainer): any `_`-prefixed field. Never rendered. Notes about
  the state of the file — what's unverified, why something is structured a certain way —
  go here, never in `practice_notes`.

Wording: questions say "your client" (enforced by the validator). The motion never names the
client: headings and argument sentences use `{client}` and pronoun tokens, which print as
"[Client]" for the attorney to fill in (enforced; see `docs/SCHEMA.md`). Rule sentences may say
"a defendant" or "the defendant" for general statements of law. Memo notes say "your client" when the sentence is about this
client's case, and "the defendant" for general statements of law (not enforced — a judgment
call per sentence).

## Design principles (details in docs/SCHEMA.md)

- The question bank is content only. All ordering, branching, and skip logic belongs to
  the decision tree (not yet built). Never put flow logic on a question.
- Don't hand-maintain a field the code can derive from structure; it will drift.
- Motion text is paragraphs of sentences. One proposition per sentence. Citations live only in
  `authorities`, never in `text` (a short case name in italics, `*Name*`, is fine).
- Conditions reference option ids, never labels. Never change an id that conditions use.
- Conditions go on paragraphs, never sentences. Use a paragraph's `when` to keep propositions
  that help the prosecution out of the motion unless the facts make them relevant.

## Workflow

- Run `python3 scripts/validate.py` and `python3 -m unittest discover tests` before
  committing. Don't commit with validator errors.
- For design changes, discuss the options with the maintainer before writing files. If
  asked to stop and discuss, stop until the discussion is done.
- Ask before adding anything new to `docs/AUTHORING_GUIDE.md`. Correcting statements that
  have become wrong is fine; say what you changed.
- When a redesign changes how a fact is represented, remove the old representation
  everywhere, and extend the validator so the old format can't come back. Retired question
  ids don't need this: the unknown-question check already catches stale references.

## Open items

- Decision tree: built (`engine.next_question`; see "The interview" in `docs/SCHEMA.md`). Try it
  with `scripts/interview.py`; review its behavior with `scripts/interview_audit.py`. Next: use it
  as an attorney and see how the order and prompts feel.
- Website: built (`app/`, `scripts/site_api.py`, `scripts/docx_render.py`; build with
  `scripts/build_site.py`, see "The website" in `README.md`). It runs entirely in the browser:
  never add anything that sends answers off the page. The motion and memo download as .docx,
  with each sentence's citations in a footnote. The footer links to a Google Form for feedback
  (pre-filling only the current question, never answers). Next: visit/motion counts (counts only,
  never answers).

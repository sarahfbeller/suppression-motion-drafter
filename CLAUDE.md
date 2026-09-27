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
  says something, don't attach it. Leave the authority off the rule statement and record
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

- **Motion text** (the court): `motion_heading`, rule statement `text`, authorities.
- **Memo text** (the attorney): `practice_notes`, `review_conditions` and
  `excluded_explanations` display notes.
- **Author notes** (the maintainer): any `_`-prefixed field. Never rendered. Notes about
  the state of the file — what's unverified, why something is structured a certain way —
  go here, never in `practice_notes`.

## Design principles (details in docs/SCHEMA.md)

- The question bank is content only. All ordering, branching, and skip logic belongs to
  the decision tree (not yet built). Never put flow logic on a question.
- Don't hand-maintain a field the code can derive from structure; it will drift.
- One proposition per rule statement. Citations live only in `authorities`, never in `text`.
- Conditions reference option ids, never labels. Never change an id that conditions use.
- Use a rule statement's `when` to keep propositions that help the prosecution out of the
  motion unless the facts make them relevant.

## Workflow

- Run `python3 scripts/validate.py` and `python3 -m unittest discover tests` before
  committing. Don't commit with validator errors.
- For design changes, discuss the options with the maintainer before writing files. If
  asked to stop and discuss, stop until the discussion is done.
- Ask before adding anything new to `docs/AUTHORING_GUIDE.md`. Correcting statements that
  have become wrong is fine; say what you changed.
- When a redesign changes how a fact is represented, remove the old representation
  everywhere, and extend the validator so it can't come back.

## Open items

- The decision tree (top-level "what kind of encounter was this" branching) is undesigned.
- Franks: answering "unknown" for intent silently excludes the issue; the policy for
  uncertain answers isn't settled.
- Unused questions: `q_duration`, `q_contact_timeline`, `q_passenger_ordered_out`, `q_stop_type`.
- Citations don't yet support short forms (*Id.*, short names) or signals (*See*).
- Most pincites are empty.
- Candidate authoring-guide additions awaiting the maintainer's decision: "use `when` to
  keep prosecution-favorable propositions out" and "run the validator before every commit."

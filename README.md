# Suppression motion generator

A question wizard for defense attorneys. From the answers, it produces two documents:
a **motion** (court-facing argument sections with rule paragraphs and citations) and an
**attorney memo** (review notes, practice notes, near misses, and gaps — never filed).

## Layout

- `content/config.json` — courts, and `motion_order`: the order of issues in the motion, grouped by phase
- `content/questions/` — the question bank, grouped by fact-pattern topic
- `content/issues/` — one file per suppression issue
- `scripts/validate.py` — checks all content; run before every commit
- `scripts/render.py` — reference renderer: case session in, motion and memo out
- `scripts/review_doc.py` — writes `review/content-review.md`, a readable review of every issue and question for legal review (edits go in the JSON; regenerate after)
- `scripts/engine.py` — condition evaluation, rendering logic, and the interview (`next_question`), shared by all the scripts
- `scripts/interview.py` — walk through the interview in the terminal, then see the motion and memo
- `scripts/interview_audit.py` — report how the interview behaves across simulated cases (which events are present when each question is asked; interview lengths)
- `scripts/simulate.py` — random simulated cases, used by the interview tests and the audit
- `tests/` — confirms the validator catches every known class of content bug
- `examples/sessions/` — sample case sessions; `examples/output/` — what they render to
- `docs/SCHEMA.md` — what each file and field is, and who reads it
- `docs/AUTHORING_GUIDE.md` — conventions and judgment calls for writing content

## Commands (from the repo root, Python 3, no dependencies)

    python3 scripts/validate.py
    python3 -m unittest discover tests
    python3 scripts/render.py examples/sessions/state-dui.json examples/sessions/federal-stop.json

All legal content is unreviewed until an attorney signs off on each issue file.

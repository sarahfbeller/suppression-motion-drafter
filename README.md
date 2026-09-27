# Suppression motion generator

A question wizard for defense attorneys. From the answers, it produces two documents:
a **motion** (court-facing argument sections with rule paragraphs and citations) and an
**attorney memo** (review notes, practice notes, near misses, and gaps — never filed).

## Layout

- `content/config.json` — courts, and the phase order that sets the default order of the motion
- `content/session.json` — the forum/state/circuit questions asked first (placeholder until the decision tree exists)
- `content/questions/` — the question bank, grouped by fact-pattern topic
- `content/issues/` — one file per suppression issue
- `scripts/validate.py` — checks all content; run before every commit
- `scripts/render.py` — reference renderer: case session in, motion and memo out
- `scripts/engine.py` — condition evaluation and rendering logic shared by both
- `tests/` — confirms the validator catches every known class of content bug
- `examples/sessions/` — sample case sessions; `examples/output/` — what they render to
- `docs/SCHEMA.md` — what each file and field is, and who reads it
- `docs/AUTHORING_GUIDE.md` — conventions and judgment calls for writing content

## Commands (from the repo root, Python 3, no dependencies)

    python3 scripts/validate.py
    python3 -m unittest discover tests
    python3 scripts/render.py examples/sessions/state-dui.json examples/sessions/federal-stop.json

All legal content is unreviewed until an attorney signs off on each issue file.

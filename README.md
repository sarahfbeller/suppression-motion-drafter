# Suppression motion generator

A question wizard for defense attorneys. From the answers, it produces two documents:
a **motion** (court-facing argument sections with rule paragraphs and citations) and an
**attorney memo** (review notes, practice notes, near misses, and gaps — never filed).

## Layout

- `content/config.json` — courts, and `motion_order`: the order of issues in the motion, grouped by phase (`phase_names` are the website's step names)
- `content/questions/` — the question bank, grouped by fact-pattern topic
- `content/issues/` — one file per suppression issue
- `scripts/validate.py` — checks all content; run before every commit
- `scripts/render.py` — reference renderer: case session in, motion and memo out
- `scripts/review_doc.py` — writes `review/content-review.md`, a readable review of every issue and question for legal review (edits go in the JSON; regenerate after)
- `scripts/engine.py` — condition evaluation, rendering logic, and the interview (`next_question`), shared by all the scripts
- `scripts/interview.py` — walk through the interview in the terminal, then see the motion and memo
- `scripts/interview_audit.py` — report how the interview behaves across simulated cases (which events are present when each question is asked; interview lengths)
- `scripts/simulate.py` — random simulated cases, used by the interview tests and the audit
- `app/` — the website: a wizard that runs the engine in the browser (Pyodide); see "The website" below
- `scripts/site_api.py` — what the website calls: interview state from saved answers, and the documents
- `scripts/docx_render.py` — the motion (citations in footnotes) and memo as Word files
- `scripts/build_site.py` — builds the website into `dist/`, ready to upload
- `tests/` — confirms the validator catches every known class of content bug
- `examples/sessions/` — sample case sessions; `examples/output/` — what they render to
- `docs/SCHEMA.md` — what each file and field is, and who reads it
- `docs/AUTHORING_GUIDE.md` — conventions and judgment calls for writing content

## Commands (from the repo root, Python 3, no dependencies)

    python3 scripts/validate.py
    python3 -m unittest discover tests
    python3 scripts/render.py examples/sessions/state-dui.json examples/sessions/federal-stop.json

All legal content is unreviewed until an attorney signs off on each issue file.

## The website

A static site: everything, including the engine, runs in the visitor's browser through
[Pyodide](https://pyodide.org), so the answers never leave the computer. The site has no server
code and stores nothing.

Build it, then try it locally (it must be served over http, not opened as a file):

    python3 scripts/build_site.py
    python3 -m http.server 8000 --directory dist

and open http://localhost:8000. The build copies the page (`app/`), bundles `content/` and the
engine into `dist/bundle.json`, and adds its own copies of Pyodide and python-docx (downloaded once
into `.cache/` and checked against pinned hashes). Rebuild after any content or code change.

To publish, upload `dist/` to a static host. With Cloudflare Pages: create a project with
"direct upload" and drag in the `dist/` folder; each upload is a new version. The Word-file tests
in `tests/test_site.py` need `pip install python-docx` and are skipped without it.

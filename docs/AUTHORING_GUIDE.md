# Authoring Guide — Conventions & Judgment Calls

Working notes for writing new files in `content/questions/` and `content/issues/`.
Not read by the app — this is for whoever (you) is authoring content.

## Judgment calls to make on every issue

- [ ] **Which encounter event does this issue start from?** Every `match_condition` must
  require at least one event from `q_encounter_events` in its top-level `all` (the validator
  rejects it otherwise). Pick the event(s) whose absence means the issue can't arise at all.
  If the right set is an existing event group (e.g. `any_search`), use the group instead of
  listing the events.
  If no event fits, raise it with the maintainer rather than stretching one — the event list
  is hand-maintained on purpose. Finer facts (where in the car, which room) are follow-up
  questions, not new events.
- [ ] **Is there a near-miss worth explaining?** For each way `match_condition` can fail,
  decide if it's (a) just "the fact pattern doesn't apply" — no explanation needed — or
  (b) a legally meaningful close call the attorney should know about even though the issue
  isn't included. Only (b) gets an `excluded_explanations` entry. Don't add one reflexively
  for every failure mode — most failures are (a).
- [ ] **Does any review/excluded condition contradict the match condition?** If a
  `review_conditions` or `excluded_explanations` entry checks the same question as
  `match_condition`, verify the triggering answer is actually *compatible* with a match —
  not the literal opposite of what's required. A condition that can never co-occur with
  inclusion is dead code that will never reach the attorney.
- [ ] **Which review/excluded condition is this?**
  - Included, but shaky → `review_conditions` (shown in the attorney memo under that issue)
  - Excluded, but a documented close call → `excluded_explanations` (shown in the memo's
    "Issues considered but not included" section)
- [ ] **What happens on an uncertain answer?** For every `unknown` / `not_sure` / `unclear`
  option on a question in `match_condition`, decide explicitly — never let it exclude the issue
  silently (the validator rejects that). Default: include the issue on that answer and add a
  `review_conditions` note explaining what to develop; a drafted section is easy to delete, a
  missing one is easy to miss. Exclude with an `excluded_explanations` note only when the
  uncertainty means the argument shouldn't be drafted at all.
- [ ] **Is a cross-cutting concept trying to sneak in as a per-issue link?** Standing and
  fruit-of-the-poisonous-tree apply to every issue — don't reference them per issue. There is
  currently no place for concepts like these (`cross_cutting_reminders` was removed); raise it
  with the maintainer rather than adding one to an issue file.
- [ ] **Is a genuinely separate but related issue better left to the decision tree?** We
  removed `related_issues` entirely — trust that a well-built issue with its own
  `match_condition` will surface independently when its own facts are present. Don't
  hand-link issues just because they're doctrinally related.

## Gotchas in the matching logic itself

- **`excluded_explanations` must be checked for every unmatched issue, every time — not just
  when convenient.** The per-issue flow is: check `match_condition` first; if it passes, check
  `review_conditions` (memo note); if it fails, check `excluded_explanations` anyway (memo's
  near-miss section). It's easy to structurally treat `excluded_explanations` as an afterthought that only
  runs "if there's time" — but if it's skipped for any unmatched issue, a documented near-miss
  will silently fail to appear, with no error to signal the gap.

## Never fabricate legal content

- If you don't have real law to cite for a court, leave that court's authority off the rule
  statement — never a plausible-sounding but made-up citation, and never placeholder text
  (the validator rejects `PLACEHOLDER`, `TODO`, `FILL_IN`). A missing authority shows up in the
  memo as a gap; a fake citation that reads as real is far more dangerous.
- Same logic for circuits: don't borrow another circuit's case as a stand-in for your own
  circuit's law. Note the gap in `_author_notes` instead.
- Record anything unverified (a pincite from secondary notes, a case you haven't read) in
  `_author_notes`, not in `practice_notes`.

## What goes in a field vs. what gets derived

- If the machine can compute it from structure, don't hand-maintain it as a separate field —
  it'll drift out of sync. (We removed `uses_questions`, `question_bank_file`, and
  `related_issues` for this reason.)
- If it's information that exists *only* because you know it (schema rationale, what's still
  unverified) — that's fine to keep, in an `_`-prefixed
  field, even though no end user ever sees it. The test is "is this the only place this fact lives," not
  "will a human ever read this."
- `flag` (short, machine-readable) and `display_note` (attorney-facing sentence) are different
  things — never surface a `flag` value directly to the end user.

## Defaults for every new issue file

- `status: "unreviewed"` — only a human lawyer changes this, never set automatically. Set it
  back to `unreviewed` whenever the legal content changes.
- `last_reviewed: ""` and `reviewed_by: ""` — filled in only once review actually happens.
- `motion_heading` — required; the court-facing heading for this section of the motion.
- `pincite: ""` on every case authority until the pinpoint page is researched.

## Open items / things not yet decided

- Decision tree: the top layer (`q_encounter_events`) exists; the derived part that picks the
  next question hasn't been built.

# Authoring Guide — Conventions & Judgment Calls

Working notes for writing new files in `content/questions/` and `content/issues/`.
Not read by the app — this is for whoever (you) is authoring content.

## Judgment calls to make on every issue

- [ ] **Is there a near-miss worth explaining?** For each way `match_condition` can fail,
  decide if it's (a) just "the fact pattern doesn't apply" — no explanation needed — or
  (b) a legally meaningful close call the attorney should know about even though the issue
  isn't included. Only (b) gets an `excluded_explanations` entry. Don't add one reflexively
  for every failure mode — most failures are (a).
- [ ] **Does any review/excluded condition contradict the match condition?** If a
  `review_conditions` or `excluded_explanations` entry checks the same question as
  `match_condition`, verify the triggering answer is actually *compatible* with a match —
  not the literal opposite of what's required. A condition that can never co-occur with
  inclusion is dead code that will never reach the attorney. (This bug happened twice
  already — once with `q_independent_suspicion`, once with `q_intent` — before we caught
  the pattern.)
- [ ] **Which review/excluded condition is this?**
  - Included, but shaky → `review_conditions` (renders inline as `[NOTE: ...]` under that
    issue's law paragraph)
  - Excluded, but a documented close call → `excluded_explanations` (renders once, in the
    closing "Issues Considered But Not Included" section)
- [ ] **Is a cross-cutting concept trying to sneak in as a per-issue link?** Standing and
  fruit-of-the-poisonous-tree apply to every issue, always — they're handled once, globally,
  via `cross_cutting_reminders` in `manifest.json`, not referenced per issue. If a new concept
  applies universally rather than to one specific fact pattern, it probably belongs there, not
  in an issue file.
- [ ] **Is a genuinely separate but related issue better left to the decision tree?** We
  removed `related_issues` entirely — trust that a well-built issue with its own
  `match_condition` will surface independently when its own facts are present. Don't
  hand-link issues just because they're doctrinally related.

## Gotchas in the matching logic itself

- **`excluded_explanations` must be checked for every unmatched issue, every time — not just
  when convenient.** The per-issue flow is: check `match_condition` first; if it passes, check
  `review_conditions` (inline note); if it fails, check `excluded_explanations` anyway (closing
  section). It's easy to structurally treat `excluded_explanations` as an afterthought that only
  runs "if there's time" — but if it's skipped for any unmatched issue, a documented near-miss
  will silently fail to appear, with no error to signal the gap.

## Never fabricate legal content

- If you don't have real law to cite (state law especially, since scope so far is one state +
  federal), use an obvious placeholder (`status: "NEEDS_RESEARCH"`, `PLACEHOLDER — ...` text)
  — never a plausible-sounding but made-up citation. A fake citation that reads as real is far
  more dangerous than an obvious gap.
- Same logic for circuits: don't borrow another circuit's case as a stand-in for your own
  circuit's law. Mark it `NEEDS_RESEARCH` and note which circuit is actually needed.
- `circuits_reviewed` tracks which circuits have been *checked* for a split — a circuit can be
  in this list with no circuit-specific segment authored, meaning "checked, no split found."
  This is what lets `circuit_specific_authority_not_researched` distinguish "no split exists"
  from "nobody's looked yet." Keep it updated as you research each issue.

## What goes in a field vs. what gets derived

- If the machine can compute it from structure, don't hand-maintain it as a separate field —
  it'll drift out of sync. (We removed `uses_questions`, `question_bank_file`, and
  `related_issues` for this reason.)
- If it's information that exists *only* because you know it (schema rationale, "why this
  question isn't gating," a segment's authoring status) — that's fine to keep as a field, even
  though no end user ever sees it. The test is "is this the only place this fact lives," not
  "will a human ever read this."
- `flag` (short, machine-readable) and `display_note` (attorney-facing sentence) are different
  things — never surface a `flag` value directly to the end user.

## Defaults for every new issue file

- `status: "unreviewed"` — only a human lawyer changes this, never set automatically.
- `last_reviewed: ""` — filled in only once review actually happens.
- `circuits_reviewed: []` unless circuits have actually been checked.

## Open items / things not yet decided

- Decision tree's top-level branching (the "what kind of encounter was this" root
  categories) — not yet designed.
- Whether `non_gating_questions`-style explanatory fields should follow a consistent naming
  convention across issue files, or are fine being one-off per issue.

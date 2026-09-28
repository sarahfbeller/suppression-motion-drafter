# Content schema

What each content file and field is, and who reads it. The enforced version of this schema is
`scripts/validate.py`; engine behavior is in `scripts/engine.py` and `scripts/render.py`. If this
file disagrees with them, the code wins and this file should be corrected.

## Files

| File | Contents |
|---|---|
| `content/config.json` | `courts` and `phase_order` |
| `content/questions/*.json` | The question bank, grouped by topic. Every file in the directory is loaded. |
| `content/issues/*.json` | One issue per file; the file name is the issue id. Every file in the directory is loaded. |

Any key starting with `_` (e.g. `_author_notes`), in any file, is a note to the maintainer. It is
never rendered, and the validator ignores it when checking for unknown fields.

## Courts and the filing court

`config.courts` maps each court code to `{ kind, display_name }`. Codes are snake_case (`scotus`,
`9th_cir`, `ak`). `kind` is `scotus`, `circuit`, or `state`; it orders parallel citations (Supreme
Court, then circuit, then state) and says whether a filing is in state or federal court.

`q_filing_court` (in `content/questions/case-setup.json`) asks where the motion is being filed.
Its option ids are the state and circuit court codes. The courts whose authority is cited in a
case are `scotus` plus that answer, so circuit authority is never cited in a state-court motion,
and state authority never in a federal one.

It's the one question the engine reads directly. Conditions can't use it: where an issue or rule
statement is the law goes in its `applicable_courts`.

## Encounter events

`q_encounter_events` (in `content/questions/case-setup.json`) is a multi-select checklist of what
happened in the encounter: stops and contacts, searches, statements and identifications, chemical
tests. It's the hand-written top of the decision tree; everything below it will be derived from
issue conditions.

- Events are facts, not legal conclusions ("police stopped a vehicle," not "seizure"), and the
  attorney checks all that apply (a bag opened in a car is both `search_vehicle` and
  `search_container`).
- Finer distinctions (inside the home vs. its yard, trunk vs. passenger compartment) are
  follow-up questions under an event, not more events.
- Every issue's `match_condition` must require an event: its top-level `all` includes
  `{ q_encounter_events includes <event> }`, or an `any` made only of those. That's what lets the
  tree skip an issue's questions when its event didn't happen.

## Case session

A case session is `{ answers }`: question id → answer (see question types). It must answer
`q_filing_court`. A question the tree skipped is absent.

## Questions

Each question is `{ id, type, prompt, options? }`. Ids look like `q_snake_case`.

| Type | Options | Answer |
|---|---|---|
| `yes_no` | none | `"yes"` or `"no"` |
| `multiple_choice` | required | one option id |
| `multi_select` | required | array of option ids, possibly empty |
| `short_text` | none | free text; never used in a condition |

Options are `{ id, label }`. The id is stored in answers and used by conditions; the label is
display text and can be reworded freely. Never change an id that a condition uses. If an option's
meaning changes, give it a new id and update every condition.

Questions hold content only. Ordering, branching, and skip logic belong to the decision tree.

## Issues

| Field | Meaning |
|---|---|
| `id` | Lowercase slug, same as the file name. |
| `phase` | When in the encounter the violation happened; one of `config.phase_order`. Sets the default order of sections in the motion. |
| `label` | Memo name for the issue; may include case names. |
| `motion_heading` | Court-facing argument heading. Advocacy, no citations. |
| `status`, `last_reviewed`, `reviewed_by` | See review status. |
| `applicable_courts` | Where the issue exists at all (see below). |
| `trigger` | `{ match_condition, review_conditions?, excluded_explanations? }` |
| `law_paragraph` | `{ rule_statements: [...] }` |
| `practice_notes` | Tips for the attorney. Memo only. |

**Order in the motion.** Issues are ordered by `phase`, then alphabetically by id. If two issues in
the same phase need a set order, split the phase rather than adding an ordering field. Attorneys
reorder sections in their own documents; the app doesn't.

**`applicable_courts`.** `["scotus"]` means the issue applies in every forum; don't also list the
circuit or state. List a specific court alone (e.g. `["ak"]`) when the issue rests on that court's
own law and hasn't been confirmed anywhere else. If none of the case's courts are in the list, the
issue is skipped entirely: nothing about it is rendered.

**`trigger`.**

- `match_condition`: the issue is included when this is true. Must require an encounter event
  (see above).
- `review_conditions`: `[{ when, flag, display_note }]`. For an included issue, each note whose
  `when` is true goes in the memo under that issue.
- `excluded_explanations`: same shape. For an issue that didn't match, each note whose `when` is
  true goes in the memo's "considered but not included" section. These are checked for every
  unmatched issue.

**Uncertain answers never exclude an issue silently.** If answering `unknown`, `not_sure`, or
`unclear` would exclude an issue that another answer would include, the validator requires one of:

- Include the issue on that answer, with a review condition explaining the uncertainty. This is
  the default: a drafted section is easy to delete, a missing one is easy to miss.
- An excluded explanation for that answer, when the uncertainty means the argument shouldn't be
  drafted at all.

`flag` is a short snake_case id, unique within the issue. It is never rendered.

## Conditions

Used by `match_condition`, every `when`, and nothing else. A condition is a leaf
`{ question, op, value }` or a compound `{ all: [...] }` / `{ any: [...] }`; compounds can nest.
Values are option ids, never labels.

| Question type | Ops |
|---|---|
| `yes_no`, `multiple_choice` | `equals`, `not_equals` (one id); `in`, `not_in` (list of ids) |
| `multi_select` | `includes`, `not_includes` (one id); `not_empty`, `empty` (no value) |

If a leaf's question is unanswered, the leaf is false for every op, including the negative ones.
A condition can only be satisfied by answers the attorney actually gave.

## Rule statements

`law_paragraph.rule_statements` is an ordered list of `{ id, text, when?, applicable_courts?, authorities }`.

- `text`: one proposition (a sentence, two at most). Never a case name or citation, even
  mid-sentence. May be a direct quotation. Ends with sentence punctuation.
- `when`: optional condition. Use it for facts that change which propositions belong in the
  motion, and to keep propositions that help the prosecution out unless the facts make them relevant.
- `applicable_courts`: optional; where this proposition is the law. Same meaning as the issue's
  field, and defaults to it. Use it only to narrow: an Alaska-only proposition inside a
  `["scotus"]` issue gets `["ak"]`. It can't list a court the issue doesn't apply in, and every
  authority must be citable there (SCOTUS authority always is).
- `authorities`: each one supports exactly this statement's text.

For each statement whose `when` is absent or true:

- It doesn't apply in this forum: skipped silently.
- It applies, and at least one authority is for one of the case's courts: rendered.
- It applies, but no authority is for the case's courts: dropped from the motion and listed in the
  memo as a gap, because research is missing.

Marking a proposition as applying only in some courts is a legal judgment that it isn't the law
elsewhere, and is reviewed like the rest of the statement.

## Authorities

`{ type, name, citation, pincite, court }`. `type` is `case`, `statute`, `constitution`, or `rule`.

- Cases: `citation` is `'<volume> <reporter> <first page> (<court> <year>)'`. `pincite` is
  required; it's the pinpoint for this statement's proposition, and empty until researched.
- Everything else: `citation` is `""` (the name is the citation) and there is no `pincite`.
- `court` is a code from `config.courts`: whose law this is, not which court decided it.

A case cites as *Name*, `<volume reporter page>, <pincite> (<court year>)`, with the pincite left
out when empty; anything else cites as its name. A statement's authorities are ordered Supreme
Court, then circuit, then state. Short forms (*Id.*) and signals (*See*) aren't supported yet.

The engine returns each surviving statement as its text plus its ordered authorities, never a
finished string, so each renderer decides where citations go. The markdown reference renderer
puts them inline after the statement, joined with `; `. The planned .docx output will put each
statement's authorities in a footnote.

## Review status

- `unreviewed`: the default for every new or edited issue. `last_reviewed` and `reviewed_by` are empty.
- `reviewed`: a lawyer has confirmed the rule statements and authorities are accurate and complete
  for every in-scope court the issue applies to. `last_reviewed` (YYYY-MM-DD) and `reviewed_by` are filled in.

Any change to `motion_heading`, `applicable_courts`, `trigger`, `law_paragraph`, or
`practice_notes` sets the status back to `unreviewed`. Not enforced by tooling yet.

## Who reads what

- **The court (motion):** `motion_heading`, rule statement `text`, authorities.
- **The attorney (memo):** `practice_notes`, and the `display_note` of review conditions and
  excluded explanations.
- **The maintainer:** `_`-prefixed fields, `flag`.

The test: would an attorney want this sentence in front of the court? Motion. In front of
themselves while deciding what to file? Memo. Is it about the state of the file? Author note.

## Output

**Motion:** an "ARGUMENT" heading, then one numbered section per included issue (I, II, III…) with
its `motion_heading` and law paragraph. Nothing else. If no issue produced a paragraph, a single
line says so.

**Memo** (never filed):

1. Case settings: forum, and whose authority was cited.
2. Included issues, numbered to match the motion: label; an unreviewed-content flag; a coverage
   note when a SCOTUS-grounded section cites no circuit or state authority; gaps; review notes that
   fired; practice notes. An issue that matched but had every statement dropped is listed here as
   "not in motion," with a note saying whether research is needed (its statements were gaps) or its
   content is broken (no statement applied). The validator rejects content that can produce the
   second case, when the answer space is small enough to check.
3. Issues considered but not included: excluded explanations that fired.

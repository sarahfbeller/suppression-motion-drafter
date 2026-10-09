# Content schema

What each content file and field is, and who reads it. The enforced version of this schema is
`scripts/validate.py`; engine behavior is in `scripts/engine.py` and `scripts/render.py`. If this
file disagrees with them, the code wins and this file should be corrected.

## Files

| File | Contents |
|---|---|
| `content/config.json` | `courts`, `motion_order`, and `event_groups` |
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

It's the one question the engine reads directly. Conditions can't use it: where an issue or
paragraph is the law goes in its `applicable_courts`.

## Client name and pronouns

The motion never contains the client's name, so attorneys don't have to enter it. Motion
headings and argument sentences refer to the client with tokens:

| Token | he/him | she/her | they/them | no pronouns (or unanswered) |
|---|---|---|---|---|
| `{client}` | [Client] | [Client] | [Client] | [Client] |
| `{they}` | he | she | they | [Client] |
| `{them}` | him | her | them | [Client] |
| `{their}` | his | her | their | [Client]'s |
| `{themself}` | himself | herself | themself | [Client] |
| `{were}` `{are}` `{have}` `{do}` | was, is, has, does | same | were, are, have, do | was, is, has, does |

`[Client]` is left in the motion for the attorney to replace with find and replace (a possessive
`[Client]'s` comes out right); the memo says how many places there are and asks the attorney to replace each with the name as it should appear in the motion (e.g. "Mr. Smith" or "Smith"). A capitalized token
(`{They}`, `{Were}`) prints capitalized, for a sentence start or a heading.

`q_client_pronouns` (in `content/questions/case-setup.json`) picks the column. Like
`q_filing_court`, only the engine reads it; conditions can't use it. Unanswered, the motion repeats
`[Client]` rather than guess.

The validator enforces:

- Tokens appear only in motion headings and argument sentences. Rule sentences state general law
  ("a person", "an arrestee", "a defendant").
- "the defendant" isn't used in a heading or argument sentence; write `{client}`.
- Only known tokens; a stray `{` or `}` is an error.
- A verb token comes right after `{they}`/`{They}`, and an agreeing verb right after `{they}` is a
  token (`{They} {were}`, never `{They} were`). After `{client}`, write the singular verb. A
  present-tense verb ending in -s after `{they}` gets a warning: rephrase with `{client}` as the
  subject.

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
  `{ q_encounter_events includes <event> }`, an `any` made only of those, or an event group. That's
  what lets the tree skip an issue's questions when its event didn't happen.

**Event groups.** `config.event_groups` names a set of events, such as `any_search`. A condition
leaf `{ "event_group": "any_search" }` means at least one of those events was checked; the engine
expands it into the equivalent `any`, and a group listed inside an `any` is merged into it. Use a
group instead of repeating the same list of events in several issues. The validator checks that
every member is an encounter event and warns about groups no issue uses.

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
| `label` | Memo name for the issue; may include case names. |
| `motion_heading` | Court-facing argument heading. Advocacy, no citations. Refers to the client with tokens (see above). |
| `status`, `last_reviewed`, `reviewed_by` | See review status. |
| `applicable_courts` | Where the issue exists at all (see below). |
| `trigger` | `{ match_condition, review_conditions?, excluded_explanations? }` |
| `law_paragraphs` | The motion text: an ordered list of paragraphs (see below). |
| `practice_notes` | Tips for the attorney. Memo only. |

**Order in the motion.** `config.motion_order` maps each phase of the encounter, in chronological
order, to the issues in that phase, in the order they appear in the motion. Every issue file must
be listed exactly once; the validator checks both directions. Where an issue goes is a judgment
call, so a new issue isn't done until it's placed. Attorneys reorder sections in their own
documents; the app doesn't.

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

**Uncertain answers never decide an issue silently.** This covers `unknown`, `not_sure`, and
`unclear` options on single-choice questions, and the same options checked alone on a checklist
(compared with checking something else, or leaving it blank). Wherever such an answer changes
whether an issue is included, the validator requires one of:

- Include the issue on that answer, with a review condition that fires on it and explains the
  uncertainty. This is the default: a drafted section is easy to delete, a missing one is easy to
  miss.
- An excluded explanation for that answer, when the uncertainty means the argument shouldn't be
  drafted at all.

Each issue needs its own note; a note on a related issue doesn't count.

`flag` is a short snake_case id, unique within the issue. It is never rendered.

## Conditions

Used by `match_condition`, every `when`, and nothing else. A condition is a leaf
`{ question, op, value }`, an event group leaf `{ event_group }` (see above), or a compound `{ all: [...] }` / `{ any: [...] }`; compounds can nest.
Values are option ids, never labels.

| Question type | Ops |
|---|---|
| `yes_no`, `multiple_choice` | `equals`, `not_equals` (one id); `in`, `not_in` (list of ids) |
| `multi_select` | `includes`, `not_includes` (one id); `not_empty`, `empty` (no value) |

If a leaf's question is unanswered, the leaf is false for every op, including the negative ones.
A condition can only be satisfied by answers the attorney actually gave.

## Paragraphs and sentences

`law_paragraphs` is an ordered list of `{ id, when?, applicable_courts?, sentences }` (or a fill-in,
below). A paragraph
is the unit that's included or left out: its sentences have no conditions of their own, so a
sentence that leans on the one before it ("Under this test…", *Id.*, "For example…") never loses it.

- `when`: optional condition. Use it for facts that change what belongs in the motion, and to keep
  propositions that help the prosecution out unless the facts make them relevant. A sentence that
  only belongs on some facts goes in its own paragraph.
- `applicable_courts`: optional; where this paragraph is the law. Same meaning as the issue's
  field, and defaults to it. Use it only to narrow: an Alaska-only paragraph inside a `["scotus"]`
  issue gets `["ak"]`. It can't list a court the issue doesn't apply in, and every authority must
  be citable there (SCOTUS authority always is). Marking a paragraph as applying only in some
  courts is a legal judgment that it isn't the law elsewhere, and is reviewed like the rest.
- `sentences`: an ordered, non-empty list of `{ id, text, kind?, authorities }`. Sentence ids are
  unique across the whole issue.

A sentence:

- `text`: one proposition (a sentence, two at most). May be a direct quotation. Ends with sentence
  punctuation. No citations: never a full case name, reporter citation, statute, or *Id.* A short
  case name is allowed when marked `*Name*` (it renders in italics). The case must be cited for
  that same sentence, earlier in the same paragraph, or in an earlier paragraph of the issue that
  has no `when` (so it always prints first, as with "*Miranda* warnings"), and be cited in every
  forum where this paragraph applies. `*` is used for nothing else.
- `kind`: `"argument"` for reasoning that needs no citation, including anything about this
  client (client tokens are allowed only here); its `authorities` must be empty.
  Omitted, the sentence states law and needs authority.
- `authorities`: each one supports exactly this sentence's text.

For each paragraph whose `when` is absent or true and that applies in this forum:

- A cited sentence with at least one authority for the case's courts is rendered.
- A cited sentence with no authority for the case's courts is dropped from the motion and listed
  in the memo as a gap, because research is missing.
- An argument sentence is always rendered, so a paragraph made only of argument (such as an
  application paragraph after the rule paragraphs) is always rendered.
- A paragraph that has cited sentences but lost all of them as gaps isn't rendered, since its
  argument would rest on nothing.

An issue needs at least one cited sentence in the motion to be a section; argument alone isn't
one. The validator checks that every match leaves a paragraph with a cited sentence.

A paragraph that doesn't apply in this forum is skipped silently.

**Fill-ins.** Application text is generated only when the answers fully decide what it says (an
argument paragraph with a `when` and client tokens). Everything else is left to the attorney: a
paragraph `{ id, when?, applicable_courts?, fill_in }` is an instruction to the attorney, printed in
the motion as **[Fill in: …]** where the text belongs. It's written to the attorney ("your
client"), has no tokens or brackets, and ends with sentence punctuation. If a section renders no
fill-in of its own, the engine ends it with "[Fill in: Apply the law to your client's facts.]", so
no section is only law. The memo counts the prompts. Fill-ins don't count as law: an issue whose
only rendered paragraphs are fill-ins and argument isn't a section.

## Authorities

`{ type, name, citation, pincite, court, signal?, parenthetical? }`. `type` is `case`, `statute`,
`constitution`, or `rule`.

- Cases: `citation` is `'<volume> <reporter> <first page> (<court> <year>)'`. `pincite` is
  required; it's the pinpoint for this sentence's proposition, and empty until researched.
- Everything else: `citation` is `""` (the name is the citation) and there is no `pincite`.
- `court` is a code from `config.courts`: whose law this is, not which court decided it.
- `signal`: optional; one of `See`, `See also`, `See, e.g.,`, `E.g.,`, `Cf.`, `See generally`,
  written as at the start of a citation sentence. Omitted, the authority directly supports the
  sentence.
- `parenthetical`: optional; `{ text, authority? }`. `text` has no citations; a case it refers to
  goes in `authority` (a full authority without its own signal or parenthetical), which is checked
  like any other and printed after the text. Only here, the authority may also be
  `{ type: "secondary", name }` for a treatise or article a court cited ("citing 4 Wayne R.
  LaFave, …"); `name` is the whole citation. A secondary source is never authority on its own.

A case cites as *Name*, `<volume reporter page>, <pincite> (<court year>)`, with the pincite left
out when empty; anything else cites as its name. A sentence's authorities are ordered Supreme
Court, then circuit, then state. A signal is printed when it changes from the previous authority
in the same citation sentence, lowercased after the first.

**Short forms.** Authors always write the full authority; the renderer decides when it prints as
*Id.* A citation becomes *Id.* (or *Id.* at `<pincite>`) when the citation just before it, in the
same motion section, was to that one authority alone. Never after a citation to several
authorities, never to a case cited inside a parenthetical, and never when this citation has no
pincite but the previous one did. *Id.* doesn't reach into an earlier section, since attorneys
reorder sections. Other short forms (short case names in citations) aren't supported yet.

The engine returns each rendered paragraph as its sentences, and each sentence as its text plus
its ordered authorities, never a finished string, so each renderer decides where citations go.
The markdown reference renderer puts them inline after the sentence, joined with `; `, with a
blank line between paragraphs. The planned .docx output will put each sentence's authorities in a
footnote.

## Review status

- `unreviewed`: the default for every new or edited issue. `last_reviewed` and `reviewed_by` are empty.
- `reviewed`: a lawyer has confirmed the motion text and authorities are accurate and complete
  for every in-scope court the issue applies to. `last_reviewed` (YYYY-MM-DD) and `reviewed_by` are filled in.

Any change to `motion_heading`, `applicable_courts`, `trigger`, `law_paragraphs`, or
`practice_notes` sets the status back to `unreviewed`. Not enforced by tooling yet.

## Who reads what

- **The court (motion):** `motion_heading`, sentence `text`, authorities.
- **The attorney (memo):** `practice_notes`, and the `display_note` of review conditions and
  excluded explanations.
- **The maintainer:** `_`-prefixed fields, `flag`.

The test: would an attorney want this sentence in front of the court? Motion. In front of
themselves while deciding what to file? Memo. Is it about the state of the file? Author note.

## Output

**Motion:** an "ARGUMENT" heading, then one numbered section per included issue (I, II, III…) with
its `motion_heading` and law paragraphs, including fill-in prompts. Nothing else. If no issue produced a paragraph, a single
line says so.

**Memo** (never filed):

1. Case settings: forum, and whose authority was cited.
2. Included issues, numbered to match the motion: label; an unreviewed-content flag; a coverage
   note when a SCOTUS-grounded section cites no circuit or state authority; gaps; review notes that
   fired; practice notes. An issue that matched but rendered no paragraph is listed here as
   "not in motion," with a note saying whether research is needed (its sentences were gaps) or its
   content is broken (no paragraph applied). The validator rejects content that can produce the
   second case, when the answer space is small enough to check.
3. Issues considered but not included: excluded explanations that fired.

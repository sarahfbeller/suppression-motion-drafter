"""Shared logic for the suppression motion generator.

Used by validate.py (to check content) and render.py (to produce the motion and
memo), so both agree on exactly what a condition means and how text renders.
Standard library only.
"""
import copy
import glob
import json
import os
import re

SCALAR_OPS = {"equals", "not_equals", "in", "not_in"}
ARRAY_OPS = {"includes", "not_includes", "not_empty", "empty"}
VALUELESS_OPS = {"not_empty", "empty"}
LIST_VALUE_OPS = {"in", "not_in"}

KIND_RANK = {"scotus": 0, "circuit": 1, "state": 2}

SCOTUS = "scotus"
FILING_COURT = "q_filing_court"  # answer is the state or circuit court code whose law binds, besides SCOTUS
ENCOUNTER_EVENTS = "q_encounter_events"  # what happened in the encounter; every issue requires one of these.
# It's derived from the opening questions (config.encounter), never asked or stored directly.

CLIENT_PRONOUNS = "q_client_pronouns"  # which pronouns the motion uses for the client; read only by the engine

# The motion never contains the client's name: {client} prints as this marker, and the attorney
# fills it in with find and replace. Pronoun and verb tokens print to match the pronoun answer.
NAME_MARKER = "[Client]"
PRONOUN_FORMS = {  # token -> form for he_him, she_her, they_them, no_pronouns
    "they": ("he", "she", "they", NAME_MARKER),
    "them": ("him", "her", "them", NAME_MARKER),
    "their": ("his", "her", "their", NAME_MARKER + "'s"),
    "themself": ("himself", "herself", "themself", NAME_MARKER),
}
VERB_FORMS = {  # agree with {they}: singular for he, she, and the name; plural for they
    "were": ("was", "was", "were", "was"),
    "are": ("is", "is", "are", "is"),
    "have": ("has", "has", "have", "has"),
    "do": ("does", "does", "do", "does"),
}
PRONOUN_OPTIONS = ("he_him", "she_her", "they_them", "no_pronouns")

# Application text that the answers can't fully decide is left to the attorney: a fill-in paragraph
# prints as a bracketed instruction. A section with no fill-in of its own ends with this one.
GENERIC_FILL_IN = "Apply the law to your client's facts."
TOKEN_RE = re.compile(r"\{([A-Za-z]+)\}")

# '<volume> <reporter> <first page> (<court> <year>)'
CITATION_RE = re.compile(r"^(?P<base>\d+ .+? \d+) (?P<paren>\([^()]*\d{4}\))$")


# --------------------------------------------------------------------------- loading

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def content_files(root, kind):
    """Every JSON file in content/<kind>/, sorted by path."""
    return sorted(glob.glob(os.path.join(root, "content", kind, "*.json")))


def load_repo(root):
    """Load config, question bank (id -> question), and issues in output order."""
    config = load_json(os.path.join(root, "content", "config.json"))
    questions = {}
    for path in content_files(root, "questions"):
        for q in load_json(path):
            questions[q["id"]] = q
    questions[ENCOUNTER_EVENTS] = events_question(config, questions)
    groups = config.get("event_groups", {})
    issues = [expand_issue(load_json(path), groups)[0] for path in content_files(root, "issues")]
    return config, questions, ordered_issues(config, issues)


# --------------------------------------------------------------------------- encounter events
#
# The opening asks what happened in steps: a gateway checklist of categories (config.encounter.gateway),
# then each checked category's detail questions. A category is either a single event (checking it in
# the gateway is the event) or a list of detail questions: a checklist whose options are events, or a
# yes/no question that records one event on "yes" (config.encounter.yes_events). The events from all
# of these, together, are q_encounter_events, which is what conditions use.

def encounter_categories(config):
    return config["encounter"]["categories"]


def opening_questions(config):
    """Every question in the hand-written opening, in asking order (not counting which are skipped)."""
    out = [FILING_COURT, CLIENT_PRONOUNS, config["encounter"]["gateway"]]
    for cat in encounter_categories(config):
        out += cat.get("questions", [])
    return out


def events_question(config, questions):
    """q_encounter_events as a question (for conditions, the validator, and labels): every event, in
    the order the opening asks about them."""
    enc = config["encounter"]
    gateway = {o["id"]: o["label"] for o in questions[enc["gateway"]]["options"]}
    options = []
    for cat in encounter_categories(config):
        if "event" in cat:
            options.append({"id": cat["event"], "label": gateway.get(cat["option"], cat["event"])})
        for qid in cat.get("questions", []):
            q = questions[qid]
            if q["type"] == "multi_select":
                options += [dict(o) for o in q["options"]]
            else:
                ye = enc["yes_events"][qid]
                options.append({"id": ye["event"], "label": ye["label"]})
    return {"id": ENCOUNTER_EVENTS, "type": "multi_select", "options": options,
            "prompt": "What happened during the encounter? (derived from the opening questions)"}


def with_events(config, answers):
    """answers plus q_encounter_events, derived from the opening questions once they're all answered.
    Until then (or if q_encounter_events is already given, as in tests), answers is returned as is."""
    if ENCOUNTER_EVENTS in answers:
        return answers
    enc = config["encounter"]
    if enc["gateway"] not in answers:
        return answers
    events = []
    for cat in encounter_categories(config):
        if cat["option"] not in answers[enc["gateway"]]:
            continue
        if "event" in cat:
            events.append(cat["event"])
        for qid in cat.get("questions", []):
            if qid not in answers:
                return answers  # this category's details aren't answered yet
            a = answers[qid]
            if isinstance(a, list):
                events += a
            elif a == "yes":
                events.append(enc["yes_events"][qid]["event"])
    return {**answers, ENCOUNTER_EVENTS: events}


def answers_for_events(config, questions, events):
    """The opening answers that produce exactly these events (for simulations and tests)."""
    enc = config["encounter"]
    events = set(events)
    out, checked = {}, []
    for cat in encounter_categories(config):
        mine = set()
        if "event" in cat:
            mine = {cat["event"]} & events
        for qid in cat.get("questions", []):
            q = questions[qid]
            if q["type"] == "multi_select":
                mine |= {o["id"] for o in q["options"]} & events
            elif enc["yes_events"][qid]["event"] in events:
                mine.add(enc["yes_events"][qid]["event"])
        if mine:
            checked.append(cat["option"])
            for qid in cat.get("questions", []):
                q = questions[qid]
                if q["type"] == "multi_select":
                    out[qid] = [o["id"] for o in q["options"] if o["id"] in events]
                else:
                    out[qid] = "yes" if enc["yes_events"][qid]["event"] in events else "no"
    out[enc["gateway"]] = checked
    return out


def motion_order(config):
    """Every issue id in motion order: config.motion_order's phases in order, each phase's issues in order."""
    return [iid for ids in config["motion_order"].values() for iid in ids]


def ordered_issues(config, issues):
    """Order issues as listed in config.motion_order. Unlisted issues (a validator error) go last."""
    rank = {iid: i for i, iid in enumerate(motion_order(config))}
    return sorted(issues, key=lambda i: (rank.get(i.get("id"), len(rank)), i.get("id", "")))


# --------------------------------------------------------------------------- conditions

def eval_condition(cond, answers):
    """Evaluate a condition against answers (question id -> option id / list of ids).

    A leaf whose question is unanswered is always false, for every op.
    """
    if "all" in cond:
        return all(eval_condition(c, answers) for c in cond["all"])
    if "any" in cond:
        return any(eval_condition(c, answers) for c in cond["any"])
    qid = cond["question"]
    if qid not in answers:
        return False
    a, op, v = answers[qid], cond["op"], cond.get("value")
    if op == "equals":
        return a == v
    if op == "not_equals":
        return a != v
    if op == "in":
        return a in v
    if op == "not_in":
        return a not in v
    if op == "includes":
        return v in a
    if op == "not_includes":
        return v not in a
    if op == "not_empty":
        return len(a) > 0
    if op == "empty":
        return len(a) == 0
    raise ValueError(f"unknown op {op!r}")


def expand_event_groups(cond, groups, used, unknown):
    """Replace each {event_group: name} leaf with the 'any' of encounter events it stands for.

    An expanded group directly inside an 'any' is spliced into it, so "any of these two groups"
    becomes one flat 'any'. Names found in groups are added to used; others to unknown (left as is).
    """
    if set(cond) == {"event_group"}:
        name = cond["event_group"]
        if name not in groups:
            unknown.add(name)
            return cond
        used.add(name)
        return {"any": [{"question": ENCOUNTER_EVENTS, "op": "includes", "value": e} for e in groups[name]]}
    if "all" in cond:
        return {"all": [expand_event_groups(c, groups, used, unknown) for c in cond["all"]]}
    if "any" in cond:
        kids = []
        for c in cond["any"]:
            e = expand_event_groups(c, groups, used, unknown)
            kids.extend(e["any"] if set(c) == {"event_group"} and "any" in e else [e])
        return {"any": kids}
    return cond


def expand_issue(issue, groups):
    """A copy of issue with every event group in its conditions expanded. Returns (issue, used, unknown)."""
    issue, used, unknown = copy.deepcopy(issue), set(), set()
    trig = issue.get("trigger", {})
    if isinstance(trig.get("match_condition"), dict):
        trig["match_condition"] = expand_event_groups(trig["match_condition"], groups, used, unknown)
    for kind in ("review_conditions", "excluded_explanations"):
        for note in trig.get(kind, []):
            if isinstance(note, dict) and isinstance(note.get("when"), dict):
                note["when"] = expand_event_groups(note["when"], groups, used, unknown)
    for para in issue.get("law_paragraphs", []):
        if isinstance(para, dict) and isinstance(para.get("when"), dict):
            para["when"] = expand_event_groups(para["when"], groups, used, unknown)
    return issue, used, unknown


def is_event_gate(cond):
    """{q_encounter_events includes x}, or an 'any' made only of those (an expanded event group is one)."""
    def leaf(c):
        return c.get("question") == ENCOUNTER_EVENTS and c.get("op") == "includes"
    return leaf(cond) or ("any" in cond and all(leaf(c) for c in cond["any"]))


_GATES = {}  # id(match) -> (match, gate); the interview asks for the same gates over and over


def event_gate(match):
    """The event part of a match_condition: its top-level event gates, as one condition (None if it has none).
    The validator requires every issue to have one."""
    hit = _GATES.get(id(match))
    if hit is not None and hit[0] is match:
        return hit[1]
    kids = match["all"] if "all" in match else [match]
    gates = [c for c in kids if is_event_gate(c)]
    gate = {"all": gates} if gates else None
    _GATES[id(match)] = (match, gate)
    return gate


def near_miss_fires(match, when, answers):
    """An excluded explanation fires only when the issue's event happened: a near miss is about an
    encounter that took place, so with no such event there's nothing to explain."""
    gate = event_gate(match)
    return (gate is None or eval_condition(gate, answers)) and eval_condition(when, answers)


def condition_questions(cond):
    """All question ids referenced anywhere in a condition."""
    if "all" in cond or "any" in cond:
        out = set()
        for c in cond.get("all", []) + cond.get("any", []):
            out |= condition_questions(c)
        return out
    return {cond["question"]}


# --------------------------------------------------------------------------- courts & citations

def binding_courts(answers):
    """SCOTUS binds every forum; the filing court adds its state or circuit."""
    return [SCOTUS, answers[FILING_COURT]]


def applies_in(applicable_courts, courts):
    """Whether an issue or paragraph is the law in a case bound by courts.

    ['scotus'] applies everywhere, since SCOTUS is always a binding court.
    """
    return bool(set(applicable_courts) & set(courts))


def paragraph_courts(issue, para):
    """A paragraph's applicable_courts, defaulting to its issue's."""
    return para.get("applicable_courts", issue["applicable_courts"])


def court_rank(config, code):
    return KIND_RANK[config["courts"][code]["kind"]]


def citation_parts(a):
    """Split an authority into what a renderer needs, leaving the markup to the renderer.

    Returns { name, italic, rest }: a case is its italicized name, then ', ' and rest (the
    citation, with any pincite inserted before the parenthetical); anything else is its name alone.
    Signals and parentheticals are separate fields of the authority; the renderer adds them.
    """
    if a["type"] != "case":
        return {"name": a["name"], "italic": False, "rest": ""}
    cite = a["citation"]
    if a.get("pincite"):
        m = CITATION_RE.match(cite)
        cite = f"{m['base']}, {a['pincite']} {m['paren']}"
    return {"name": a["name"], "italic": True, "rest": cite}


def token_word(name):
    """The base token a {name} stands for ('They' -> 'they'), or None if it isn't one."""
    base = name[0].lower() + name[1:]
    if name == "client":
        return name
    if base in PRONOUN_FORMS or base in VERB_FORMS:
        return base
    return None


def fill_client(text, pronouns):
    """Replace {client}, pronoun, and verb tokens. pronouns is a q_client_pronouns answer, or None
    (unanswered), which repeats the name marker instead of guessing."""
    col = PRONOUN_OPTIONS.index(pronouns) if pronouns in PRONOUN_OPTIONS else PRONOUN_OPTIONS.index("no_pronouns")

    def sub(m):
        name = m.group(1)
        base = token_word(name)
        if base == "client":
            return NAME_MARKER
        word = (PRONOUN_FORMS.get(base) or VERB_FORMS[base])[col]
        return word[0].upper() + word[1:] if name[0].isupper() else word
    return TOKEN_RE.sub(sub, text)


def same_source(a, b):
    return all(a.get(k) == b.get(k) for k in ("type", "name", "citation", "court"))


def id_form(a, previous):
    """How a citation shortens to Id., given the authority cited just before it.

    previous is the sole authority of the immediately preceding citation, or None when that
    citation had several authorities (or there was none). Authorities inside parentheticals are
    never "the preceding citation". Returns None (cite in full), "" (Id.), or the pincite (Id. at <pincite>).
    """
    if previous is None or not same_source(a, previous):
        return None
    if a["type"] != "case" or a.get("pincite", "") == previous.get("pincite", ""):
        return ""
    return a.get("pincite") or None  # no pincite yet, after one that had one: cite in full


def law_paragraphs(issue, answers, courts, config):
    """Return (paragraphs, gap_sentence_texts) for one issue.

    paragraphs is the ordered list of paragraphs that render, each as { id, sentences } or, for a
    fill-in, { id, fill_in }. Each sentence is { id, text, kind, authorities } with authorities filtered to courts and in
    citation order (SCOTUS, circuit, state). A paragraph renders when its 'when' is absent or true
    and it applies in this forum. Inside it, a cited sentence with no authority for these courts
    is dropped and reported as a gap; an argument sentence always renders. A paragraph made only
    of argument (e.g. an application paragraph) renders as is, but one whose cited sentences were
    all dropped doesn't, since its argument would rest on nothing. Whether citations go inline or
    in footnotes is up to the renderer. If anything renders but no fill-in paragraph does, the
    generic one is added at the end, so no section is only law.
    """
    paragraphs, gaps = [], []
    for para in issue["law_paragraphs"]:
        if "when" in para and not eval_condition(para["when"], answers):
            continue
        if not applies_in(paragraph_courts(issue, para), courts):
            continue  # not the law in this forum, so not a gap either
        if "fill_in" in para:
            paragraphs.append({"id": para["id"], "fill_in": para["fill_in"]})
            continue
        sentences = []
        for st in para["sentences"]:
            kind = st.get("kind", "rule")
            auths = [a for a in st["authorities"] if a["court"] in courts]
            auths.sort(key=lambda a: court_rank(config, a["court"]))  # stable within a court
            if kind != "argument" and not auths:
                gaps.append(st["text"])
                continue
            sentences.append({"id": st["id"], "text": fill_client(st["text"], answers.get(CLIENT_PRONOUNS)),
                              "kind": kind, "authorities": auths})
        had_cited = any(st.get("kind", "rule") != "argument" for st in para["sentences"])
        if sentences and (not had_cited or has_cited(sentences)):
            paragraphs.append({"id": para["id"], "sentences": sentences})
    if paragraphs and not any("fill_in" in p for p in paragraphs):
        paragraphs.append({"id": "fill_in", "fill_in": GENERIC_FILL_IN})
    return paragraphs, gaps


def has_cited(sentences):
    return any(st.get("kind", "rule") != "argument" for st in sentences)


# --------------------------------------------------------------------------- the interview (decision tree)
#
# The opening of the interview is hand-written (opening_questions); everything after it is derived from the
# issues' conditions. A question is asked only if it appears in a condition that is still undecided
# and still matters to the output. Answers so far are the only state: an absent question hasn't been
# asked yet. Every question asked gets a real answer (there's no "skip").

def _eval3(cond, answers):
    """(value, open questions): value as in eval3; open questions are the unasked ones that can still
    decide it, left to right (empty once it's decided)."""
    if "all" in cond or "any" in cond:
        stop = False if "all" in cond else True
        undecided = []
        for c in cond.get("all", cond.get("any")):
            v, qs = _eval3(c, answers)
            if v is stop:
                return stop, []
            if v is None:
                undecided += [q for q in qs if q not in undecided]
        return (None, undecided) if undecided else (not stop, [])
    if cond["question"] not in answers:
        return None, [cond["question"]]
    return eval_condition(cond, answers), []


def eval3(cond, answers):
    """Like eval_condition, but a question that hasn't been asked yet is unknown: returns True, False,
    or None when the answer still depends on unasked questions. A decided result holds however those
    questions are answered, or if they're never asked (which renders as false)."""
    return _eval3(cond, answers)[0]


def open_questions(cond, answers):
    """Unasked questions that can still decide cond, in the order they appear (left to right)."""
    return _eval3(cond, answers)[1]


def issue_open_questions(issue, answers, courts):
    """The issue's questions that could still change the output, in asking order: its trigger first,
    then its near-miss explanations, review notes, and paragraphs, in the order they're written.

    An issue that can no longer match keeps only its near-miss questions, and only if its event
    happened (or may have). Near-miss questions count while the issue is still undecided too, so
    answering never makes an earlier topic relevant again."""
    if not applies_in(issue["applicable_courts"], courts):
        return []
    trig = issue["trigger"]
    match = trig["match_condition"]
    m, match_open = _eval3(match, answers)
    gate = event_gate(match)
    out = list(match_open)
    conds = []
    if m is not True and (gate is None or eval3(gate, answers) is not False):
        conds += [ex["when"] for ex in trig.get("excluded_explanations", [])]
    if m is not False:
        conds += [rc["when"] for rc in trig.get("review_conditions", [])]
        conds += [p["when"] for p in issue["law_paragraphs"]
                  if "when" in p and applies_in(paragraph_courts(issue, p), courts)]
    for c in conds:
        out += [q for q in open_questions(c, answers) if q not in out]
    return out


def next_question(config, issues, answers):
    """The id of the next question to ask, or None when the interview is done.

    The hand-written opening comes first: filing court, pronouns, the encounter gateway, then the
    detail questions of each category checked there. Then issues are taken one at a time in motion
    order (issues must already be ordered, as load_repo returns them), asking each one's open
    questions in order."""
    return next_step(config, issues, answers)[0]


OPENING = "opening"  # the phase of the hand-written opening questions


def issue_phases(config):
    """Issue id -> its config.motion_order phase."""
    return {iid: phase for phase, ids in config["motion_order"].items() for iid in ids}


def next_step(config, issues, answers):
    """(next question, the phase asking it), as next_question; the phase is OPENING for the opening.
    (None, None) when the interview is done."""
    for qid in (FILING_COURT, CLIENT_PRONOUNS):
        if qid not in answers:
            return qid, OPENING
    if ENCOUNTER_EVENTS not in answers:
        enc = config["encounter"]
        if enc["gateway"] not in answers:
            return enc["gateway"], OPENING
        for cat in encounter_categories(config):
            if cat["option"] in answers[enc["gateway"]]:
                for qid in cat.get("questions", []):
                    if qid not in answers:
                        return qid, OPENING
        answers = with_events(config, answers)
    courts = binding_courts(answers)
    phase = issue_phases(config)
    for issue in issues:
        for qid in issue_open_questions(issue, answers, courts):
            if qid not in answers:
                return qid, phase[issue["id"]]
    return None, None


def interview_path(config, issues, answers):
    """Replay the interview against saved answers. Returns (path, pending, asked):
    - path: the questions asked so far, in order, as (question, phase);
    - pending: the next question to ask, as (question, phase), or (None, None) when done;
    - asked: the answers to the questions on the path.

    Answers to questions off the path (left over after the attorney changed an earlier answer) are
    ignored, so evaluate the case on `asked`, never on the raw answers."""
    asked, path = {}, []
    while True:
        qid, phase = next_step(config, issues, asked)
        if qid is None or qid not in answers:
            return path, (qid, phase), asked
        asked[qid] = answers[qid]
        path.append((qid, phase))


def possible_phases(config, issues, answers):
    """The motion_order phases that could still ask a question, in order. Before the filing court is
    known, that's every phase. Answering only ever removes phases (see next_question)."""
    if FILING_COURT not in answers:
        return list(config["motion_order"])
    answers = with_events(config, answers)
    courts = binding_courts(answers)
    phase = issue_phases(config)
    live = {phase[i["id"]] for i in issues if issue_open_questions(i, answers, courts)}
    return [p for p in config["motion_order"] if p in live]


# --------------------------------------------------------------------------- session evaluation

def evaluate_session(config, issues, session):
    """Evaluate every issue for one case. Returns a structured result for rendering."""
    answers = with_events(config, session.get("answers", {}))
    courts = binding_courts(answers)
    specific = courts[1]
    result = {"courts": courts, "pronouns": answers.get(CLIENT_PRONOUNS),
              "included": [], "no_paragraph": [], "near_misses": []}

    for issue in issues:
        if not applies_in(issue["applicable_courts"], courts):
            continue
        trig = issue["trigger"]
        if eval_condition(trig["match_condition"], answers):
            paragraphs, gaps = law_paragraphs(issue, answers, courts, config)
            cited_courts = {a["court"] for p in paragraphs for st in p.get("sentences", []) for a in st["authorities"]}
            entry = {
                "issue": issue,
                "heading": fill_client(issue["motion_heading"], answers.get(CLIENT_PRONOUNS)),
                "paragraphs": paragraphs,
                "review_notes": [rc["display_note"] for rc in trig.get("review_conditions", [])
                                 if eval_condition(rc["when"], answers)],
                "gaps": gaps,
                "unreviewed": issue["status"] != "reviewed",
                "missing_specific_court": (SCOTUS in issue["applicable_courts"]
                                           and specific not in cited_courts),
            }
            # Argument with no law in front of it isn't a section.
            cited = any(has_cited(p.get("sentences", [])) for p in paragraphs)
            (result["included"] if cited else result["no_paragraph"]).append(entry)
        else:
            for ex in trig.get("excluded_explanations", []):
                if near_miss_fires(trig["match_condition"], ex["when"], answers):
                    result["near_misses"].append({"issue": issue, "note": ex["display_note"]})
    return result

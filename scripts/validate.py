#!/usr/bin/env python3
"""Validate all content in the repo.

Usage (from the repo root):
    python3 scripts/validate.py            # errors fail, warnings are printed
    python3 scripts/validate.py --strict   # warnings fail too

Errors mean something is broken. Warnings are worth reading but may be intentional.
"""
import glob
import itertools
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E  # noqa: E402

UNANSWERED = object()
ENUMERATION_LIMIT = 200_000
UNCERTAIN_OPTION_IDS = {"unknown", "not_sure", "unclear"}

QUESTION_TYPES = {"yes_no", "multiple_choice", "multi_select", "short_text"}
ISSUE_KEYS = {"id", "label", "motion_heading", "status", "last_reviewed",
              "reviewed_by", "applicable_courts", "trigger", "law_paragraphs", "practice_notes"}
TRIGGER_KEYS = {"match_condition", "review_conditions",
                "excluded_explanations"}
NOTE_KEYS = {"when", "flag", "display_note"}
PARAGRAPH_KEYS = {"id", "when", "applicable_courts", "sentences", "fill_in"}
SENTENCE_KEYS = {"id", "text", "kind", "authorities"}
SENTENCE_KINDS = {"rule", "argument"}
CASE_KEYS = {"type", "name", "citation", "pincite", "court"}
OTHER_AUTHORITY_KEYS = {"type", "name", "citation", "court"}
OPTIONAL_AUTHORITY_KEYS = {"signal", "parenthetical"}
PARENTHETICAL_KEYS = {"text", "authority"}
SIGNALS = {"See", "See also", "See, e.g.,", "E.g.,", "Cf.", "See generally"}
AUTHORITY_TYPES = {"case", "statute", "constitution", "rule"}
QUESTION_KEYS = {"id", "type", "prompt", "options"}

SLUG_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
OPTION_ID_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
QUESTION_ID_RE = re.compile(r"^q_[a-z0-9]+(?:_[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CITATION_IN_TEXT = [
    (re.compile(r"\b[A-Z][\w.'&-]* v\. [A-Z]"), "a case name"),
    (re.compile(r"\b\d+ (?:U\.S\.|S\. ?Ct\.|L\. ?Ed\.|F\.(?: ?Supp\.)?(?: ?\dd| ?4th)?|P\.(?: ?\dd)?) \d+"), "a reporter citation"),
    (re.compile(r"\bAS \d+\.\d+"), "an Alaska statute citation"),
    (re.compile(r"\b[Ii]d\. "), "an 'Id.' citation"),
    (re.compile(r"\b(?:Alaska|Fed\.) (?:Criminal Rule|Crim\.|R\.|Const\.)"), "a rule or constitution citation"),
    (re.compile(r"§"), "a section symbol"),
]
# Questions talk to the attorney ("your client"). The motion names the client only through {client}
# and pronoun tokens; "the defendant" is fine in a rule sentence stating general law.
DEFENDANT_RE = re.compile(r"\bdefendant", re.I)
THE_DEFENDANT_RE = re.compile(r"\bthe defendant", re.I)
BRACE_RE = re.compile(r"\{[^{}]*\}|[{}]")
AGREEING_VERBS = {"was": "were", "were": "were", "is": "are", "are": "are", "has": "have",
                  "have": "have", "does": "do", "do": "do"}
CLIENT_RE = re.compile(r"\bclient", re.I)
PLACEHOLDER_RE = re.compile(r"\b(?:PLACEHOLDER|FILL_IN|TODO|TBD|XXX)\b")
AUTHOR_NOTE_RE = re.compile(
    r"\b(?:prior draft|placeholder|todo|tbd|not (?:yet )?(?:verified|confirmed)|unverified|"
    r"no citation (?:was|has been)|needs? (?:more )?research|was removed|"
    r"this (?:rule statement|statement|segment|field)\b)", re.I)


class QuestionBank(dict):
    """id -> question for every question that passed structural checks.

    'broken' holds ids of questions that failed them (already reported), so
    conditions referencing them are skipped instead of crashing or double-reporting.
    """
    def __init__(self):
        super().__init__()
        self.broken = set()


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def err(self, where, msg):
        self.errors.append(f"{where}: {msg}")

    def warn(self, where, msg):
        self.warnings.append(f"{where}: {msg}")


def public_keys(d):
    return {k for k in d if not k.startswith("_")}


def check_keys(r, where, d, allowed, required=()):
    if not isinstance(d, dict):
        r.err(where, "expected an object")
        return False
    extra = public_keys(d) - allowed
    if extra:
        r.err(where, f"unknown field(s) {sorted(extra)} — stale field, or a typo? "
                     f"(author-only notes must start with '_')")
    missing = [k for k in required if k not in d]
    if missing:
        r.err(where, f"missing required field(s) {missing}")
    return not extra and not missing


def iter_public_strings(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if not k.startswith("_"):
                yield from iter_public_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from iter_public_strings(v)
    elif isinstance(node, str):
        yield node


def citation_in(text):
    for rx, what in CITATION_IN_TEXT:
        if rx.search(text):
            return what
    return None


def check_tokens(r, where, text, allowed):
    """Client tokens in motion text. Returns text with tokens removed, for the other text checks."""
    for m in BRACE_RE.finditer(text):
        t = m.group(0)
        name = t[1:-1] if len(t) > 2 else ""
        if not E.TOKEN_RE.fullmatch(t) or E.token_word(name) is None:
            r.err(where, f"unknown token {t!r} — tokens are {{client}}, {{they}} {{them}} {{their}} "
                         f"{{themself}}, and after {{they}}: {{were}} {{are}} {{have}} {{do}} "
                         f"(capitalize the pronoun and verb tokens for a sentence start or heading)")
            continue
        if not allowed:
            r.err(where, f"{t} in a rule sentence — rule sentences state general law; put sentences about "
                         f"this client in an argument sentence")
    words = re.findall(r"\{[A-Za-z]+\}|[A-Za-z']+", text)
    for prev, word in zip([None] + words, words):
        pt = E.token_word(prev[1:-1]) if prev and prev.startswith("{") else None
        wt = E.token_word(word[1:-1]) if word.startswith("{") else None
        if wt in E.VERB_FORMS and pt != "they":
            r.err(where, f"{word} must come right after {{they}} or {{They}} — it agrees with that pronoun "
                         f"(after {{client}}, write the singular verb)")
        if pt == "they" and not word.startswith("{"):
            if word.lower() in AGREEING_VERBS:
                r.err(where, f"{prev} {word}: write {{{AGREEING_VERBS[word.lower()]}}} so the verb agrees "
                             f"(it prints 'was' or 'were' to match, etc.)")
            elif re.fullmatch(r"[a-z]+[^s]s", word):
                r.warn(where, f"{prev} {word}: if '{word}' is a present-tense verb it won't agree with "
                              f"'they' — rephrase with {{client}} as the subject")
    return E.TOKEN_RE.sub(lambda m: "X", text)


# --------------------------------------------------------------------------- config


def load_or_report(r, root, rel):
    try:
        return E.load_json(os.path.join(root, rel))
    except Exception as e:  # noqa: BLE001
        r.err(rel, f"cannot load: {e}")
        return None


def check_config(r, root):
    if os.path.exists(os.path.join(root, "content", "manifest.json")):
        r.err("content/manifest.json", "the manifest was split up — config goes in content/config.json, "
                                       "schema documentation in docs/SCHEMA.md; issue and question files "
                                       "are found by directory")
    if os.path.exists(os.path.join(root, "content", "session.json")):
        r.err("content/session.json", f"the forum/state/circuit questions were replaced by the "
                                      f"{E.FILING_COURT} question in the question bank")
    where = "content/config.json"
    c = load_or_report(r, root, where)
    if c is None:
        return None
    if not check_keys(r, where, c, {"courts", "motion_order", "event_groups"}, ["courts", "motion_order"]):
        return None

    courts = {k: v for k, v in c["courts"].items() if not k.startswith("_")}
    for code, ct in courts.items():
        if not OPTION_ID_RE.match(code):
            r.err(where, f"court code {code!r} must be snake_case (court codes are option ids of {E.FILING_COURT})")
        check_keys(r, f"{where} courts[{code}]", ct, {"kind", "display_name"}, ["kind", "display_name"])
        if ct.get("kind") not in E.KIND_RANK:
            r.err(where, f"court {code!r} has invalid kind {ct.get('kind')!r}")
        if not ct.get("display_name"):
            r.err(where, f"court {code!r} has no display_name")
    if courts.get(E.SCOTUS, {}).get("kind") != "scotus":
        r.err(where, f"courts must define {E.SCOTUS!r} with kind 'scotus'")
    c["courts"] = courts

    mo = c["motion_order"]
    if not isinstance(mo, dict) or not mo or not all(isinstance(v, list) for v in mo.values()):
        r.err(where, "motion_order must be an object mapping each phase to a list of issue ids")
        c["motion_order"] = {}
    else:
        for ph in mo:
            if not SLUG_RE.match(str(ph)):
                r.err(where, f"motion_order phase {ph!r} must be a lowercase slug")
        seen = set()
        for iid in E.motion_order(c):
            if iid in seen:
                r.err(where, f"motion_order lists {iid!r} more than once")
            seen.add(iid)
        files = {os.path.splitext(os.path.basename(p))[0] for p in E.content_files(root, "issues")}
        for iid in sorted(seen - files):
            r.err(where, f"motion_order lists {iid!r}, but there's no content/issues/{iid}.json")
        for iid in sorted(files - seen):
            r.err(where, f"content/issues/{iid}.json isn't in motion_order — add it where it belongs in the motion")

    return c


def check_client_pronouns(r, questions):
    """Read only by the engine: its option ids are the pronoun sets fill_client knows."""
    where = f"question {E.CLIENT_PRONOUNS}"
    q = questions.get(E.CLIENT_PRONOUNS)
    if q is None:
        if E.CLIENT_PRONOUNS not in questions.broken:
            r.err(where, "missing — the engine needs it to print pronoun tokens")
        return
    if q["type"] != "multiple_choice" or sorted(o["id"] for o in q["options"]) != sorted(E.PRONOUN_OPTIONS):
        r.err(where, f"must be multiple_choice with exactly the options {list(E.PRONOUN_OPTIONS)}")


def check_encounter_events(r, questions):
    where = f"question {E.ENCOUNTER_EVENTS}"
    q = questions.get(E.ENCOUNTER_EVENTS)
    if q is None:
        if E.ENCOUNTER_EVENTS not in questions.broken:
            r.err(where, "missing — every issue's match_condition starts from an encounter event")
    elif q["type"] != "multi_select":
        r.err(where, "must be multi_select")
    sj = questions.get("q_search_justification")
    if sj and any(o["id"] == "warrant" for o in sj.get("options", [])):
        r.err("question q_search_justification", "has a 'warrant' option — warrants are recorded by the "
                                                 f"'warrant' option of {E.ENCOUNTER_EVENTS}, and this question "
                                                 "covers warrantless searches only")


def check_event_groups(r, questions, config):
    """config.event_groups: name -> non-empty list of q_encounter_events option ids."""
    where = "content/config.json event_groups"
    groups = config.setdefault("event_groups", {})
    if not isinstance(groups, dict):
        r.err(where, "must be an object mapping each group name to a list of events")
        config["event_groups"] = {}
        return
    q = questions.get(E.ENCOUNTER_EVENTS)
    events = {o["id"] for o in q["options"]} if q else set()
    for name, members in groups.items():
        if not SLUG_RE.match(str(name)):
            r.err(where, f"group name {name!r} must be a lowercase slug")
        if not isinstance(members, list) or not members:
            r.err(where, f"group {name!r} must be a non-empty list of events")
            continue
        if len(members) != len(set(members)):
            r.err(where, f"group {name!r} lists an event twice")
        for m in members:
            if q and m not in events:
                r.err(where, f"group {name!r}: {m!r} isn't an option of {E.ENCOUNTER_EVENTS}")


def check_event_gate(r, where, match):
    if E.event_gate(match) is None:
        r.err(where, f"match_condition must require an encounter event: put "
                     f"{{{E.ENCOUNTER_EVENTS} includes <event>}}, or an 'any' of those, "
                     f"directly in its top-level 'all'")


def check_filing_court(r, questions, config):
    """The one question the engine itself reads: its options are the state and circuit court codes."""
    where = f"question {E.FILING_COURT}"
    q = questions.get(E.FILING_COURT)
    if q is None:
        if E.FILING_COURT not in questions.broken:
            r.err(where, "missing — the engine needs it to know which courts bind the case")
        return
    if q["type"] != "multiple_choice":
        r.err(where, "must be multiple_choice")
        return
    courts = config["courts"]
    offered = {o["id"] for o in q["options"]}
    for code in sorted(offered):
        if courts.get(code, {}).get("kind") not in ("state", "circuit"):
            r.err(where, f"option {code!r} is not a state or circuit court in config courts")
    for code in sorted(set(courts) - offered):
        if courts[code]["kind"] != "scotus":
            r.warn(where, f"court {code!r} is in config but isn't offered as a filing court")


# --------------------------------------------------------------------------- questions

def check_questions(r, root):
    questions = QuestionBank()
    for path in E.content_files(root, "questions"):
        rel = os.path.relpath(path, root)
        try:
            data = E.load_json(path)
        except Exception as e:  # noqa: BLE001
            r.err(rel, f"cannot load: {e}")
            continue
        if not isinstance(data, list):
            r.err(rel, "question file must be a list")
            continue
        for q in data:
            qid = q.get("id", "?")
            where = f"{rel} {qid}"
            n_errors = len(r.errors)
            check_keys(r, where, q, QUESTION_KEYS, ["id", "type", "prompt"])
            if not QUESTION_ID_RE.match(str(qid)):
                r.err(where, "question id must look like q_snake_case")
            if qid in questions:
                r.err(where, "duplicate question id (also defined in another place)")
            if q.get("type") not in QUESTION_TYPES:
                r.err(where, f"invalid type {q.get('type')!r}")
                questions.broken.add(qid)
                continue
            if not q.get("prompt"):
                r.err(where, "empty prompt")
            elif DEFENDANT_RE.search(q["prompt"]):
                r.err(where, "prompt says 'defendant' — questions address the attorney, so say 'your client'")
            if q["type"] in ("yes_no", "short_text"):
                if "options" in q:
                    r.err(where, f"{q['type']} questions must not have options")
            else:
                opts = q.get("options")
                if not isinstance(opts, list) or not opts:
                    r.err(where, "needs a non-empty options list")
                    questions.broken.add(qid)
                    continue
                seen_ids, seen_labels = set(), set()
                for o in opts:
                    if not isinstance(o, dict) or set(o) != {"id", "label"}:
                        r.err(where, f"option must be exactly {{id, label}}: {o!r}")
                        continue
                    if not OPTION_ID_RE.match(o["id"]):
                        r.err(where, f"option id {o['id']!r} must be snake_case")
                    if o["id"] in seen_ids:
                        r.err(where, f"duplicate option id {o['id']!r}")
                    if o["label"] in seen_labels:
                        r.err(where, f"duplicate option label {o['label']!r}")
                    if not o["label"]:
                        r.err(where, "empty option label")
                    elif DEFENDANT_RE.search(o["label"]):
                        r.err(where, f"option {o['id']!r} says 'defendant' — say 'your client'")
                    seen_ids.add(o["id"])
                    seen_labels.add(o["label"])
            if len(r.errors) > n_errors:
                questions.broken.add(qid)
            else:
                questions[qid] = q
    return questions


def domain(q, refs=None):
    """Every possible answer to q, plus UNANSWERED.

    For multi_select, refs (the option ids some condition mentions) keeps this small: options no
    condition mentions are interchangeable, so one of them stands in for all. They still matter
    for 'empty' / 'not_empty'.
    """
    if q["type"] == "yes_no":
        vals = ["yes", "no"]
    elif q["type"] == "multiple_choice":
        vals = [o["id"] for o in q["options"]]
    else:  # multi_select: every subset
        ids = [o["id"] for o in q["options"]]
        if refs is not None:
            others = [i for i in ids if i not in refs]
            ids = [i for i in ids if i in refs] + others[:1]
        vals = [list(c) for n in range(len(ids) + 1) for c in itertools.combinations(ids, n)]
    return vals + [UNANSWERED]


def referenced_options(conds):
    """question id -> the option ids worth enumerating, given these conditions.

    Starts from the option ids the conditions mention, then keeps one representative of any
    options that are interchangeable: ones mentioned only as 'includes' leaves inside the same
    'any' groups (e.g. an issue that starts from any of ten encounter events). Swapping such
    options never changes any condition's value, so enumerating one of them is enough.

    Every question the conditions use gets an entry, even one used only as 'empty' / 'not_empty':
    its options are then all interchangeable, and one representative stands in for them.
    Pass only the conditions a check actually evaluates; options mentioned elsewhere in the
    issue don't change the outcome, and leaving them out keeps the enumeration small.
    """
    contexts = {}  # (question, option) -> set of places it's mentioned

    def group_of_includes(c):
        kids = c.get("any", [])
        return kids and all("question" in k and k.get("op") == "includes"
                            and k["question"] == kids[0]["question"] for k in kids)

    def walk(c, parent=None):
        if "all" in c or "any" in c:
            for k in c.get("all", []) + c.get("any", []):
                walk(k, c)
            return
        v = c.get("value")
        values = v if isinstance(v, list) else [] if v is None else [v]
        shared = parent is not None and c.get("op") == "includes" and group_of_includes(parent)
        for x in values:
            contexts.setdefault((c["question"], x), set()).add(id(parent) if shared else id(c))
    for c in conds:
        walk(c)

    refs, seen = {}, set()
    for c in conds:
        for q in E.condition_questions(c):
            refs.setdefault(q, set())
    for (q, x), ctx in contexts.items():
        sig = (q, frozenset(ctx))
        if sig not in seen:
            seen.add(sig)
            refs[q].add(x)
    return refs


# --------------------------------------------------------------------------- conditions

def check_condition(r, where, cond, questions):
    """Structural check. Returns True if the condition is safe to evaluate."""
    if not isinstance(cond, dict):
        r.err(where, "condition must be an object")
        return False
    if "all" in cond or "any" in cond:
        if len(cond) != 1:
            r.err(where, "a compound condition must have exactly one key, 'all' or 'any'")
            return False
        kids = cond.get("all", cond.get("any"))
        if not isinstance(kids, list) or not kids:
            r.err(where, "'all'/'any' needs a non-empty list")
            return False
        return all([check_condition(r, where, c, questions) for c in kids])
    if not check_keys(r, where, cond, {"question", "op", "value"}, ["question", "op"]):
        return False
    qid, op = cond["question"], cond["op"]
    if qid in getattr(questions, "broken", ()):
        return False  # already reported where the question is defined
    if qid == E.FILING_COURT:
        r.err(where, f"conditions can't use {qid} — where an issue or paragraph is the law "
                     f"goes in its applicable_courts")
        return False
    if qid == E.CLIENT_PRONOUNS:
        r.err(where, f"conditions can't use {qid} — it only decides how pronoun tokens print")
        return False
    q = questions.get(qid)
    if q is None:
        r.err(where, f"references unknown question {qid!r}")
        return False
    qt = q["type"]
    if qt == "short_text":
        r.err(where, f"{qid} is short_text and can't be used in a condition")
        return False
    allowed = E.ARRAY_OPS if qt == "multi_select" else E.SCALAR_OPS
    if op not in allowed:
        r.err(where, f"op {op!r} can't be used with {qt} question {qid} (allowed: {sorted(allowed)})")
        return False
    valid = set(domain(q)) - {UNANSWERED} if qt != "multi_select" else {o["id"] for o in q["options"]}
    if op in E.VALUELESS_OPS:
        if "value" in cond:
            r.err(where, f"op {op!r} takes no value")
            return False
        return True
    if "value" not in cond:
        r.err(where, f"op {op!r} needs a value")
        return False
    v = cond["value"]
    if op in E.LIST_VALUE_OPS:
        if not isinstance(v, list) or not v:
            r.err(where, f"op {op!r} needs a non-empty list of option ids")
            return False
        bad = [x for x in v if x not in valid]
    else:
        if isinstance(v, list):
            r.err(where, f"op {op!r} takes a single option id, not a list")
            return False
        bad = [] if v in valid else [v]
    if bad:
        r.err(where, f"{qid}: {bad} not valid option ids (valid: {sorted(valid)})")
        return False
    return True


def assignments(qids, questions, refs=None):
    qids = sorted(qids)
    refs = refs or {}
    for combo in itertools.product(*(domain(questions[q], refs.get(q)) for q in qids)):
        yield {q: v for q, v in zip(qids, combo) if v is not UNANSWERED}


def space_size(qids, questions, refs=None):
    refs = refs or {}
    n = 1
    for q in qids:
        n *= len(domain(questions[q], refs.get(q)))
    return n


# --------------------------------------------------------------------------- issues

def check_applicable_courts(r, where, ac, courts):
    """Shared by issues and paragraphs. Returns the valid codes (empty if the list is unusable)."""
    if not isinstance(ac, list) or not ac:
        r.err(where, "applicable_courts must be a non-empty list")
        return []
    for c in ac:
        if c not in courts:
            r.err(where, f"applicable_courts has unknown court {c!r}")
    if len(ac) != len(set(ac)):
        r.err(where, "applicable_courts has duplicates")
    if E.SCOTUS in ac and len(ac) > 1:
        r.warn(where, f"applicable_courts lists {E.SCOTUS!r} plus other courts — it alone already covers every forum")
    return [c for c in ac if c in courts]


def citable_courts(ac, courts):
    """Courts whose authority can ever be cited where applicable_courts ac is the law."""
    if E.SCOTUS in ac:
        return set(courts)
    return {E.SCOTUS} | set(ac)


def check_issue(r, where, issue, config, questions, used_questions):
    if not check_keys(r, where, issue, ISSUE_KEYS, sorted(ISSUE_KEYS)):
        if not all(k in issue for k in ("trigger", "law_paragraphs", "applicable_courts")):
            return
    courts = config["courts"]

    if not SLUG_RE.match(str(issue.get("id", ""))):
        r.err(where, "id must be a lowercase slug")
    if not issue.get("label"):
        r.err(where, "empty label")
    heading = issue.get("motion_heading", "")
    if not heading:
        r.err(where, "empty motion_heading")
    else:
        if citation_in(heading):
            r.err(where, f"motion_heading contains {citation_in(heading)}")
        plain = check_tokens(r, f"{where} motion_heading", heading, allowed=True)
        if CLIENT_RE.search(plain):
            r.err(where, "motion_heading says 'client' — write {client}, which prints as a name to fill in")
        if THE_DEFENDANT_RE.search(plain):
            r.err(where, "motion_heading says 'the defendant' — write {client} (or a pronoun token) instead")

    status = issue.get("status")
    if status not in ("unreviewed", "reviewed"):
        r.err(where, f"status must be 'unreviewed' or 'reviewed', not {status!r}")
    elif status == "reviewed":
        if not DATE_RE.match(issue.get("last_reviewed", "")):
            r.err(where, "reviewed issues need last_reviewed as YYYY-MM-DD")
        if not issue.get("reviewed_by"):
            r.err(where, "reviewed issues need reviewed_by")
    elif issue.get("last_reviewed") or issue.get("reviewed_by"):
        r.err(where, "unreviewed issues must have empty last_reviewed and reviewed_by")

    ac = check_applicable_courts(r, where, issue.get("applicable_courts", []), courts)

    for s in iter_public_strings(issue):
        if PLACEHOLDER_RE.search(s):
            r.err(where, f"placeholder text found: {s[:70]!r}")

    # ---- trigger
    trig = issue.get("trigger", {})
    check_keys(r, f"{where} trigger", trig, TRIGGER_KEYS, ["match_condition"])
    conds_ok = True
    match = trig.get("match_condition")
    if match is not None:
        conds_ok &= check_condition(r, f"{where} match_condition", match, questions)
        if conds_ok:
            used_questions |= E.condition_questions(match)
            check_event_gate(r, where, match)

    flags = set()
    for kind in ("review_conditions", "excluded_explanations"):
        for i, note in enumerate(trig.get(kind, [])):
            nw = f"{where} {kind}[{i}]"
            if not check_keys(r, nw, note, NOTE_KEYS, sorted(NOTE_KEYS)):
                conds_ok = False
                continue
            ok = check_condition(r, nw, note["when"], questions)
            conds_ok &= ok
            if ok:
                used_questions |= E.condition_questions(note["when"])
            if not SLUG_RE.match(note["flag"]) or "-" in note["flag"]:
                r.err(nw, f"flag {note['flag']!r} must be snake_case")
            if note["flag"] in flags:
                r.err(nw, f"duplicate flag {note['flag']!r}")
            flags.add(note["flag"])
            if not note["display_note"]:
                r.err(nw, "empty display_note")
            elif AUTHOR_NOTE_RE.search(note["display_note"]):
                r.warn(nw, "display_note reads like a note to the author, but it's shown to the "
                           "attorney — move it to an '_'-prefixed field?")

    # ---- law paragraphs
    if "law_paragraph" in issue:
        r.err(where, "law_paragraph (a flat list of rule_statements) was replaced by law_paragraphs: "
                     "a list of { id, when?, applicable_courts?, sentences }")
    paragraphs = issue.get("law_paragraphs", [])
    if not isinstance(paragraphs, list) or not paragraphs:
        r.err(where, "law_paragraphs must be a non-empty list")
        paragraphs = []
    para_ids, sentence_ids = set(), set()
    counts = {"missing_pincites": 0, "cases": 0}
    good_paragraphs = []
    for para in paragraphs:
        pw = f"{where} paragraph {para.get('id', '?') if isinstance(para, dict) else '?'}"
        if not check_keys(r, pw, para, PARAGRAPH_KEYS, ["id"]):
            continue
        if ("sentences" in para) == ("fill_in" in para):
            r.err(pw, "a paragraph has either 'sentences' (motion text) or 'fill_in' (an instruction to "
                      "the attorney), and not both")
            continue
        if not SLUG_RE.match(str(para["id"])):
            r.err(pw, "id must be a lowercase slug")
        if para["id"] in para_ids:
            r.err(pw, "duplicate paragraph id")
        para_ids.add(para["id"])
        if "when" in para:
            ok = check_condition(r, pw + " when", para["when"], questions)
            conds_ok &= ok
            if ok:
                used_questions |= E.condition_questions(para["when"])
        p_ac = ac
        if "applicable_courts" in para:
            p_ac = check_applicable_courts(r, pw, para["applicable_courts"], courts)
            if E.SCOTUS not in ac:
                broader = [c for c in p_ac if c not in ac]
                if broader:
                    r.err(pw, f"applicable_courts has {broader}, but the issue only applies in {sorted(ac)}")
            if p_ac and set(p_ac) == set(ac):
                r.warn(pw, "applicable_courts is the same as the issue's — remove it; paragraphs inherit it")
        if "fill_in" in para:
            check_fill_in(r, pw, para["fill_in"])
            good_paragraphs.append(para)
            continue
        sentences = para["sentences"]
        if not isinstance(sentences, list) or not sentences:
            r.err(pw, "sentences must be a non-empty list")
            continue
        for st in sentences:
            check_sentence(r, pw, st, p_ac, "applicable_courts" in para, courts, sentence_ids, counts)
        good_paragraphs.append(para)
    if counts["missing_pincites"]:
        r.warn(where, f"{counts['missing_pincites']} of {counts['cases']} case authorities have no pincite yet")

    # ---- practice notes
    pn = issue.get("practice_notes", [])
    if not isinstance(pn, list):
        r.err(where, "practice_notes must be a list")
        pn = []
    for note in pn:
        if not isinstance(note, str) or not note:
            r.err(where, "practice_notes entries must be non-empty strings")
        elif AUTHOR_NOTE_RE.search(note):
            r.warn(f"{where} practice_notes", f"reads like a note to the author, but practice notes "
                                               f"go to the attorney — move it to '_author_notes'? {note[:70]!r}")

    if conds_ok and match is not None:
        check_reachability(r, where, trig, good_paragraphs, questions)
        check_every_match_has_a_paragraph(r, where, issue, good_paragraphs, questions, courts)


def check_fill_in(r, pw, text):
    """A fill-in is an instruction to the attorney, printed in the motion in brackets."""
    if not isinstance(text, str) or not text:
        r.err(pw, "fill_in must be a non-empty instruction to the attorney")
        return
    if BRACE_RE.search(text):
        r.err(pw, "fill_in is written to the attorney, so it doesn't use client tokens — say 'your client'")
    if "[" in text or "]" in text:
        r.err(pw, "fill_in can't contain brackets; the renderer adds them")
    if not re.search(r"[.?!]$", text):
        r.err(pw, "fill_in must end with sentence punctuation")


def check_sentence(r, pw, st, p_ac, narrowed, courts, sentence_ids, counts):
    """One sentence of a paragraph. p_ac is where the paragraph is the law."""
    sw = f"{pw} sentence {st.get('id', '?') if isinstance(st, dict) else '?'}"
    if isinstance(st, dict) and ("when" in st or "applicable_courts" in st):
        r.err(sw, "sentences can't have 'when' or applicable_courts — put the condition on the paragraph, "
                  "or move the sentence to its own paragraph")
        st = {k: v for k, v in st.items() if k not in ("when", "applicable_courts")}
    if not check_keys(r, sw, st, SENTENCE_KEYS, ["id", "text", "authorities"]):
        return
    if not SLUG_RE.match(st["id"]):
        r.err(sw, "id must be a lowercase slug")
    if st["id"] in sentence_ids:
        r.err(sw, "duplicate sentence id (ids are unique across the issue's paragraphs)")
    sentence_ids.add(st["id"])
    kind = st.get("kind", "rule")
    if kind not in SENTENCE_KINDS:
        r.err(sw, f"kind must be one of {sorted(SENTENCE_KINDS)}, not {kind!r}")
    if "kind" in st and kind == "rule":
        r.warn(sw, "kind 'rule' is the default — remove it")
    auths = st["authorities"]
    if not isinstance(auths, list):
        r.err(sw, "authorities must be a list")
        return
    text = st["text"]
    if not text:
        r.err(sw, "empty text")
    else:
        what = citation_in(text)
        if what:
            r.err(sw, f"text embeds {what} — citations belong only in 'authorities' "
                      f"(a short case name in italics, *Name*, is fine)")
        plain = check_tokens(r, sw, text, allowed=st.get("kind") == "argument")
        if CLIENT_RE.search(plain):
            r.err(sw, "text says 'client' — write {client}, which prints as a name to fill in")
        if st.get("kind") == "argument" and THE_DEFENDANT_RE.search(plain):
            r.err(sw, "argument sentence says 'the defendant' — write {client} (or a pronoun token); "
                      "'the defendant' is only for rule sentences stating general law")
        if not re.search(r"[.?!][\"'”’]?$", text):
            r.err(sw, "text must end with sentence punctuation (the citation follows it)")
        if text.count("*") % 2:
            r.err(sw, "unbalanced '*' — italics (case names, emphasis) are marked *like this*")
    if kind == "argument":
        if auths:
            r.err(sw, "argument sentences have no authorities — remove them, or drop kind 'argument'")
        return
    if not auths:
        r.warn(sw, "has no authorities, so it never renders (it will show up as a gap in the memo)")
    seen = set()
    for a in auths:
        check_authority(r, sw, a, p_ac, narrowed, courts, counts, nested=False)
        key = (a.get("name"), a.get("court")) if isinstance(a, dict) else None
        if key in seen:
            r.err(f"{sw} authority {a.get('name', '?')!r}", "cited twice in the same sentence")
        seen.add(key)


def check_authority(r, sw, a, p_ac, narrowed, courts, counts, nested):
    if not isinstance(a, dict):
        r.err(sw, "authority must be an object")
        return
    aw = f"{sw} authority {a.get('name', '?')!r}" + (" (in a parenthetical)" if nested else "")
    t = a.get("type")
    if t == "secondary":
        # A treatise or article, only ever inside a parenthetical ("citing 4 LaFave ..."): never
        # cited as authority itself. The name is the whole citation.
        if not nested:
            r.err(aw, "secondary sources can only appear inside a parenthetical — motion authority is binding law")
        check_keys(r, aw, a, {"type", "name"}, ["type", "name"])
        if not a.get("name"):
            r.err(aw, "empty name")
        return
    if t not in AUTHORITY_TYPES:
        r.err(aw, f"invalid type {t!r}")
        return
    base = CASE_KEYS if t == "case" else OTHER_AUTHORITY_KEYS
    check_keys(r, aw, a, base | (set() if nested else OPTIONAL_AUTHORITY_KEYS), sorted(base))
    if not a.get("name"):
        r.err(aw, "empty name")
    court = a.get("court")
    if court not in courts:
        r.err(aw, f"unknown court {court!r}")
    elif p_ac and court not in citable_courts(p_ac, courts):
        scope = "this paragraph" if narrowed else "this issue"
        r.err(aw, f"court {court!r} can never be cited: {scope} only applies in "
                  f"{sorted(p_ac)}, so {court!r} is never a binding court")
    if t == "case":
        counts["cases"] += 1
        if not E.CITATION_RE.match(a.get("citation", "")):
            r.err(aw, f"citation {a.get('citation')!r} must look like "
                      f"'<vol> <reporter> <page> (<court> <year>)'")
        if not isinstance(a.get("pincite", None), str):
            r.err(aw, "pincite must be a string (empty until researched)")
        elif not a["pincite"]:
            counts["missing_pincites"] += 1
    elif a.get("citation", "") != "":
        r.err(aw, f"{t} authorities keep citation empty — the name is the citation")
    if "signal" in a and a["signal"] not in SIGNALS:
        r.err(aw, f"signal {a['signal']!r} isn't one of {sorted(SIGNALS)} (no signal means direct support)")
    if "parenthetical" in a:
        p = a["parenthetical"]
        if check_keys(r, aw + " parenthetical", p, PARENTHETICAL_KEYS, ["text"]):
            if not p["text"]:
                r.err(aw, "empty parenthetical text")
            elif citation_in(p["text"]):
                r.err(aw, f"parenthetical text embeds {citation_in(p['text'])} — put the case in its 'authority'")
            if "authority" in p:
                check_authority(r, aw, p["authority"], p_ac, narrowed, courts, counts, nested=True)


def too_many(r, where, what, qids, questions, refs):
    """True (with a warning) if checking `what` would mean enumerating more than ENUMERATION_LIMIT
    combinations of answers. The check is skipped, so the warning says which one and why."""
    n = space_size(qids, questions, refs)
    if n <= ENUMERATION_LIMIT:
        return False
    r.warn(where, f"too many answer combinations ({n:,}) to check {what} — skipped. "
                  f"Questions involved: {', '.join(sorted(qids))}")
    return True


def check_every_match_has_a_paragraph(r, where, issue, paragraphs, questions, courts):
    """In every forum the issue applies in, every matching set of answers must leave at least one
    paragraph with a cited sentence standing after its 'when' and applicable_courts — otherwise the
    issue matches but produces nothing (argument alone isn't a section), and it isn't a research gap."""
    match = issue["trigger"]["match_condition"]
    whens = [p["when"] for p in paragraphs if "when" in p]
    qids = E.condition_questions(match)
    for w in whens:
        qids |= E.condition_questions(w)
    refs = referenced_options([match] + whens)
    for code in sorted(courts):
        binding = [E.SCOTUS, code]
        if courts[code]["kind"] == "scotus" or not E.applies_in(issue["applicable_courts"], binding):
            continue
        live = [p for p in paragraphs if E.applies_in(E.paragraph_courts(issue, p), binding)
                and E.has_cited(p.get("sentences", []))]
        if any("when" not in p for p in live):
            continue  # a paragraph of law that always prints here: nothing to enumerate
        if too_many(r, where, "that every match leaves a paragraph of law", qids, questions, refs):
            return
        for a in assignments(qids, questions, refs):
            if E.eval_condition(match, a) and not any("when" not in p or E.eval_condition(p["when"], a)
                                                      for p in live):
                r.err(where, f"in {courts[code]['display_name']}, the issue can match with no paragraph of law "
                             f"left after 'when' and applicable_courts, so it would produce nothing — "
                             f"e.g. answers {a}")
                break


def check_reachability(r, where, trig, paragraphs, questions):
    match = trig["match_condition"]
    mq = E.condition_questions(match)

    def explore(extra_cond, what):
        """Every relevant combination of answers for match_condition plus one other condition,
        or None (with a warning) if there are too many to check."""
        qids = mq | (E.condition_questions(extra_cond) if extra_cond else set())
        refs = referenced_options([match] + ([extra_cond] if extra_cond else []))
        if too_many(r, where, what, qids, questions, refs):
            return None
        return assignments(qids, questions, refs)

    space = explore(None, "whether match_condition can ever be true")
    if space is None:
        return
    if not any(E.eval_condition(match, a) for a in space):
        r.err(where, "match_condition can never be true for any combination of answers")
        return

    for i, rc in enumerate(trig.get("review_conditions", [])):
        space = explore(rc["when"], f"review note {rc['flag']!r}")
        if space is not None and not any(E.eval_condition(match, a) and E.eval_condition(rc["when"], a) for a in space):
            r.err(f"{where} review_conditions[{i}] ({rc['flag']})",
                  "can never fire on an included issue — its 'when' contradicts match_condition")

    for i, ex in enumerate(trig.get("excluded_explanations", [])):
        space = explore(ex["when"], f"near-miss explanation {ex['flag']!r}")
        if space is not None and not any((not E.eval_condition(match, a)) and E.near_miss_fires(match, ex["when"], a)
                                         for a in space):
            r.err(f"{where} excluded_explanations[{i}] ({ex['flag']})",
                  "can never fire — whenever its 'when' is true, either the issue is included or its "
                  "encounter event didn't happen (near misses show only when the event did)")

    for p in paragraphs:
        if "when" not in p:
            continue
        combos = explore(p["when"], f"paragraph {p['id']!r}")
        if combos is None:
            continue
        fires = redundant = False
        redundant = True
        for a in combos:
            if E.eval_condition(match, a):
                w = E.eval_condition(p["when"], a)
                fires |= w
                redundant &= w
        if not fires:
            r.err(f"{where} paragraph {p['id']}", "'when' can never be true on an included issue, "
                                                  "so this paragraph never renders")
        elif redundant:
            r.warn(f"{where} paragraph {p['id']}", "'when' is true whenever the issue matches — it can be removed")

    # Uncertain answers ("not sure", "unknown", "unclear") must never silently decide an issue:
    # if one can exclude it, an excluded_explanation must say so; if one can include it, a review
    # note must say so. On a multi_select, the uncertain answer is that option checked alone.
    excluded = trig.get("excluded_explanations", [])
    reviews = trig.get("review_conditions", [])
    note_qids = set()
    for n in excluded + reviews:
        note_qids |= E.condition_questions(n["when"])
    refs = referenced_options([match] + [n["when"] for n in excluded + reviews])
    for qid in sorted(mq):
        q = questions[qid]
        if q["type"] not in ("multiple_choice", "multi_select"):
            continue
        multi = q["type"] == "multi_select"
        for uid in [o["id"] for o in q["options"] if o["id"] in UNCERTAIN_OPTION_IDS]:
            others = (mq | note_qids) - {qid}
            if too_many(r, where, f"what answering {qid} = {uid!r} does", others, questions, refs):
                continue
            uncertain = [uid] if multi else uid
            # On a checklist, leaving it blank ("none of these") is an alternative too.
            alternatives = [[o["id"]] if multi else o["id"] for o in q["options"] if o["id"] != uid]
            if multi:
                alternatives.append([])
            answer = f"{qid} = {uid!r}" + (" (checked alone)" if multi else "")
            excl_reported = incl_reported = False
            for a in assignments(others, questions, refs):
                a = {**a, qid: uncertain}
                matched = E.eval_condition(match, a)
                decides = any(E.eval_condition(match, {**a, qid: alt}) != matched for alt in alternatives)
                if not decides:
                    continue
                if not matched and not excl_reported and not any(E.near_miss_fires(match, e["when"], a)
                                                                 for e in excluded):
                    r.err(where, f"answering {answer} silently excludes this issue (a different "
                                 f"answer would have included it, and no excluded_explanation fires). "
                                 f"Include it with a review note (the default), or add an excluded_explanation.")
                    excl_reported = True
                if matched and not incl_reported and not any(E.eval_condition(n["when"], a) for n in reviews):
                    r.err(where, f"answering {answer} can include this issue with no review note firing, so "
                                 f"the attorney isn't told the section rests on an uncertain answer. Add a "
                                 f"review_conditions note for it.")
                    incl_reported = True
                if excl_reported and incl_reported:
                    break


# --------------------------------------------------------------------------- example sessions

def check_sessions(r, root, config, questions):
    for path in sorted(glob.glob(os.path.join(root, "examples", "sessions", "*.json"))):
        where = os.path.relpath(path, root)
        try:
            s = E.load_json(path)
        except Exception as e:  # noqa: BLE001
            r.err(where, f"cannot load: {e}")
            continue
        if not check_keys(r, where, s, {"answers"}, ["answers"]):
            continue
        if E.FILING_COURT not in s["answers"]:
            r.err(where, f"no answer for {E.FILING_COURT}")
        for qid, ans in s.get("answers", {}).items():
            q = questions.get(qid)
            if q is None:
                r.err(where, f"answer for unknown question {qid!r}")
                continue
            if q["type"] == "short_text":
                ok = isinstance(ans, str)
            elif q["type"] == "multi_select":
                ids = {o["id"] for o in q["options"]}
                ok = isinstance(ans, list) and all(x in ids for x in ans)
            else:
                ok = ans in (set(domain(q)) - {UNANSWERED})
            if not ok:
                r.err(where, f"invalid answer for {qid}: {ans!r}")


# --------------------------------------------------------------------------- main

def validate(root, only=None):
    """Validate the repo. only: a set of issue ids to check instead of every issue (for tests).
    Config, questions, and example sessions are always checked; the checks that need every issue
    (unused questions and event groups, duplicate headings across files) run only on a full check."""
    r = Report()
    config = check_config(r, root)
    if config is None:
        return r
    questions = check_questions(r, root)
    check_filing_court(r, questions, config)
    check_encounter_events(r, questions)
    check_client_pronouns(r, questions)
    check_event_groups(r, questions, config)
    groups_used = set()
    used = set()
    headings = {}
    for path in E.content_files(root, "issues"):
        if only is not None and os.path.splitext(os.path.basename(path))[0] not in only:
            continue
        where = os.path.relpath(path, root)
        try:
            issue = E.load_json(path)
        except Exception as e:  # noqa: BLE001
            r.err(where, f"cannot load: {e}")
            continue
        if issue.get("id") != os.path.splitext(os.path.basename(path))[0]:
            r.err(where, f"id {issue.get('id')!r} doesn't match the file name")
        issue, g_used, g_unknown = E.expand_issue(issue, config["event_groups"])
        groups_used |= g_used
        for name in sorted(g_unknown):
            r.err(where, f"unknown event_group {name!r} (groups are defined in config event_groups)")
        check_issue(r, where, issue, config, questions, used)
        h = issue.get("motion_heading")
        if h:
            if h in headings:
                r.warn(where, f"same motion_heading as {headings[h]}")
            headings[h] = where
    if only is not None:
        check_sessions(r, root, config, questions)
        return r
    for name in sorted(set(config["event_groups"]) - groups_used):
        r.warn("content/config.json event_groups", f"group {name!r} isn't used by any issue")
    for qid, q in sorted(questions.items()):
        if qid not in used and qid not in (E.FILING_COURT, E.CLIENT_PRONOUNS):
            if q["type"] == "short_text":
                r.warn(f"question {qid}", "short_text answer is collected but nothing uses it yet")
            else:
                r.warn(f"question {qid}", "not referenced by any issue")
    check_sessions(r, root, config, questions)
    return r


def main(argv):
    strict = "--strict" in argv
    args = [a for a in argv if not a.startswith("--")]
    root = args[0] if args else os.getcwd()
    r = validate(root)
    if r.errors:
        print(f"ERRORS ({len(r.errors)}):")
        for e in r.errors:
            print(f"  {e}")
    if r.warnings:
        print(f"WARNINGS ({len(r.warnings)}):")
        for w in r.warnings:
            print(f"  {w}")
    if not r.errors and not r.warnings:
        print("All checks passed.")
    elif not r.errors:
        print("No errors.")
    return 1 if r.errors or (strict and r.warnings) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

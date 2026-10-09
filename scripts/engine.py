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
ENCOUNTER_EVENTS = "q_encounter_events"  # what happened in the encounter; every issue requires one of these

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
    groups = config.get("event_groups", {})
    issues = [expand_issue(load_json(path), groups)[0] for path in content_files(root, "issues")]
    return config, questions, ordered_issues(config, issues)


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

    paragraphs is the ordered list of paragraphs that render, each as { id, sentences }, and each
    sentence as { id, text, kind, authorities } with authorities filtered to courts and in
    citation order (SCOTUS, circuit, state). A paragraph renders when its 'when' is absent or true
    and it applies in this forum. Inside it, a cited sentence with no authority for these courts
    is dropped and reported as a gap; an argument sentence always renders. A paragraph made only
    of argument (e.g. an application paragraph) renders as is, but one whose cited sentences were
    all dropped doesn't, since its argument would rest on nothing. Whether citations go inline or
    in footnotes is up to the renderer.
    """
    paragraphs, gaps = [], []
    for para in issue["law_paragraphs"]:
        if "when" in para and not eval_condition(para["when"], answers):
            continue
        if not applies_in(paragraph_courts(issue, para), courts):
            continue  # not the law in this forum, so not a gap either
        sentences = []
        for st in para["sentences"]:
            kind = st.get("kind", "rule")
            auths = [a for a in st["authorities"] if a["court"] in courts]
            auths.sort(key=lambda a: court_rank(config, a["court"]))  # stable within a court
            if kind != "argument" and not auths:
                gaps.append(st["text"])
                continue
            sentences.append({"id": st["id"], "text": st["text"], "kind": kind, "authorities": auths})
        had_cited = any(st.get("kind", "rule") != "argument" for st in para["sentences"])
        if sentences and (not had_cited or has_cited(sentences)):
            paragraphs.append({"id": para["id"], "sentences": sentences})
    return paragraphs, gaps


def has_cited(sentences):
    return any(st.get("kind", "rule") != "argument" for st in sentences)


# --------------------------------------------------------------------------- session evaluation

def evaluate_session(config, issues, session):
    """Evaluate every issue for one case. Returns a structured result for rendering."""
    answers = session.get("answers", {})
    courts = binding_courts(answers)
    specific = courts[1]
    result = {"courts": courts, "included": [], "no_paragraph": [], "near_misses": []}

    for issue in issues:
        if not applies_in(issue["applicable_courts"], courts):
            continue
        trig = issue["trigger"]
        if eval_condition(trig["match_condition"], answers):
            paragraphs, gaps = law_paragraphs(issue, answers, courts, config)
            cited_courts = {a["court"] for p in paragraphs for st in p["sentences"] for a in st["authorities"]}
            entry = {
                "issue": issue,
                "paragraphs": paragraphs,
                "review_notes": [rc["display_note"] for rc in trig.get("review_conditions", [])
                                 if eval_condition(rc["when"], answers)],
                "gaps": gaps,
                "unreviewed": issue["status"] != "reviewed",
                "missing_specific_court": (SCOTUS in issue["applicable_courts"]
                                           and specific not in cited_courts),
            }
            # Argument with no law in front of it isn't a section.
            cited = any(has_cited(p["sentences"]) for p in paragraphs)
            (result["included"] if cited else result["no_paragraph"]).append(entry)
        else:
            for ex in trig.get("excluded_explanations", []):
                if eval_condition(ex["when"], answers):
                    result["near_misses"].append({"issue": issue, "note": ex["display_note"]})
    return result

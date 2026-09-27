"""Shared logic for the suppression motion generator.

Used by validate.py (to check content) and render.py (to produce the motion and
memo), so both agree on exactly what a condition means and how text renders.
Standard library only.
"""
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
    issues = [load_json(path) for path in content_files(root, "issues")]
    return config, questions, ordered_issues(config, issues)


def ordered_issues(config, issues):
    """Order issues by phase (when in the encounter the violation happened), then by id."""
    phase_rank = {p: i for i, p in enumerate(config["phase_order"])}
    return sorted(issues, key=lambda i: (phase_rank.get(i.get("phase"), len(phase_rank)), i.get("id", "")))


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
    """Whether an issue or rule statement is the law in a case bound by courts.

    ['scotus'] applies everywhere, since SCOTUS is always a binding court.
    """
    return bool(set(applicable_courts) & set(courts))


def statement_courts(issue, st):
    """A rule statement's applicable_courts, defaulting to its issue's."""
    return st.get("applicable_courts", issue["applicable_courts"])


def court_rank(config, code):
    return KIND_RANK[config["courts"][code]["kind"]]


def citation_parts(a):
    """Split an authority into what a renderer needs, leaving the markup to the renderer.

    Returns { name, italic, rest }: a case is its italicized name, then ', ' and rest (the
    citation, with any pincite inserted before the parenthetical); anything else is its name alone.
    """
    if a["type"] != "case":
        return {"name": a["name"], "italic": False, "rest": ""}
    cite = a["citation"]
    if a.get("pincite"):
        m = CITATION_RE.match(cite)
        cite = f"{m['base']}, {a['pincite']} {m['paren']}"
    return {"name": a["name"], "italic": True, "rest": cite}


def law_paragraph(issue, answers, courts, config):
    """Return (statements, gap_statement_texts) for one issue.

    statements is the ordered list of rule statements that survive, each as
    { id, text, authorities } with authorities filtered to courts and in citation order
    (SCOTUS, circuit, state). Whether citations go inline or in footnotes is up to the renderer.
    """
    statements, gaps = [], []
    for st in issue["law_paragraph"]["rule_statements"]:
        if "when" in st and not eval_condition(st["when"], answers):
            continue
        if not applies_in(statement_courts(issue, st), courts):
            continue  # not the law in this forum, so not a gap either
        auths = [a for a in st["authorities"] if a["court"] in courts]
        auths.sort(key=lambda a: court_rank(config, a["court"]))  # stable within a court
        if not auths:
            gaps.append(st["text"])
            continue
        statements.append({"id": st["id"], "text": st["text"], "authorities": auths})
    return statements, gaps


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
            statements, gaps = law_paragraph(issue, answers, courts, config)
            cited_courts = {a["court"] for st in statements for a in st["authorities"]}
            entry = {
                "issue": issue,
                "statements": statements,
                "review_notes": [rc["display_note"] for rc in trig.get("review_conditions", [])
                                 if eval_condition(rc["when"], answers)],
                "gaps": gaps,
                "unreviewed": issue["status"] != "reviewed",
                "missing_specific_court": (SCOTUS in issue["applicable_courts"]
                                           and specific not in cited_courts),
            }
            (result["included"] if statements else result["no_paragraph"]).append(entry)
        else:
            for ex in trig.get("excluded_explanations", []):
                if eval_condition(ex["when"], answers):
                    result["near_misses"].append({"issue": issue, "note": ex["display_note"]})
    return result

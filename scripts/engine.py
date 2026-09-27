"""Shared logic for the suppression motion generator.

Used by validate.py (to check content) and render.py (to produce the motion and
memo), so both agree on exactly what a condition means and how text renders.
Standard library only.
"""
import json
import os
import re

SCALAR_OPS = {"equals", "not_equals", "in", "not_in"}
ARRAY_OPS = {"includes", "not_includes", "not_empty", "empty"}
VALUELESS_OPS = {"not_empty", "empty"}
LIST_VALUE_OPS = {"in", "not_in"}

KIND_RANK = {"scotus": 0, "circuit": 1, "state": 2}

# '<volume> <reporter> <first page> (<court> <year>)'
CITATION_RE = re.compile(r"^(?P<base>\d+ .+? \d+) (?P<paren>\([^()]*\d{4}\))$")


# --------------------------------------------------------------------------- loading

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_repo(root):
    """Load manifest, question bank (id -> question), and issues in output order."""
    manifest = load_json(os.path.join(root, "content", "manifest.json"))
    questions = {}
    for rel in manifest["question_bank_topics"]:
        for q in load_json(os.path.join(root, rel)):
            questions[q["id"]] = q
    issues = [load_json(os.path.join(root, e["file"])) for e in manifest["issues"]]
    return manifest, questions, ordered_issues(manifest, issues)


def ordered_issues(manifest, issues):
    cat_rank = {c: i for i, c in enumerate(manifest["category_order"])}
    indexed = list(enumerate(issues))
    indexed.sort(key=lambda p: (cat_rank.get(p[1].get("category"), len(cat_rank)), p[0]))
    return [issue for _, issue in indexed]


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

def desired_courts(session):
    if session["forum"] == "state_court":
        return ["SCOTUS", session["state"]]
    return ["SCOTUS", session["federal_circuit"]]


def court_rank(manifest, code):
    return KIND_RANK[manifest["courts"][code]["kind"]]


def format_authority(a, italic=True):
    if a["type"] == "case":
        name = f"*{a['name']}*" if italic else a["name"]
        cite = a["citation"]
        if a.get("pincite"):
            m = CITATION_RE.match(cite)
            cite = f"{m['base']}, {a['pincite']} {m['paren']}"
        return f"{name}, {cite}"
    return a["name"]


def render_law_paragraph(issue, answers, courts, manifest):
    """Return (paragraph_text, authorities_used, gap_statement_texts)."""
    parts, used, gaps = [], [], []
    for st in issue["law_paragraph"]["rule_statements"]:
        if "when" in st and not eval_condition(st["when"], answers):
            continue
        auths = [a for a in st["authorities"] if a["court"] in courts]
        auths.sort(key=lambda a: court_rank(manifest, a["court"]))  # stable within a court
        if not auths:
            gaps.append(st["text"])
            continue
        parts.append(st["text"] + " " + "; ".join(format_authority(a) for a in auths) + ".")
        used.extend(auths)
    return " ".join(parts), used, gaps


# --------------------------------------------------------------------------- session evaluation

def evaluate_session(manifest, issues, session):
    """Evaluate every issue for one case. Returns a structured result for rendering."""
    courts = desired_courts(session)
    answers = session.get("answers", {})
    specific = courts[1]
    result = {"courts": courts, "included": [], "no_paragraph": [], "near_misses": []}

    for issue in issues:
        if not set(issue["applicable_courts"]) & set(courts):
            continue
        trig = issue["trigger"]
        if eval_condition(trig["match_condition"], answers):
            text, used, gaps = render_law_paragraph(issue, answers, courts, manifest)
            entry = {
                "issue": issue,
                "paragraph": text,
                "review_notes": [rc["display_note"] for rc in trig.get("review_conditions", [])
                                 if eval_condition(rc["when"], answers)],
                "gaps": gaps,
                "unreviewed": issue["status"] != "reviewed",
                "missing_specific_court": ("SCOTUS" in issue["applicable_courts"]
                                           and specific not in {a["court"] for a in used}),
            }
            (result["included"] if text else result["no_paragraph"]).append(entry)
        else:
            for ex in trig.get("excluded_explanations", []):
                if eval_condition(ex["when"], answers):
                    result["near_misses"].append({"issue": issue, "note": ex["display_note"]})
    return result

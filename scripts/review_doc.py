#!/usr/bin/env python3
"""Write a readable review document of every issue and every question.

Usage (from the repo root):
    python3 scripts/review_doc.py [--out review/content-review.md]

For legal review. It's read-only: edits go in the JSON files, and each item says which file
and which id to edit. Regenerate after editing. Conditions are spelled out in plain English
using the questions' prompts and option labels, so they can be checked without reading JSON.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E  # noqa: E402
import render as R  # noqa: E402


def load_raw(root):
    """Config, questions (id -> question, with its file), and issues as written (event and option groups unexpanded)."""
    config = E.load_json(os.path.join(root, "content", "config.json"))
    questions, files = {}, []
    for path in E.content_files(root, "questions"):
        rel = os.path.relpath(path, root)
        qs = E.load_json(path)
        files.append((rel, [q["id"] for q in qs]))
        for q in qs:
            questions[q["id"]] = {**q, "_file": rel}
    questions[E.ENCOUNTER_EVENTS] = {**E.events_question(config, questions), "_file": "(derived: config.encounter)"}
    issues = {}
    for path in E.content_files(root, "issues"):
        issue = E.load_json(path)
        issues[issue["id"]] = {**issue, "_file": os.path.relpath(path, root)}
    return config, questions, files, issues


# --------------------------------------------------------------------------- conditions in English

def label(q, oid):
    for o in q.get("options", []):
        if o["id"] == oid:
            return f"“{o['label']}”"
    return f"“{oid}”"


def leaf_text(c, questions, config):
    if set(c) == {"event_group"}:
        name = c["event_group"]
        members = config.get("event_groups", {}).get(name, [])
        q = questions.get(E.ENCOUNTER_EVENTS, {})
        return f"any `{name}` event is checked ({'; '.join(label(q, m) for m in members)})"
    if "option_group" in c:
        name = c["option_group"]
        g = config.get("option_groups", {}).get(name, {"question": "", "options": []})
        q = questions.get(g["question"], {"prompt": g["question"]})
        members = [m for m in g["options"] if m not in c.get("except", [])]
        which = "any" if c.get("op") == "includes_any" else "none"
        but = f", other than {' or '.join(label(q, m) for m in c['except'])}" if c.get("except") else ""
        return (f"*{q['prompt']}* → {which} of `{name}`{but} checked "
                f"({'; '.join(label(q, m) for m in members)})")
    q = questions.get(c["question"], {"prompt": c["question"]})
    op, v = c["op"], c.get("value")
    prompt = f"*{q['prompt']}*"
    if op == "equals":
        return f"{prompt} → {label(q, v) if q.get('options') else '“' + str(v) + '”'}"
    if op == "not_equals":
        return f"{prompt} → anything but {label(q, v) if q.get('options') else '“' + str(v) + '”'}"
    if op == "in":
        return f"{prompt} → {' or '.join(label(q, x) for x in v)}"
    if op == "not_in":
        return f"{prompt} → anything but {' or '.join(label(q, x) for x in v)}"
    if op == "includes":
        return f"{prompt} → {label(q, v)} checked"
    if op == "not_includes":
        return f"{prompt} → {label(q, v)} not checked"
    if op == "not_empty":
        return f"{prompt} → anything checked"
    if op == "empty":
        return f"{prompt} → nothing checked"
    return f"{prompt} {op} {v}"


def condition_lines(c, questions, config, depth=0):
    """Nested bullet lines. 'all' reads as ALL of, 'any' as ANY of."""
    pad = "  " * depth
    if "all" in c or "any" in c:
        kind = "all" if "all" in c else "any"
        kids = c[kind]
        if len(kids) == 1:
            return condition_lines(kids[0], questions, config, depth)
        out = [f"{pad}- {'ALL' if kind == 'all' else 'ANY'} of:"]
        for k in kids:
            out += condition_lines(k, questions, config, depth + 1)
        return out
    return [f"{pad}- {leaf_text(c, questions, config)}"]


def when_inline(c, questions, config):
    lines = condition_lines(c, questions, config)
    if len(lines) == 1:
        return lines[0][2:]
    return "\n" + "\n".join("  " + x for x in lines)


# --------------------------------------------------------------------------- document

def issue_section(n, issue, phase, config, questions):
    courts = config["courts"]
    ac = ", ".join(courts[c]["display_name"] for c in issue["applicable_courts"])
    trig = issue["trigger"]
    out = [f"## {n}. {issue['label']}", "",
           f"`{issue['_file']}` · phase: {phase} · applies in: {ac} · status: **{issue['status']}**", "",
           f"**Motion heading:** {issue['motion_heading']}", "",
           "### Included when", ""]
    out += condition_lines(trig["match_condition"], questions, config) + [""]

    out += ["### Motion text (paragraphs, in order)", ""]
    for para in issue["law_paragraphs"]:
        out.append(f"- **Paragraph `{para['id']}`**")
        if "applicable_courts" in para:
            out.append(f"  - *Only in:* {', '.join(courts[c]['display_name'] for c in para['applicable_courts'])}")
        if "when" in para:
            out.append(f"  - *Only when:* {when_inline(para['when'], questions, config)}")
        if "fill_in" in para:
            out.append(f"  - *Fill-in for the attorney:* {para['fill_in']}")
            continue
        for st in para["sentences"]:
            out.append(f"  - `{st['id']}`: {st['text']}")
            if st.get("kind") == "argument":
                out.append("    - *Argument — no citation needed*")
                continue
            cites = "; ".join(cite_text(a, courts) for a in st["authorities"])
            out.append(f"    - *Cites:* {cites}" if cites else "    - *Cites:* **none — shows as a gap in the memo**")
    if not any("fill_in" in p for p in issue["law_paragraphs"]):
        out.append(f"- *No fill-in of its own: the section ends with “[Fill in: {E.GENERIC_FILL_IN}]”*")
    out.append("")

    for kind, title in (("review_conditions", "Memo: review notes (when included)"),
                        ("excluded_explanations", "Memo: near-miss explanations (when not included)")):
        notes = trig.get(kind, [])
        if notes:
            out += [f"### {title}", ""]
            for note in notes:
                out.append(f"- `{note['flag']}` — *when:* {when_inline(note['when'], questions, config)}")
                out.append(f"  - {note['display_note']}")
            out.append("")

    if issue.get("practice_notes"):
        out += ["### Memo: practice notes", ""] + [f"- {p}" for p in issue["practice_notes"]] + [""]
    if issue.get("_author_notes"):
        out += ["### Author notes (never rendered)", ""] + [f"- {p}" for p in issue["_author_notes"]] + [""]
    return out


def cite_text(a, courts):
    """One authority as the motion cites it in full, plus its court when that isn't the Supreme Court."""
    signal = f"*{a['signal']}* " if a.get("signal") else ""
    where = f" [{courts[a['court']]['display_name']}]" if a["court"] != E.SCOTUS else ""
    return signal + R.authority(a) + where


def option_uses(cond, out):
    """Collect (question, option) pairs a condition mentions."""
    if "all" in cond or "any" in cond:
        for k in cond.get("all", []) + cond.get("any", []):
            option_uses(k, out)
        return
    v = cond.get("value")
    for x in (v if isinstance(v, list) else [] if v is None else [v]):
        out.add((cond["question"], x))


def question_section(rel, qids, questions, used_by, used_options):
    out = [f"### `{rel}`", ""]
    for qid in qids:
        q = questions[qid]
        out.append(f"- **`{qid}`** ({q['type'].replace('_', ' ')}): {q['prompt']}")
        engine_read = qid in (E.FILING_COURT, E.CLIENT_PRONOUNS)
        for o in q.get("options", []):
            unused = "" if engine_read or (qid, o["id"]) in used_options else " *(no issue uses this option)*"
            out.append(f"  - `{o['id']}`: {o['label']}{unused}")
        users = sorted(used_by.get(qid, []))
        for note in q.get("_author_notes", []):
            out.append(f"  - *Author note (never rendered):* {note}")
        if qid == E.FILING_COURT:
            out.append("  - *Used by:* the engine (sets which courts' authority is cited)")
        elif qid == E.CLIENT_PRONOUNS:
            out.append("  - *Used by:* the engine (sets how pronoun tokens print in the motion)")
        else:
            out.append(f"  - *Used by:* {', '.join(users) if users else '**no issue**'}")
    return out + [""]


def build(root):
    config, questions, files, issues = load_raw(root)
    groups = config.get("event_groups", {})
    order = E.motion_order(config)
    phase_of = {iid: ph for ph, ids in config["motion_order"].items() for iid in ids}

    used_by, used_options = {}, set()
    for iid, issue in issues.items():
        expanded = E.expand_issue(issue, config)[0]
        trig = expanded["trigger"]
        conds = ([trig["match_condition"]] + [n["when"] for n in trig.get("review_conditions", [])]
                 + [n["when"] for n in trig.get("excluded_explanations", [])]
                 + [p["when"] for p in expanded["law_paragraphs"] if "when" in p])
        for c in conds:
            option_uses(c, used_options)
            for qid in E.condition_questions(c):
                used_by.setdefault(qid, set()).add(iid)

    out = ["# Content review", "",
           "Generated by `scripts/review_doc.py` — don't edit this file. Make changes in the JSON file "
           "named under each item (search for the id), then regenerate.", "",
           f"{len(order)} issues, in motion order, then every question.", "",
           "## Contents", ""]
    for n, iid in enumerate(order, 1):
        out.append(f"{n}. [{issues[iid]['label']}](#{n}-{anchor(issues[iid]['label'])}) — {phase_of[iid]}")
    out += ["", "[Questions](#questions)", "", "---", ""]

    for n, iid in enumerate(order, 1):
        out += issue_section(n, issues[iid], phase_of[iid], config, questions) + ["---", ""]

    out += ["# Questions", "", "Grouped by file, in file order. *Used by* lists every issue whose conditions "
            "mention the question. Options no condition mentions are marked; on a checklist they can still "
            "matter for “anything checked” / “nothing checked.”", ""]
    q = questions.get(E.ENCOUNTER_EVENTS)
    if q:
        out += [f"**`{E.ENCOUNTER_EVENTS}`** is derived from the opening questions (`content/config.json` "
                f"encounter), not asked directly. Its events:", ""]
        out += [f"- `{o['id']}`: {o['label']}" for o in q["options"]] + [""]
    if groups and q:
        out += ["**Event groups** (`content/config.json`):", ""]
        for name, members in groups.items():
            out.append(f"- `{name}`: {'; '.join(label(q, m) for m in members)}")
        out.append("")
    if config.get("option_groups"):
        out += ["**Option groups** (`content/config.json`):", ""]
        for name, g in config["option_groups"].items():
            gq = questions.get(g["question"], {})
            out.append(f"- `{name}` (`{g['question']}`): {'; '.join(label(gq, m) for m in g['options'])}")
        out.append("")
    for rel, qids in files:
        out += question_section(rel, qids, questions, used_by, used_options)
    return "\n".join(out)


def anchor(text):
    """GitHub-style heading anchor."""
    keep = [ch.lower() if ch.isalnum() or ch in "-_" else "-" if ch == " " else "" for ch in text]
    return "".join(ch for ch in keep if ch)


def main(argv):
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join("review", "content-review.md")
    text = build(os.getcwd())
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

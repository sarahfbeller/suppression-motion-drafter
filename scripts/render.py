#!/usr/bin/env python3
"""Render the two deliverables for one case: the motion and the attorney memo.

Usage (from the repo root):
    python3 scripts/render.py examples/sessions/state-dui.json [--out examples/output]

Writes <session-name>.motion.md and <session-name>.memo.md. This is a reference
implementation of the rendering rules in docs/SCHEMA.md, not the final app.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E  # noqa: E402


def roman(n):
    vals = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for v, s in vals:
        while n >= v:
            out, n = out + s, n - v
    return out


def render_motion(result):
    if not result["included"]:
        return "No suppression issues were identified for these facts. See the attorney memo.\n"
    lines = ["## ARGUMENT", ""]
    for i, entry in enumerate(result["included"], 1):
        lines += [f"### {roman(i)}. {entry['issue']['motion_heading']}", "", entry["paragraph"], ""]
    return "\n".join(lines)


def render_memo(result, config):
    courts = config["courts"]
    specific = result["courts"][1]
    forum = "State court" if courts[specific]["kind"] == "state" else "Federal court"
    specific_name = courts[specific]["display_name"]
    cited = " and ".join(courts[c]["display_name"] for c in result["courts"])

    lines = ["# Attorney memo: suppression issues", "",
             "*For the attorney only. Do not file.*", "",
             f"**Forum:** {forum} ({specific_name}). **Authority cited:** {cited}.", ""]

    lines += ["## Issues included in the motion", ""]
    if not result["included"] and not result["no_paragraph"]:
        lines += ["No issues matched the answers given.", ""]
    for i, e in enumerate(result["included"], 1):
        issue = e["issue"]
        lines += [f"### {roman(i)}. {issue['label']}", ""]
        flags = []
        if e["unreviewed"]:
            flags.append("This section's legal content has not yet been reviewed by an attorney. "
                         "Check every proposition and citation before filing.")
        if e["missing_specific_court"]:
            flags.append(f"This section cites only U.S. Supreme Court authority; no {specific_name} "
                         f"authority is cited. Consider adding a {specific_name} case if one exists.")
        for g in e["gaps"]:
            flags.append(f"A proposition relevant to these facts was left out of the motion because no "
                         f"authority for this forum is available yet: \"{g}\"")
        flags += e["review_notes"]
        if flags:
            lines += ["**Check before filing:**", ""] + [f"- {f}" for f in flags] + [""]
        if issue.get("practice_notes"):
            lines += ["**Practice notes:**", ""] + [f"- {n}" for n in issue["practice_notes"]] + [""]

    for e in result["no_paragraph"]:
        lines += [f"### {e['issue']['label']} (not in motion)", ""]
        if e["gaps"]:
            lines += ["The facts match this issue, but no rule statement has authority available for this "
                      "forum, so no paragraph could be generated. Research needed before this can be argued.", ""]
        else:
            lines += ["The facts match this issue, but none of its rule statements apply to these facts, so "
                      "no paragraph could be generated. This is a problem with the issue's content, not "
                      "missing research — tell the maintainer.", ""]

    if result["near_misses"]:
        lines += ["## Issues considered but not included", ""]
        for nm in result["near_misses"]:
            lines += [f"### {nm['issue']['label']}", "", nm["note"], ""]

    return "\n".join(lines)


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    out_dir = argv[argv.index("--out") + 1] if "--out" in argv else "examples/output"
    if "--out" in argv:
        args.remove(out_dir)
    if not args:
        print(__doc__)
        return 2
    root = os.getcwd()
    config, _questions, issues = E.load_repo(root)
    os.makedirs(out_dir, exist_ok=True)
    for session_path in args:
        session = E.load_json(session_path)
        result = E.evaluate_session(config, issues, session)
        name = os.path.splitext(os.path.basename(session_path))[0]
        for suffix, text in (("motion", render_motion(result)),
                             ("memo", render_memo(result, config))):
            path = os.path.join(out_dir, f"{name}.{suffix}.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

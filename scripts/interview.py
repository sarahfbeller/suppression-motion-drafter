#!/usr/bin/env python3
"""Walk through the interview in the terminal, then print the motion and memo.

Usage (from the repo root):
    python3 scripts/interview.py [--resume session.json] [--save session.json]

Each question is asked only if its answer can still change the output (see next_question in
engine.py). Answer by number; for a checklist, give numbers separated by commas, or press Enter
for none. Every question needs an answer.
--resume starts from a saved session's answers; --save writes the session when you finish.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E  # noqa: E402
import render as R  # noqa: E402


def options_of(q):
    if q["type"] == "yes_no":
        return [("yes", "Yes"), ("no", "No")]
    return [(o["id"], o["label"]) for o in q.get("options", [])]


def ask(q, read=input, write=print):
    """Ask one question until the reply is valid. Returns the answer."""
    opts = options_of(q)
    multi = q["type"] == "multi_select"
    write("")
    write(q["prompt"])
    for n, (_, label) in enumerate(opts, 1):
        write(f"  {n}. {label}")
    hint = "numbers separated by commas, or Enter for none" if multi else "a number"
    while True:
        reply = read(f"[{hint}] > ").strip()
        if q["type"] == "short_text":
            return reply
        if multi and reply == "":
            return []
        try:
            picks = [int(x) for x in reply.split(",")] if multi else [int(reply)]
        except ValueError:
            write("Please answer with the number(s) shown.")
            continue
        if not picks or any(p < 1 or p > len(opts) for p in picks) or (not multi and len(picks) != 1):
            write("Please answer with the number(s) shown.")
            continue
        ids = [opts[p - 1][0] for p in picks]
        return [i for i, _ in opts if i in ids] if multi else ids[0]


def run(root, answers, read=input, write=print):
    """Ask questions until the interview is done. Returns the answers."""
    config, questions, issues = E.load_repo(root)
    while (qid := E.next_question(issues, answers)) is not None:  # answers is filled in place
        answers[qid] = ask(questions[qid], read, write)
    return answers


def main(argv):
    root = os.getcwd()
    answers = {}
    if "--resume" in argv:
        answers = E.load_json(argv[argv.index("--resume") + 1]).get("answers", {})
    try:
        answers = run(root, answers)
    except (EOFError, KeyboardInterrupt):
        print("\nInterview stopped before it finished; the output below uses the answers so far.")
        if E.FILING_COURT not in answers:
            print("No filing court yet, so there's nothing to render.")
            return 1
    config, _questions, issues = E.load_repo(root)
    result = E.evaluate_session(config, issues, {"answers": answers})
    motion = R.render_motion(result)
    print("\n" + "=" * 70 + "\nMOTION\n" + "=" * 70 + "\n")
    print(motion)
    print("\n" + "=" * 70 + "\nMEMO\n" + "=" * 70 + "\n")
    print(R.render_memo(result, config, motion))
    if "--save" in argv:
        path = argv[argv.index("--save") + 1]
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"answers": answers}, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"saved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

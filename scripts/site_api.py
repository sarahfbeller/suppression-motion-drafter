"""What the website calls, through Pyodide, to run the interview and produce the documents.

The page keeps every answer the attorney has given, including ones left over after changing an earlier
answer; everything here replays the interview from those answers (engine.interview_path), so only the
answers on the current path count. Arguments and results are JSON strings, except documents(), which
returns the two Word files as bytes.
"""
import json

import engine as E
import render as R

OPENING_NAME = "Getting started"

_repo = None


def load(root):
    """Load the content once, from root (the website writes the repo files there)."""
    global _repo
    _repo = E.load_repo(root)


def questions():
    """Every askable question, by id, as the page renders it."""
    _config, qs, _issues = _repo
    return json.dumps({qid: q for qid, q in qs.items() if qid != E.ENCOUNTER_EVENTS})


def state(answers_json):
    """Where the interview stands:
    - path: the questions asked so far, in order, each {id, phase};
    - pending: the next question to ask {id, phase}, or null when the interview is done;
    - steps: the phases to show in the step list, in order, each {phase, name}: the opening, every
      phase asked so far, and every phase that could still ask a question."""
    config, _qs, issues = _repo
    path, (qid, phase), asked = E.interview_path(config, issues, json.loads(answers_json))
    shown = {p for _, p in path} | {phase} | set(E.possible_phases(config, issues, asked))
    steps = [{"phase": E.OPENING, "name": OPENING_NAME}]
    steps += [{"phase": p, "name": config["phase_names"][p]} for p in config["motion_order"] if p in shown]
    return json.dumps({
        "path": [{"id": q, "phase": p} for q, p in path],
        "pending": {"id": qid, "phase": phase} if qid else None,
        "steps": steps,
    })


def evaluate(answers_json):
    """The engine's result for the answers on the current path."""
    config, _qs, issues = _repo
    _path, _pending, asked = E.interview_path(config, issues, json.loads(answers_json))
    return E.evaluate_session(config, issues, {"answers": asked})


def documents(answers_json):
    """[motion .docx bytes, memo .docx bytes]."""
    import docx_render as D  # needs python-docx, which the page loads after the interview starts
    config = _repo[0]
    result = evaluate(answers_json)
    motion = R.render_motion(result)
    return [D.motion_docx(result), D.memo_docx(R.render_memo(result, config, motion))]

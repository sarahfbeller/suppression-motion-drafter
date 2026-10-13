"""Simulated interviews, for testing the decision tree and for the interview audit report.

A simulated case is a complete set of answers, every question answered. An interview asks next_question() repeatedly, answering from that set, until
the tree says it's done. Standard library only.
"""
import random

import engine as E
import validate as V


def random_answers(questions, rng, events=()):
    """A random complete set of answers. `events` are encounter events that must be checked."""
    answers = {}
    for qid, q in questions.items():
        if q["type"] == "short_text":
            answers[qid] = "x"
        elif q["type"] == "multi_select":
            answers[qid] = [o["id"] for o in q["options"] if rng.random() < 0.25]
        else:
            ids = ["yes", "no"] if q["type"] == "yes_no" else [o["id"] for o in q["options"]]
            answers[qid] = rng.choice(ids)
    answers[E.FILING_COURT] = rng.choice([o["id"] for o in questions[E.FILING_COURT]["options"]])
    picked = set(answers[E.ENCOUNTER_EVENTS]) | set(events)
    answers[E.ENCOUNTER_EVENTS] = [o["id"] for o in questions[E.ENCOUNTER_EVENTS]["options"] if o["id"] in picked]
    return answers


def gate_events(issue, rng):
    """Encounter events that satisfy the issue's event gate (one from each part of it)."""
    out = []
    for g in E.event_gate(issue["trigger"]["match_condition"])["all"]:
        leaves = g.get("any", [g])
        out.append(rng.choice(leaves)["value"])
    return out


def run_interview(issues, full):
    """Answer next_question() from `full` until done. Returns (answers given, questions asked in order)."""
    answers, asked = {}, []
    while True:
        qid = E.next_question(issues, answers)
        if qid is None:
            return answers, asked
        if qid in answers:
            raise AssertionError(f"{qid} asked twice")
        answers[qid] = full[qid]
        asked.append(qid)


def all_open(issues, answers):
    """Every question that could still be asked, given these answers."""
    if any(q not in answers for q in E.TOP_QUESTIONS):
        return None
    courts = E.binding_courts(answers)
    return {q for i in issues for q in E.issue_open_questions(i, answers, courts) if q not in answers}


def matching_answers(questions, issue, full, rng):
    """Answers that make the issue match while agreeing with as much of `full` as possible: the search
    keeps a random part of full's answers fixed, and keeps less if that can't match. Varying what's
    kept gives varied matching cases, not the same one every time."""
    match = issue["trigger"]["match_condition"]
    qids = [q for q in E.condition_questions(match)]
    for share in (0.6, 0.3, 0.0):
        kept = {q: full[q] for q in qids if rng.random() < share}
        found = V.satisfy(V.F_cond(match, kept), questions)
        if found is not None:
            return {**kept, **found}
    return None


def cases(questions, issues, per_issue, seed=0):
    """Random complete answer sets, per_issue for each issue plus per_issue fully random ones. Half of
    each issue's cases have its event happening; the other half start from answers that make it match
    (so an issue with a narrow trigger still gets its deeper questions exercised), with every other
    question random."""
    rng = random.Random(seed)
    for issue in issues:
        for n in range(per_issue):
            full = random_answers(questions, rng, gate_events(issue, rng))
            if n % 2:
                witness = matching_answers(questions, issue, full, rng)
                if witness is not None:
                    full.update(witness)
            yield issue["id"], full
    for _ in range(per_issue):
        yield None, random_answers(questions, rng)

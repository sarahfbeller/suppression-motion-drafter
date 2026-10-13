"""Checks the validator's search (satisfy) against brute force: for random small question sets and
random formulas, satisfy() must find answers exactly when some combination of answers works.

Run from the repo root:  python3 -m unittest discover tests
"""
import itertools
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import engine as E  # noqa: E402
import validate as V  # noqa: E402

TRIALS = 1500


def every_answer(q):
    """Every possible answer to q, plus None for unanswered."""
    if q["type"] == "yes_no":
        return ["yes", "no", None]
    ids = [o["id"] for o in q["options"]]
    if q["type"] == "multiple_choice":
        return ids + [None]
    return [list(c) for n in range(len(ids) + 1) for c in itertools.combinations(ids, n)] + [None]


def holds(f, answers):
    if f[0] == "c":
        a = {k: v for k, v in {**answers, **f[2]}.items() if v is not None}
        return E.eval_condition(f[1], a)
    if f[0] == "not":
        return not holds(f[1], answers)
    vals = [holds(g, answers) for g in f[1]]
    return all(vals) if f[0] == "and" else any(vals)


def random_questions(rng):
    qs = {}
    for n in range(rng.randint(1, 3)):
        kind = rng.choice(["yes_no", "multiple_choice", "multi_select"])
        q = {"id": f"q_{n}", "type": kind}
        if kind != "yes_no":
            k = rng.randint(2, 5 if kind == "multi_select" else 4)
            q["options"] = [{"id": f"o{i}", "label": f"O{i}"} for i in range(k)]
        qs[q["id"]] = q
    return qs


def random_leaf(rng, qs):
    q = rng.choice(list(qs.values()))
    ids = ["yes", "no"] if q["type"] == "yes_no" else [o["id"] for o in q["options"]]
    if q["type"] == "multi_select":
        op = rng.choice(["includes", "not_includes", "empty", "not_empty"])
        return {"question": q["id"], "op": op} if op in ("empty", "not_empty") else \
            {"question": q["id"], "op": op, "value": rng.choice(ids)}
    op = rng.choice(["equals", "not_equals", "in", "not_in"])
    if op in ("in", "not_in"):
        return {"question": q["id"], "op": op, "value": rng.sample(ids, rng.randint(1, len(ids)))}
    return {"question": q["id"], "op": op, "value": rng.choice(ids)}


def random_cond(rng, qs, depth):
    if depth == 0 or rng.random() < 0.4:
        return random_leaf(rng, qs)
    return {rng.choice(["all", "any"]): [random_cond(rng, qs, depth - 1) for _ in range(rng.randint(1, 3))]}


def random_formula(rng, qs, depth=2):
    r = rng.random()
    if depth == 0 or r < 0.4:
        ov = {}
        if rng.random() < 0.3:
            q = rng.choice(list(qs.values()))
            ov = {q["id"]: rng.choice([a for a in every_answer(q) if a is not None])}
        return V.F_cond(random_cond(rng, qs, 2), ov)
    if r < 0.55:
        return V.F_not(random_formula(rng, qs, depth - 1))
    kids = [random_formula(rng, qs, depth - 1) for _ in range(rng.randint(1, 3))]
    return V.F_and(*kids) if r < 0.8 else V.F_or(*kids)


class SearchMatchesBruteForce(unittest.TestCase):
    def test_random_formulas(self):
        rng = random.Random(7)
        for trial in range(TRIALS):
            qs = random_questions(rng)
            f = random_formula(rng, qs)
            ids = list(qs)
            truth = any(holds(f, dict(zip(ids, combo)))
                        for combo in itertools.product(*(every_answer(qs[i]) for i in ids)))
            found = V.satisfy(f, qs)
            self.assertEqual(found is not None, truth, f"trial {trial}: formula {f}, questions {qs}")
            if found is not None:
                self.assertTrue(holds(f, found), f"trial {trial}: answers {found} don't satisfy {f}")

    def test_not_in_list_with_an_unnamed_third_option(self):
        # The bug the regression check found: in a not_in list, only one member is kept as
        # representative, and the dropped member became the stand-in for "every other option".
        # The truly unnamed option (o2) was never tried, so this looked impossible.
        qs = {"q_0": {"id": "q_0", "type": "multiple_choice",
                      "options": [{"id": f"o{i}", "label": "x"} for i in range(3)]}}
        f = V.F_cond({"question": "q_0", "op": "not_in", "value": ["o0", "o1"]})
        self.assertEqual(V.satisfy(f, qs), {"q_0": "o2"})


if __name__ == "__main__":
    unittest.main()

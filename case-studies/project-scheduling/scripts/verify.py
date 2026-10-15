"""Offline schedule checks; optional SMT proof of the reference outcomes.

No model calls, credentials, or automatic explanation grading.
Run: python3 case-studies/project-scheduling/scripts/verify.py [--prove]
"""
import argparse
import itertools
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text())


def minutes(day, clock):
    hour, minute = map(int, clock.split(":"))
    return (int(day) - 19) * 1440 + hour * 60 + minute


def tasks_from_input(question):
    tasks = {}
    for line in question.splitlines():
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 6 or not re.fullmatch(r"[A-N](, (Standard|Accelerated))?", parts[0]):
            continue
        name = parts[0]
        tasks[name] = {
            "duration": int(float(parts[1].split()[0]) * 60),
            "resources": [p.strip() for field in parts[2:4] for p in field.split(",") if p.strip() != "-"],
            "prerequisites": [] if parts[4] == "-" else parts[4].split(", "),
            "cost": int(parts[5]),
        }
    assert len(tasks) == 15, "Expected A–N with two alternatives for G"
    return tasks


def selected_tasks(all_tasks, method):
    tasks = {k: v for k, v in all_tasks.items() if not k.startswith("G,")}
    tasks["G"] = all_tasks[f"G, {method}"]
    return tasks


def availability(spec, resource):
    return [(minutes(day, start), minutes(day, end))
            for day, windows in spec["effective_availability"][resource].items()
            for start, end in windows]


def parse_schedule(text):
    matches = re.findall(r"^- ([A-N]): October (19|20), (\d\d:\d\d)–(\d\d:\d\d)", text, re.M)
    assert len(matches) == 14, "Expected exactly 14 schedule entries"
    schedule = {name: (minutes(day, start), minutes(day, end)) for name, day, start, end in matches}
    assert set(schedule) == set("ABCDEFGHIJKLMN"), "Missing or duplicated task"
    return schedule


def check_schedule(schedule, tasks, spec):
    for task, (start, end) in schedule.items():
        detail = tasks[task]
        assert start % 30 == 0, f"{task}: start boundary"
        assert end - start == detail["duration"], f"{task}: duration"
        for resource in detail["resources"]:
            assert any(a <= start and end <= b for a, b in availability(spec, resource)), f"{task}: {resource} availability/lunch/day boundary"
        for prerequisite in detail["prerequisites"]:
            assert schedule[prerequisite][1] <= start, f"{task}: prerequisite {prerequisite}"
    for a, b in itertools.combinations(tasks, 2):
        if set(tasks[a]["resources"]) & set(tasks[b]["resources"]):
            assert schedule[a][1] <= schedule[b][0] or schedule[b][1] <= schedule[a][0], f"{a}/{b}: resource conflict"
    assert schedule["M"][0] >= minutes(spec["M_earliest"]["day"], spec["M_earliest"]["time"]), "M restriction"
    assert max(end for _, end in schedule.values()) <= minutes(spec["deadline"]["day"], spec["deadline"]["time"]), "Deadline"


def prove(dataset, spec, method, earlier_than=None):
    try:
        import z3
    except ImportError:
        raise SystemExit("Install the optional solver with: python3 -m pip install -r case-studies/project-scheduling/scripts/requirements-proof.txt")
    tasks = selected_tasks(tasks_from_input(dataset["input"]["question"]), method)
    solver = z3.Solver()
    starts = {task: z3.Int(f"start_{task}") for task in tasks}
    ends = {task: starts[task] + detail["duration"] for task, detail in tasks.items()}
    for task, detail in tasks.items():
        solver.add(starts[task] % 30 == 0)
        for resource in detail["resources"]:
            solver.add(z3.Or(*[z3.And(starts[task] >= a, ends[task] <= b) for a, b in availability(spec, resource)]))
        for prerequisite in detail["prerequisites"]:
            solver.add(starts[task] >= ends[prerequisite])
    for a, b in itertools.combinations(tasks, 2):
        if set(tasks[a]["resources"]) & set(tasks[b]["resources"]):
            solver.add(z3.Or(ends[a] <= starts[b], ends[b] <= starts[a]))
    solver.add(starts["M"] >= minutes(spec["M_earliest"]["day"], spec["M_earliest"]["time"]))
    deadline = minutes(spec["deadline"]["day"], spec["deadline"]["time"])
    for end in ends.values():
        solver.add(end <= deadline)
        if earlier_than is not None:
            solver.add(end < earlier_than)
    return solver.check()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prove", action="store_true")
    args = parser.parse_args()
    specs = load("datasets/reference-constraints.json")
    rows = load("results/annotations.json")
    for row in rows:
        dataset = load(f"datasets/{row['dataset']}.json")
        text = (ROOT / row["response_file"]).read_text()
        tasks = selected_tasks(tasks_from_input(dataset["input"]["question"]), "Accelerated")
        schedule = parse_schedule(text)
        spec = specs[row["dataset"]]
        check_schedule(schedule, tasks, spec)
        expected = dataset["expected_output"]["scenario_1"]
        completion = expected["earliest_completion"].split("T")[1][:5]
        assert max(end for _, end in schedule.values()) == minutes(20, completion)
        assert tasks["G"]["cost"] == expected["minimum_additional_cost"] <= spec["scenario_budgets"][0]
        assert tasks["G"]["cost"] > spec["scenario_budgets"][1]
        assert "INFEASIBLE" in text and "FEASIBLE" in text and "Accelerated" in text
        assert row["task_success"] is True
        print(f"PASS schedule: {row['id']}")
    for version in range(1, 5):
        prompt = load(f"prompts/v{version}.json")
        assert prompt["prompt"][1] == {"role": "user", "content": "{{question}}"}
    if args.prove:
        import z3
        for ident, spec in specs.items():
            dataset = load(f"datasets/{ident}.json")
            all_tasks = tasks_from_input(dataset["input"]["question"])
            for method, info in spec["methods"].items():
                task = all_tasks[f"G, {method}"]
                assert task["duration"] == info["duration_minutes"] and task["cost"] == info["cost"]
            assert prove(dataset, spec, "Standard") == z3.unsat
            assert prove(dataset, spec, "Accelerated") == z3.sat
            completion = dataset["expected_output"]["scenario_1"]["earliest_completion"].split("T")[1][:5]
            assert prove(dataset, spec, "Accelerated", minutes(20, completion)) == z3.unsat
            print(f"PASS proof: {ident}: Standard infeasible; Accelerated feasible and optimal")
    print("Explanation labels remain manual; this script does not verify natural-language proofs.")


if __name__ == "__main__":
    main()

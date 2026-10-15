import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class Score:
    name: str
    value: Any
    data_type: str
    comment: str


@dataclass
class EvaluationResult:
    scores: list[Score]


# Required durations for project-scheduling-validation-02.
# G is handled separately because its duration depends on the method.
DURATIONS = {
    "A": 60,
    "B": 60,
    "C": 60,
    "D": 60,
    "E": 60,
    "F": 60,
    "H": 60,
    "I": 30,
    "J": 30,
    "K": 30,
    "L": 30,
    "M": 30,
    "N": 30,
}


def read_answer(value):
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("{", "[")):
            try:
                return read_answer(json.loads(text))
            except json.JSONDecodeError:
                pass
        return value

    if isinstance(value, list):
        return "\n".join(read_answer(part) for part in value)

    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if value.get("content") is not None:
            return read_answer(value["content"])

    raise ValueError("Unsupported output structure.")


def status(value, comment):
    return EvaluationResult(scores=[
        Score(
            name="code_task_duration_status",
            value=value,
            data_type="CATEGORICAL",
            comment=comment,
        )
    ])


def evaluate_duration(ctx) -> EvaluationResult:
    output = ctx.observation.output

    if output is None or output == "":
        return status("no_output", "No answer available; not scored.")

    text = read_answer(output)

    # Supports bullet rows such as:
    # - G: October 19, 14:00–15:00
    # - G (Accelerated): October 19, 14:00–15:00
    pattern = (
        r"^[ \t]*(?:[-*][ \t]+)?"
        r"([A-N])(?:[ \t]*\([^\n)]*\))?"
        r"[ \t]*:[ \t]*(?:October|Oct)[ \t]+"
        r"(\d{1,2})(?:,[ \t]*2026)?[ \t]*,?[ \t]+"
        r"(\d{1,2}:\d{2})[ \t]*[–—-][ \t]*"
        r"(\d{1,2}:\d{2})"
    )

    rows = re.findall(pattern, text, flags=re.MULTILINE)

    if not rows:
        return status(
            "unparsed_schedule",
            "No supported bullet schedule found; not scored."
        )

    # Multiple feasible scenarios must be checked separately.
    tasks = [row[0] for row in rows]
    if len(tasks) != len(set(tasks)):
        return status(
            "ambiguous_schedule",
            "Repeated task rows found. Check each scenario separately."
        )

    missing = sorted(set("ABCDEFGHIJKLMN") - set(tasks))
    if missing:
        return status(
            "incomplete_schedule",
            "Missing tasks: " + ", ".join(missing)
            + ". Duration score not assigned."
        )

    # Read the selected method from the answer's explicit method field.
    methods = re.findall(
        r"(?:Selected testing method|Testing method)"
        r"[ \t]*:[ \t]*(?:G[ \t]*[-–—][ \t]*)?"
        r"(Accelerated|Standard)\b",
        text,
        flags=re.IGNORECASE,
    )

    methods = set(method.lower() for method in methods)
    if len(methods) != 1:
        return status(
            "unknown_testing_method",
            "Could not identify one explicit testing method; not scored."
        )

    method = next(iter(methods))
    required = dict(DURATIONS)
    required["G"] = 60 if method == "accelerated" else 120

    errors = []

    for task, day, start, end in rows:
        try:
            start_dt = datetime.strptime(
                f"2026-10-{int(day):02d} {start}",
                "%Y-%m-%d %H:%M",
            )
            end_dt = datetime.strptime(
                f"2026-10-{int(day):02d} {end}",
                "%Y-%m-%d %H:%M",
            )
        except ValueError:
            errors.append(f"{task}: invalid date or time")
            continue

        minutes = int((end_dt - start_dt).total_seconds() / 60)

        if minutes <= 0:
            errors.append(f"{task}: end must be later than start")
        elif minutes != required[task]:
            errors.append(
                f"{task}: expected {required[task]} minutes, "
                f"got {minutes} ({start}–{end})"
            )

    return EvaluationResult(scores=[
        Score(
            name="code_task_duration",
            value=not errors,
            data_type="BOOLEAN",
            comment=(
                "; ".join(errors)
                if errors else
                "All A–N durations match validation-02 requirements. "
                f"G method: {method}. "
                "Does not check availability, dependencies, resource "
                "conflicts, lunch, budget, deadline, or optimality."
            ),
        )
    ])

from types import SimpleNamespace


def evaluate(ctx) -> EvaluationResult:
    text = read_answer(ctx.observation.output)

    # Find task A's original one-hour interval.
    pattern = (
        r"(?m)^([ \t]*-[ \t]+A:[ \t]*"
        r"(?:October|Oct)[ \t]+19,[ \t]*)"
        r"09:00[–—-]10:00[ \t]*$"
    )

    if len(re.findall(pattern, text)) != 1:
        raise ValueError(
            "This test requires exactly one A row: "
            "October 19, 09:00–10:00."
        )

    # Change only the copy: A now lasts 30 minutes.
    wrong_answer = re.sub(
        pattern,
        lambda match: match.group(1) + "09:00–09:30",
        text,
    )

    variants = [
        ("original", text, True),
        ("wrong_a", wrong_answer, False),
    ]

    scores = []
    all_passed = True

    for label, answer, expected in variants:
        sample = SimpleNamespace(
            observation=SimpleNamespace(output=answer)
        )

        result = evaluate_duration(sample).scores[0]

        if result.data_type != "BOOLEAN":
            raise ValueError(
                f"Test could not be scored: {label}. "
                + result.comment
            )

        all_passed = all_passed and result.value == expected

        scores.append(Score(
            name="duration_test_" + label,
            value=result.value,
            data_type="BOOLEAN",
            comment=(
                f"Synthetic test. Expected {expected}; "
                f"observed {result.value}. "
                + result.comment
            ),
        ))

    scores.append(Score(
        name="duration_self_test_passed",
        value=all_passed,
        data_type="BOOLEAN",
        comment=(
            "True means both tests produced the expected results. "
            "The stored model answer was not modified."
        ),
    ))

    return EvaluationResult(scores=scores)
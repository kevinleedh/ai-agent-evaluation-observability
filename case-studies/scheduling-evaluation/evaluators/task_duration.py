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


def evaluate(ctx) -> EvaluationResult:
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

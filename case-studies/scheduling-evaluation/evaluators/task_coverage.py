import json
import re
from dataclasses import dataclass
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


def read_answer(value):
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("{", "[")):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return value
            return read_answer(parsed)
        return value
    if isinstance(value, list):
        return "\n".join(read_answer(part) for part in value)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if value.get("content") is not None:
            return read_answer(value["content"])
    raise ValueError("Unsupported output structure. Inspect the selected observation output.")


def evaluate(ctx) -> EvaluationResult:
    output = ctx.observation.output
    if output is None or output == "":
        return EvaluationResult(scores=[Score(
            name="code_task_coverage_status",
            value="unscored_no_output",
            data_type="CATEGORICAL",
            comment="No answer available; task coverage was not scored."
        )])

    text = read_answer(output)
    patterns = [
        r"^\s*(?:[-*]\s+)?([A-N])(?:\s*\([^\n)]*\))?\s*:\s*(?:October|Oct)\s+\d{1,2}\b",
        r"^\s*\|\s*([A-N])(?:\s*\([^\n|)]*\))?\s*\|\s*(?:October|Oct)\s+\d{1,2}\s*\|",
    ]
    tasks = [task for pattern in patterns
             for task in re.findall(pattern, text, flags=re.MULTILINE)]

    if not tasks:
        return EvaluationResult(scores=[Score(
            name="code_task_coverage_status",
            value="unparsed_schedule",
            data_type="CATEGORICAL",
            comment="No supported schedule rows found. Check the selected observation and answer format; no quality score was assigned."
        )])

    expected = list("ABCDEFGHIJKLMN")
    missing = [task for task in expected if task not in tasks]
    duplicates = [task for task in expected if tasks.count(task) > 1]
    return EvaluationResult(scores=[Score(
        name="code_task_coverage",
        value=not missing and not duplicates,
        data_type="BOOLEAN",
        comment=(
            f"Missing: {', '.join(missing) or 'none'}; "
            f"duplicates: {', '.join(duplicates) or 'none'}. "
            "Checks task listing only, not schedule validity or explanation accuracy."
        )
    )])

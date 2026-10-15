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


def evaluate_coverage(ctx) -> EvaluationResult:
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


class Observation:
    def __init__(self, output):
        self.output = output

class Context:
    def __init__(self, output):
        self.observation = Observation(output)

def evaluate(ctx) -> EvaluationResult:
    # Mutate only in-memory copies. The stored answer remains unchanged.
    text = read_answer(ctx.observation.output)
    n_pattern = r"(?m)^[-*] N: (?:October|Oct) [^\n]+$"
    rows = re.findall(n_pattern, text)
    if len(rows) != 1:
        raise ValueError("Self-test requires exactly one bullet-format N row.")
    n_row = rows[0]
    variants = [
        ("original", text, True),
        ("missing_n", re.sub(n_pattern, "", text), False),
        ("duplicate_n", text + "\n" + n_row, False),
    ]
    scores = []
    all_passed = True
    for label, answer, expected in variants:
        result = evaluate_coverage(Context(answer)).scores[0]
        if result.data_type != "BOOLEAN":
            raise ValueError("Self-test could not parse the schedule: " + label)
        matched = result.value == expected
        all_passed = all_passed and matched
        scores.append(Score(
            name="coverage_test_" + label,
            value=result.value,
            data_type="BOOLEAN",
            comment=(f"Synthetic evaluator test; expected {expected}, observed {result.value}. "
                     + result.comment + " Stored model output was not modified.")
        ))
    scores.append(Score(
        name="coverage_self_test_passed",
        value=all_passed,
        data_type="BOOLEAN",
        comment="True means all three test results match their expected values. Synthetic test scores do not grade the original model answer."
    ))
    return EvaluationResult(scores=scores)

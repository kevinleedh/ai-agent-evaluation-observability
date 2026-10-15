"""Langfuse Python Code evaluator. Scope: exact validation-02 input only.

Deterministic schedule checks plus comparison with a fixed reviewed reference.
Natural-language factual correctness/proofs are deliberately left unscored.
Standard library only; no model calls, network, or optimization solver.
"""
import hashlib
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


# Filled from the archived validation-02 question, not from model output.
INPUT_SHA256 = "3f0ca185046e08d778e018ec06665ad9f397e6867a623798fb3046e79df194c8"
TASKS = {
    # minutes, people/resources, prerequisites
    "A": (60, ("Alex", "Maya", "Review Room"), ()),
    "B": (60, ("Alex",), ("A",)),
    "C": (60, ("Ethan",), ("A",)),
    "D": (60, ("Ethan", "GPU"), ("B", "C")),
    "E": (60, ("Maya",), ("A",)),
    "F": (60, ("Alex", "Ethan"), ("D",)),
    "G": (None, ("Ethan", "GPU"), ("F",)),
    "H": (60, ("Maya",), ("E", "F")),
    "I": (30, ("Maya", "Ethan", "Review Room"), ("G", "H")),
    "J": (30, ("Alex",), ("I",)),
    "K": (30, ("Maya",), ("I",)),
    "L": (30, ("Ethan", "GPU"), ("J", "K")),
    "M": (30, ("Alex", "Maya", "Review Room"), ("L",)),
    "N": (30, ("Ethan", "GPU"), ("M",)),
}
METHODS = {"standard": (120, 0), "accelerated": (60, 5)}
BUDGETS = {1: 5, 2: 4}
DEADLINE = datetime(2026, 10, 20, 10, 0)
M_EARLIEST = datetime(2026, 10, 20, 9, 0)
REFERENCE_METHOD = "accelerated"
REFERENCE_COST = 5
REFERENCE_FINISH = DEADLINE


def canonical(text):
    return re.sub(r"\s+", " ", text).strip()


def input_strings(value):
    """Read input text across dict/messages/serialized JSON wrappers."""
    if isinstance(value, str):
        yield value
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return
        if not isinstance(parsed, str) or parsed != value:
            yield from input_strings(parsed)
    elif isinstance(value, list):
        for part in value:
            yield from input_strings(part)
    elif isinstance(value, dict):
        for part in value.values():
            yield from input_strings(part)


def read_answer(value):
    if isinstance(value, str):
        if value.strip().startswith(("{", "[")):
            try:
                return read_answer(json.loads(value))
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
    raise ValueError("Unsupported output wrapper; inspect observation.output.")


def status(name, value, comment):
    return Score(name, value, "CATEGORICAL", comment)


def check(scores, name, errors, success):
    scores.append(Score(name, not errors, "BOOLEAN",
                        "; ".join(errors) if errors else success))
    return not errors


def clean(text):
    # Remove common presentation markup, not natural-language content.
    return text.replace("**", "").replace("`", "").replace("\r\n", "\n")


DATE = r"(?:October|Oct\.?)[ \t]+(\d{1,2})(?:[ \t]*,[ \t]*2026)?"
ROW = re.compile(
    r"^[ \t]*(?:[-*][ \t]+)?([A-N])(?:[ \t]*\(([^\n)]*)\))?"
    r"[ \t]*:[ \t]*" + DATE +
    r"[ \t]*,?[ \t]+(\d{1,2}:\d{2})[ \t]*[–—-][ \t]*"
    r"(\d{1,2}:\d{2})(?:[ \t]*\(([^\n)]*)\))?[ \t]*$",
    re.IGNORECASE,
)
CANDIDATE = re.compile(r"^[ \t]*(?:[-*][ \t]+)?[A-N](?:[ \t]*\([^\n)]*\))?[ \t]*:")


def parse_rows(section):
    rows, errors = {}, []
    for line in section.splitlines():
        # Table: | A | Oct 19 | 09:00 | 10:00 |
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and re.fullmatch(r"[A-N](?:\s*\([^)]*\))?", cells[0]):
                if len(cells) != 4:
                    errors.append("Unsupported schedule table row: " + line)
                    continue
                line = f"{cells[0]}: {cells[1]}, {cells[2]}–{cells[3]}"
        match = ROW.fullmatch(line)
        if not match:
            if CANDIDATE.match(line):
                errors.append("Unparsed task row: " + line)
            continue
        task, label1, day, start, end, label2 = match.groups()
        task = task.upper()
        if task in rows:
            errors.append("Duplicate task " + task)
            continue
        try:
            start_dt = datetime.strptime(f"2026-10-{int(day):02d} {start}", "%Y-%m-%d %H:%M")
            end_dt = datetime.strptime(f"2026-10-{int(day):02d} {end}", "%Y-%m-%d %H:%M")
        except ValueError:
            errors.append("Invalid date/time for " + task)
            continue
        rows[task] = (start_dt, end_dt, " ".join((label1 or "", label2 or "")).lower())
    return rows, errors


def parse_completion(section):
    matches = re.findall(
        r"(?:Project completion|Completion)[ \t]*:[ \t]*" + DATE +
        r"[ \t]*(?:,[ \t]*|at[ \t]+)?(\d{1,2}:\d{2})", section, re.IGNORECASE)
    if len(matches) != 1:
        return None
    try:
        day, clock = matches[0]
        return datetime.strptime(f"2026-10-{int(day):02d} {clock}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def evaluate(ctx) -> EvaluationResult:
    scores = []
    supplied_input = getattr(ctx.observation, "input", None)
    matched_input = any(
        hashlib.sha256(canonical(s).encode()).hexdigest() == INPUT_SHA256
        for s in input_strings(supplied_input)
    )
    if not matched_input:
        return EvaluationResult([status(
            "sched_input_status", "unsupported_input",
            "Exact validation-02 question not found in observation.input. "
            "No quality score assigned. Do not use this evaluator on other datasets.")])
    scores.append(status("sched_input_status", "matched_validation_02", "Input fingerprint matched reviewed validation-02 question."))
    output = ctx.observation.output
    if output is None or output == "":
        return EvaluationResult(scores + [status("sched_parse_status", "no_output", "No completed answer; unscored.")])
    try:
        text = clean(read_answer(output))
    except ValueError as error:
        return EvaluationResult(scores + [status("sched_parse_status", "unsupported_output", str(error))])

    # This case has exactly two verdicts, in scenario order. Headers are optional.
    verdicts = list(re.finditer(r"\bVerdict[ \t]*:[ \t]*(INFEASIBLE|FEASIBLE)\b", text, re.IGNORECASE))
    if len(verdicts) != 2:
        return EvaluationResult(scores + [status(
            "sched_parse_status", "unsupported_scenarios",
            "Expected two explicit Verdict fields in scenario order; no quality score assigned.")])
    headers = re.findall(r"\bScenario[ \t]+([1-9]\d*)\b", text, re.IGNORECASE)
    if any(h not in ("1", "2") for h in headers):
        return EvaluationResult(scores + [status("sched_parse_status", "unsupported_scenarios", "Unexpected scenario number; unscored.")])
    overall = True
    for index, verdict_match in enumerate(verdicts):
        scenario = index + 1
        prefix = f"sched_s{scenario}_"
        end_pos = verdicts[index + 1].start() if index + 1 < len(verdicts) else len(text)
        section = text[verdict_match.end():end_pos]
        verdict = verdict_match.group(1).upper()
        expected_verdict = "FEASIBLE" if scenario == 1 else "INFEASIBLE"
        verdict_ok = check(scores, prefix + "verdict_reference", [] if verdict == expected_verdict else [f"Expected {expected_verdict}, got {verdict}"], "Verdict agrees with fixed reviewed reference; not a newly computed proof.")
        overall = overall and verdict_ok
        rows, row_errors = parse_rows(section)
        if verdict == "INFEASIBLE":
            no_schedule = check(scores, prefix + "no_infeasible_schedule", row_errors + (["Infeasible scenario includes a task schedule"] if rows else []), "No supported task schedule presented for infeasible scenario.")
            has_justification = bool(re.search(r"\b(?:Justification|because|budget|cannot|impossible)\b", section, re.IGNORECASE))
            check(scores, prefix + "justification_present", [] if has_justification else ["No recognizable justification"], "Justification text present; factual correctness not assessed.")
            overall = overall and no_schedule and has_justification
            continue

        missing = sorted(set(TASKS) - set(rows))
        coverage_errors = row_errors + (["Missing: " + ", ".join(missing)] if missing else [])
        complete = check(scores, prefix + "coverage", coverage_errors, "All A–N occur once in supported schedule rows.")
        methods = set(m.lower() for m in re.findall(
            r"(?:Selected testing method|Testing method)[ \t]*:[ \t]*(?:G[ \t]*[-–—][ \t]*)?(Accelerated|Standard)\b", section, re.IGNORECASE))
        costs = re.findall(r"Additional cost[ \t]*:[ \t]*\$?([0-9]+(?:\.[0-9]+)?)(?![\w.])", section, re.IGNORECASE)
        completion = parse_completion(section)
        format_errors = []
        if len(methods) != 1:
            format_errors.append("Expected one explicit testing method")
        if len(costs) != 1:
            format_errors.append("Expected one explicit additional cost")
        if completion is None:
            format_errors.append("Missing/ambiguous completion date and time")
        if not re.search(r"\b(?:Justification|because|No cheaper|minimum cost)\b", section, re.IGNORECASE):
            format_errors.append("No recognizable justification")
        format_ok = check(scores, prefix + "required_fields", format_errors, "Required summary fields and justification marker parsed.")
        if not complete or not format_ok:
            overall = False
            scores.append(status(prefix + "constraint_status", "unscored_incomplete_or_unparsed", "Detailed checks skipped to avoid false passes on missing/unparsed fields."))
            continue
        method = next(iter(methods))
        cost = float(costs[0])
        duration_errors, dependency_errors, availability_errors = [], [], []
        boundary_errors, overlap_errors, approved_errors = [], [], []
        for task, (start, finish, label) in rows.items():
            minutes, resources, predecessors = TASKS[task]
            required = METHODS[method][0] if task == "G" else minutes
            actual = (finish - start).total_seconds() / 60
            if actual != required:
                duration_errors.append(f"{task}: expected {required} min, got {actual:g}")
            if task == "G" and label.strip() and label.strip() != method:
                duration_errors.append("G row label conflicts with selected method")
            for predecessor in predecessors:
                if rows[predecessor][1] > start:
                    dependency_errors.append(f"{task} starts before {predecessor} finishes")
            # Every named person/resource has identical windows in validation-02.
            in_day = start.month == 10 and start.day in (19, 20) and start.date() == finish.date()
            s, e = start.hour * 60 + start.minute, finish.hour * 60 + finish.minute
            in_block = finish > start and ((540 <= s < e <= 720) or (780 <= s < e <= 1020))
            if not (in_day and in_block):
                availability_errors.append(f"{task}: outside allowed date/work block for {', '.join(resources)}")
            if start.minute not in (0, 30):
                boundary_errors.append(f"{task}: start is not on a 30-minute boundary")
        names = list(rows)
        for i, left in enumerate(names):
            for right in names[i + 1:]:
                shared = set(TASKS[left][1]) & set(TASKS[right][1])
                if shared and max(rows[left][0], rows[right][0]) < min(rows[left][1], rows[right][1]):
                    overlap_errors.append(f"{left}/{right} overlap on {', '.join(sorted(shared))}")
        if rows["M"][0] < M_EARLIEST or rows["M"][0].date() != M_EARLIEST.date():
            approved_errors.append("M must start on October 20 at/after 09:00")
        finish = max(row[1] for row in rows.values())
        budget_errors = []
        if cost != METHODS[method][1]:
            budget_errors.append(f"Reported cost {cost:g} does not match {method} cost {METHODS[method][1]}")
        if METHODS[method][1] > BUDGETS[scenario] or cost > BUDGETS[scenario]:
            budget_errors.append("Additional cost exceeds scenario budget")
        deadline_errors = [] if finish <= DEADLINE else ["Actual schedule completion exceeds October 20 10:00"]
        completion_errors = [] if completion == finish else ["Reported completion does not equal latest task finish"]
        groups = [
            ("durations", duration_errors), ("dependencies", dependency_errors),
            ("availability_lunch_continuity", availability_errors),
            ("start_boundaries", boundary_errors), ("resource_exclusivity", overlap_errors),
            ("approved_m_constraint", approved_errors), ("budget_cost", budget_errors),
            ("deadline", deadline_errors), ("completion_consistency", completion_errors),
        ]
        valid_schedule = True
        for name, errors in groups:
            passed = check(scores, prefix + name, errors, "Passed for fixed validation-02 constraints.")
            valid_schedule = valid_schedule and passed
        optimal_errors = []
        if not valid_schedule:
            optimal_errors.append("Schedule violates mandatory constraints")
        if method != REFERENCE_METHOD or cost != REFERENCE_COST or finish != REFERENCE_FINISH:
            optimal_errors.append("Method/cost/finish do not match reviewed optimal reference: Accelerated, 5, October 20 10:00")
        optimal = check(scores, prefix + "optimality_reference", optimal_errors, "Valid schedule matches reviewed minimum cost and earliest completion; no solver/proof evaluation performed.")
        overall = overall and valid_schedule and optimal
    scores.append(Score("sched_all_deterministic_checks", overall, "BOOLEAN", "Covers supported output fields, schedule constraints and fixed reference outcomes only. Does not grade natural-language explanation accuracy."))
    scores.append(status("sched_explanation_accuracy_status", "requires_human_or_llm_judge", "Explanation truth, all prose time statements, and validity of optimization/infeasibility arguments remain unscored. Presence is checked separately."))
    return EvaluationResult(scores)

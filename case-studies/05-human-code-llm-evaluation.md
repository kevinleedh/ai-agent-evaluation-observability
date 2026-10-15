# From Human Review to Code Assertions and an LLM Judge

## Summary

After [case 04's prompt-iteration study](04-prompt-iteration-scheduling.md), I reused
its saved scheduling answers to learn how three evaluation methods fit together:
human review defines the error, deterministic code checks explicit constraints,
and an LLM judge examines the final explanation's factual claims and argument.
These methods complement each other; they are not three votes on one identical
criterion, and passing one does not imply passing all.

The integrated code evaluator passed the two selected validation-02 answers.
An LLM judge agreed with prior human explanation labels on those two positive
answers and on one negative validation-01/v4 answer. The negative answer has a valid
schedule but a sentence that contradicts that schedule. This is a small,
retrospective calibration exercise, not proof of a generally reliable evaluator.

## Why this is a separate case

Case 04 asks whether changing the generation prompt improves an answer on new
problems. This case asks whether an evaluator detects the relevant errors in an
existing answer. It introduces separate code artifacts, deliberate answer mutations,
a judge prompt, and comparisons with human labels. The datasets and seven published
final answers remain in [project-scheduling/](project-scheduling/); no new model
answers were generated for this follow-up. LLM judging itself does make paid model
calls during the user's evaluation session.

## Evaluation structure

```text
Stored problem + stored final answer
    |
    +-- Human review: task_success and explanation_accuracy
    |
    +-- Code: explicit schedule constraints and reviewed reference outcomes
    |
    +-- LLM judge: explanation facts, schedule consistency, and arguments

Separate self-tests deliberately corrupt answer copies to test the code checker.
```

| Method | Evidence inspected | What the result means |
|---|---|---|
| Human review | Problem, complete schedule and final justification | A prior assistant-assisted label, with a concrete error explanation |
| Code evaluator | Parsed task intervals and fixed validation-02 constraints | Supported deterministic checks passed/failed; no claim about prose truth |
| LLM-as-judge | Original input and complete final answer | Model judgment of explanation accuracy, with a written reason |
| Code self-test | Original and deliberately corrupted in-memory copies | Whether the checking logic returns the expected values on those cases |

Human labels are retained as comparison evidence. They are not passed to the judge
as answers to imitate. The judge is instructed to ignore embedded instructions and
`reasoningText`, and assess the final-answer `text` field only.

## 1. Begin with human labels

The existing rubric separates a valid outcome from a valid explanation. In
validation-01/v4, B finishes at 14:30, C at 15:00, and D begins at 15:00. Yet the
explanation says B and C cannot finish early enough for the 15:00–17:00 GPU slot.
Starting exactly when a prerequisite finishes is allowed. That sentence is false,
even though the schedule and final feasibility conclusion are correct.

This example gives the judge a useful negative calibration case without generating
a deliberately bad model answer. The two validation-02 responses are positive cases.
See the original [manual annotations](project-scheduling/results/annotations.json)
and [validation-01/v4 answer](project-scheduling/responses/validation-01-v4.txt).

## 2. Turn explicit requirements into code checks

The first evaluators checked A–N task coverage and elapsed task durations. The
integrated [Python evaluator](scheduling-evaluation/evaluators/scheduling_validation02.py),
saved in Langfuse as `code_schedule_validation02`, then covered:

- Required verdict/method/cost/completion fields and a recognizable justification marker.
- Task coverage and duration, including Standard versus Accelerated G.
- Prerequisites, allowing a successor to start exactly at a predecessor's finish.
- Personnel and shared-resource windows; no person/resource double booking.
- Lunch/day boundaries, one continuous declared interval per task, and 30-minute starts.
- The approved October 20 M start restriction; proposed lunch/deadline changes are ignored.
- Actual method cost, budget, deadline, and consistency of reported completion with the last task.
- Verdicts, optimal cost and finish compared with the reviewed reference outcome.

The input fingerprint matches the exact archived validation-02 question after
whitespace normalization. This is important: validation-01 has different durations,
availability, cost, budget and deadline. The evaluator returns an **unscored status**
on unsupported input, not a misleading pass. It supports the documented English
bullet/table formats and two explicit verdict fields in scenario order; it is not a
general natural-language parser.

`optimality_reference` means comparison with the reviewed reference; it does not
perform a new optimization search or verify the model's proof. Justification presence
is a shallow marker check, not explanation accuracy. Unknown interruptions cannot be
inferred from a declared interval. Explanation semantics remain explicitly unscored
under `sched_explanation_accuracy_status=requires_human_or_llm_judge`.

### Verify the checker with known errors

A saved normal answer returning True is insufficient to test error detection. Two
separate self-test evaluators create in-memory copies and run the checking function
on each copy. They contain copied checker logic; they do not invoke a different
saved Langfuse evaluator by its ID. Future checker changes must be mirrored and
retested rather than assuming these copied self-tests still cover the latest version.

| Synthetic input | Checker result | Expected? |
|---|---|---|
| Original A–N answer | True | Yes |
| N row removed | False: Missing N | Yes |
| N row duplicated | False: duplicate N | Yes |
| A shortened from 09:00–10:00 to 09:00–09:30 | False: 30 minutes instead of 60 | Yes |

The corrupted copies are not written back to the stored Output. Their `False`
scores are diagnostic test results, not failures of the original model answer.
The explicit `*_self_test_passed=True` score means the observed results match the
expected results. Such synthetic metrics should be excluded from answer-quality
aggregates.

The integrated code also has [26 local regression checks](scheduling-evaluation/tests/test_scheduling_validation02.py),
including missing/duplicate tasks, wrong durations, dependency violations, people/GPU
overlaps, lunch/date/start-boundary violations, the M restriction, cost/deadline/
completion mismatches, unsupported input, and formatting variants. These are selected
coverage checks, not exhaustive verification.

## 3. Judge the final explanation with an LLM

The evaluator `llm_explanation_accuracy` uses the
[published judge instruction](scheduling-evaluation/evaluators/explanation_judge.txt)
and Boolean scoring. Its variables map Input to `{{input}}` and Output to
`{{output}}`. The criteria are factual accuracy, agreement with the submitted
schedule, distinction between availability and task intervals, and valid
feasibility/infeasibility/minimum-cost/earliest-completion arguments. Correct final
conclusions do not excuse a false decisive claim. Alternative valid schedules and
sound concise proofs are allowed.

The visible judge model was `grok-4.7`. The complete per-run parameter snapshots
were not exported. The exact instruction is preserved as supplied in chat, not as
an independently exported history of every evaluator version. Generation prompt
versions v3/v4 and judge versions are different objects and should not be conflated.

| Saved answer | Prior human explanation label | Integrated code | LLM explanation label |
|---|---|---|---|
| Validation-02/v3 | True | True | True |
| Validation-02/v4 | True | True | True |
| Validation-01/v4 | False | Not applicable: validation-02 only | False |

These three completed judgments agree with the prior labels. This is a descriptive
observation from two positives and one known negative selected after human review;
it is not an accuracy estimate, a blinded holdout, or a confusion matrix with useful
population-level precision/recall. No general judge ranking is supported.

### Inspect the reason, not just the Boolean

On validation-02, the judge's comments explain that Standard G cannot finish before
16:00 and leave the 1.5 hours required to reach L, while M/N occupy the next morning's
09:00–10:00 deadline window. A second comment uses the 7.5-hour Standard critical
path against seven working hours. Both are specific, checkable arguments. The full
[comments and selected results](scheduling-evaluation/results/judge-results.json)
are preserved with their evidence provenance.

On validation-01/v4, the completed judge result specifically identifies the B/C
sentence: C ends at 15:00 and D starts at 15:00, contradicting the claim that B/C
cannot finish in time. It also points out the omitted morning 10:00–12:00 GPU
window when the answer calls 15:00–17:00 the "only" two-hour window. That morning
window does not itself make Standard feasible; the key finding is an inaccurate
explanation, not a newly feasible alternative schedule.

## 4. Separate execution failures from answer judgments

Some judge attempts timed out after 120 seconds, including a single-answer attempt
after removing Compare. No Boolean explanation score was produced for those
attempts. A later validation-01/v4 call completed in about 57 seconds and returned
False. Speed was not the objective and applied parameter changes were not verified;
no causal explanation or latency improvement is claimed.

A timeout means the evaluation failed to complete. False means a completed judge
found a problem in the answer. These must not share an accuracy denominator without
an explicit operational policy. [Selected execution observations](scheduling-evaluation/results/execution-observations.json)
are incomplete and do not support a timeout-rate estimate.

## Inspect or replay in Langfuse

1. Open an existing experiment and select its dataset row. Compare is optional.
2. Choose **Evaluate**, select a saved evaluator, then **Run Evaluation**. This
   evaluates the existing answer; it does not regenerate the scheduling response.
3. For code, create a Python Code evaluator with a published source file. Save it
   and choose **Skip execution** rather than attaching a broad automatic rule.
   Apply the integrated evaluator only to validation-02.
4. For the LLM judge, use the published prompt, Boolean output, original input and
   final output mappings, and a recorded model configuration. Check sample evidence
   before expanding its scope. A judge invocation does make a model call.
5. Batch Actions shows bulk processing progress. Confirm score creation in Scores or
   the experiment, and inspect Tracing for evaluator runtime errors.

In this UI, default environment filters hid the experiment scores. The following
Scores query made the explanation scores visible:

```text
environment:langfuse-prompt-experiment name:llm_explanation_accuracy
```

The score is attached to the evaluated experiment observation. Judge execution
records live under `langfuse-llm-as-a-judge`; code execution records under
`langfuse-code-eval`. These are different views of target results and evaluator
execution, not different verdicts. In Scores, **Row height -> Large** displays full
comments across multiple lines. Names/menu details describe the observed UI and
may change.

## Offline checks

From the repository root, with Python 3.10+ and no credentials:

```bash
python3 case-studies/scheduling-evaluation/tests/test_scheduling_validation02.py
python3 case-studies/scheduling-evaluation/tests/test_basic_evaluators.py
```

These run deterministic evaluator tests only. They do not call Langfuse or a model,
recreate the LLM judgments, or validate arbitrary prose. Files under
[evaluators/](scheduling-evaluation/evaluators/) are standalone standard-library
Python sources intended for the Langfuse Code editor. See
[provenance](scheduling-evaluation/PROVENANCE.md) for what was observed versus authored.

## Conclusion and limits

This completes one practical loop: identify an explanation error with human review,
automate explicit schedule checks, test the checker on known mutations, then inspect
an LLM judge's agreement and written reasons on selected positive and negative cases.
It demonstrates the workflow, not that any evaluator is universally correct.

The next reliability study should freeze evaluator settings and expand independent
human-reviewed examples across new error types, especially zero-cost feasible and
all-methods-infeasible problems, correct alternative schedules, partial answers and
formatting changes. Review disagreements and preserve every attempt. Avoid tuning
only to the known B/C sentence or calling inspected regression examples unseen data.

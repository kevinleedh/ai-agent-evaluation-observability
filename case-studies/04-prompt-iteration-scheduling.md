# Prompt Changes Can Fix One Explanation and Fail on a New Case

## Summary

I used Langfuse prompt experiments to investigate a scheduling answer that reached the right outcome but explained a time interval incorrectly. I revised the system prompt, checked the same development problem, and then compared versions 3 and 4 on two new synthetic problems.

Version 4 corrected the availability-window confusion on the development problem. On the first new problem, however, it introduced a different contradiction between its explanation and its own schedule. Both versions passed the second new problem.

The lesson is narrower than “a longer prompt improves accuracy”: a targeted instruction can fix a visible example without producing a consistent improvement on new inputs. Outcome correctness and explanation correctness need separate labels.

## Evidence and experimental scope

This is a retrospective, AI-assisted learning case assembled from the user's pasted final answers, prompt text, problem definitions, and Langfuse screenshots on October 15, 2026. The artifact contains seven completed final answers; it is not a full API or Langfuse export. [Provenance and limitations](project-scheduling/PROVENANCE.md) distinguish reconstructed material from directly transcribed responses.

| Component | Recorded setup |
|---|---|
| Interface | Langfuse Cloud prompt experiments |
| Model family for the seven final answers | Grok, from the conversation's experiment context |
| Exact model ID | Not independently verified for each pasted answer |
| Prompt | `project-scheduling-v1`, versions 1–4; the name remains the same across versions |
| User message template | `{{question}}` |
| Development dataset | `project-scheduling` |
| New problem datasets | `project-scheduling-validation-01`, `project-scheduling-validation-02` |
| Intended controls | Same model, dataset, and model options within each version comparison |
| Actual option snapshots | Incomplete; identical options cannot be certified from the preserved evidence |
| Repetitions | One selected completed answer per published dataset/version cell; not an exhaustive attempt log |
| Grading | Manual review in chat, with separate outcome and explanation criteria |

Kimi experiments earlier in the learning session encountered 120-second timeouts and a separate account concurrency limit. A v2 timeout was also reported in the development comparison. These execution observations are documented separately and are not counted as completed-answer accuracy results. No runtime improvement is claimed.

## Prompt changes

The rules, optimization objective, output requirements, and user-variable template stayed fixed. Only the additional system instructions changed. The full chat prompts are in [prompts/](project-scheduling/prompts/).

| Version | Added instruction relative to the base |
|---|---|
| v1 | Base rules; no additional explanation consistency instruction |
| v2 | Explicitly verify time-related statements, check starts and finishes separately, and correct inconsistencies |
| v3 | Replace v2's addition with “Ensure that all start and finish times in the explanation match the final schedule.” |
| v4 | Keep v3; add instructions to distinguish full availability windows from scheduled/earliest task intervals |

v1 versus v3 tests adding a time-consistency instruction. v3 versus v4 tests adding a distinction between availability windows and task intervals. This is not an isolated test of prompt length. A v2 timeout does not show that its longer instruction caused the timeout.

## Problems and reference outcomes

Each dataset item has `input.question` and a separate `expected_output`. Expected outputs are grading references, not model input. The problems involve tasks A–N, shared people and resources, continuous tasks, lunch/day boundaries, approved changes, budgets, and a lexicographic objective: satisfy constraints, minimize additional cost, then minimize completion time.

| Problem | Standard / Accelerated G | Approved earliest M | Budgets | Reference outcome |
|---|---|---|---|---|
| Development | 3 h / 1.5 h, Accelerated costs 6 | Oct 20, 16:00 | 6 / 5 | Scenario 1: cost 6, finish 17:00; Scenario 2: infeasible |
| Validation 01 | 2 h / 1 h, Accelerated costs 4 | Oct 20, 15:30 | 4 / 3 | Scenario 1: cost 4, finish 16:30; Scenario 2: infeasible |
| Validation 02 | 2 h / 1 h, Accelerated costs 5 | Oct 20, 09:00 | 5 / 4 | Scenario 1: cost 5, finish 10:00; Scenario 2: infeasible |

Validation 02 also changes several task durations, availability windows, and the deadline. It tests the lunch boundary and the forced next-day M/N tail. Full inputs and grading references are in [datasets/](project-scheduling/datasets/).

These new problems were not used to write v4 before their first observed answers. They are related, assistant-generated variants, however, not an independent benchmark or a statistically representative held-out set. Once inspected here, they are regression cases rather than unseen tests.

## Evaluation contract

| Label | Meaning |
|---|---|
| `task_success` | Both scenario verdicts and the feasible schedule's constraints, minimum cost, and optimal completion are correct |
| `explanation_accuracy` | Final explanation is factually correct, agrees with the schedule/input, and distinguishes availability windows from task intervals |
| Execution status | Record completion, timeout, or concurrency rejection separately; absent completed answers remain unscored on the two quality labels |

`task_success=True` is intentionally a narrow outcome label, not a claim that the entire response meets every quality requirement. An overall acceptance rule could require both labels to be True. The separate explanation label was introduced after reviewing the first validation problem, and earlier published answers were reviewed retrospectively using that rubric. The labels are not an exported record of what was saved in the UI. [Rubric](project-scheduling/results/rubric.json) · [Annotations](project-scheduling/results/annotations.json)

## Results

| Problem | Version | Task success | Explanation accuracy |
|---|---|---|---|
| Development | v1 | Pass | Fail |
| Development | v3 | Pass | Fail |
| Development | v4 | Pass | Pass |
| Validation 01 | v3 | Pass | Pass |
| Validation 01 | v4 | Pass | Fail |
| Validation 02 | v3 | Pass | Pass |
| Validation 02 | v4 | Pass | Pass |

On the two new problems, v3 passed outcome and explanation checks in 2/2 selected answers; v4 passed outcome checks in 2/2 and explanation checks in 1/2. These are descriptive counts from a tiny convenience sample, not estimated population accuracies or proof that v3 is generally superior.

## Error analysis

### 1. Confusing availability duration with task duration

The [development v1 answer](project-scheduling/responses/development-v1.txt) calls October 20, 13:00–17:00 a “three-hour window.” That is a four-hour availability interval. Standard G lasts three hours; its earliest placement is 13:00–16:00.

The [development v3 answer](project-scheduling/responses/development-v3.txt) similarly calls 13:00–16:00 the only three-hour overlap. The full common availability remains 13:00–17:00, which contains multiple possible three-hour placements. They all fail the deadline once successor tasks are included. The outcome is correct, but the explanation's interval claim is not.

The [development v4 answer](project-scheduling/responses/development-v4.txt) correctly refers to the only common window **of at least three hours**, 13:00–17:00, and explains why G must finish by 14:30. The targeted error was absent in this answer.

### 2. A new contradiction despite the targeted correction

The [validation-01 v4 answer](project-scheduling/responses/validation-01-v4.txt) says B and C cannot finish in time for the October 19 GPU slot at 15:00–17:00. Its own schedule shows B ending at 14:30, C ending at 15:00, and D starting at 15:00. Starting exactly when a prerequisite finishes is allowed, so that explanation sentence is false.

The correct explanation is: B and C finish at 14:30 and 15:00; the GPU becomes available at 15:00; therefore D's earliest placement is 15:00–17:00. This mistake changes the explanation label, not the validity of the listed schedule.

### 3. Different schedules can both be optimal

In validation-01, v3 places Accelerated G at 13:00–14:00 while v4 places it at 10:00–11:00. Both are valid and both finish the project at 16:30. The concurrent H at 10:00–11:00 uses Maya, while G uses Ethan and the GPU; they do not conflict. Grading against one exact reference schedule would wrongly penalize a valid alternative.

### 4. Both versions pass the next problem

The validation-02 answers correctly account for the lunch boundary, the 7-hour working day, and the mandatory October 20 M/N placement. v3 uses a 7.5-hour Standard critical path versus 7 available hours; v4 uses the earliest Standard G finish at 16:00 plus 1.5 hours to reach L. Both arguments are valid. Final answers: [v3](project-scheduling/responses/validation-02-v3.txt), [v4](project-scheduling/responses/validation-02-v4.txt).

## Offline verification

From the repository root, check all seven schedules without credentials or network access:

```bash
python3 case-studies/project-scheduling/scripts/verify.py
```

The script parses task requirements from the stored question text and checks all tasks, durations, prerequisites, person/resource conflicts, effective availability, lunch/day boundaries, 30-minute starts, the M restriction, deadline, and reported reference completion/cost. The effective availability model is manually transcribed in `datasets/reference-constraints.json`; it does not automatically interpret arbitrary change logs.

For a discrete SMT check of the three reference outcomes:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r case-studies/project-scheduling/scripts/requirements-proof.txt
python3 case-studies/project-scheduling/scripts/verify.py --prove
```

With Z3 4.15.4, all seven schedule checks passed. For each of the three problems, Standard was infeasible before the deadline, Accelerated was feasible, and completion earlier than the reference time was infeasible. Accelerated exceeds the Scenario 2 budget in each problem. These checks validate the encoded scheduling constraints; they do not automatically grade natural-language explanations or establish causality for prompt edits.

## Replay in Langfuse

1. Create a chat prompt using a stored JSON artifact's system content and the user message `{{question}}`. Version labels in this case are logical labels; a fresh Langfuse prompt may assign different numeric versions.
2. Create a dataset item using `input` and `expected_output` from one of the three dataset JSON files. The enclosing artifact and its `id` are not the model's user input.
3. Explicitly choose the same exact model and options for each comparison. The historical per-run options cannot be reconstructed fully from chat, so record fresh settings rather than claim an exact replay.
4. Run one experiment at a time and inspect the complete final answer, not only the table preview.
5. Apply the two rubric labels independently and quote the concrete error in a comment. Log execution errors separately and preserve every new attempt.

This publication does not run new paid API calls. The earlier proposed Python repetition runner is excluded because its execution was not established in this session. See Langfuse's [UI experiments](https://langfuse.com/docs/evaluation/experiments/experiments-via-ui) and [SDK experiments](https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk) for platform setup.

## Limitations and decision

There is no pre-registered protocol, blinded independent rater, complete attempt export, certified parameter parity, or repeated sample for each cell. The problems are small synthetic variants; both feasible-budget scenarios require Accelerated and both lower-budget scenarios are infeasible. A broader suite should also contain zero-cost feasible and all-methods-infeasible cases. The assistant helped create problems, review answers, and prepare this write-up, so manual-label uncertainty and evaluator dependence remain.

The evidence supports “v4 corrected a development example but did not show a consistent advantage on two new problems.” It does not support a general accuracy gain, a model ranking, or a claim that shorter prompts prevent timeouts. Retain v3 as a provisional comparison baseline, keep v4's negative result, and evaluate new error types before adding more instructions.

## 한국어 요약

일정과 판정이 맞아도 설명은 틀릴 수 있었다. v4는 기존 문제의 가용 시간 구간 혼동을 해결했지만, 새로운 문제에서는 일정표와 모순되는 설명을 만들었다. 새 문제 두 개에서 v3의 설명 정확성은 2/2, v4는 1/2였다. 작은 관찰 결과이므로 일반적인 성능 차이를 단정하지 않는다. 이번 사례는 오류에 근거한 프롬프트 수정, 새로운 문제 검증, 결과와 설명의 별도 평가를 기록한다.

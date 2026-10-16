# Evaluate the saved document-review output in Langfuse

This recipe describes the inspected Langfuse v4.63 UI and Python SDK 5.0.1 session.
Labels can change. Both evaluators target **one original root observation**;
they do not evaluate an exported JSON file merely because it exists locally.

## 1. Human annotation

Open the original `terminal-python-document-review` root. Read its question,
candidate decisions, successful retrieved text, answer and claim evidence.

- `task_success`: whether the answer fulfills the question, or appropriately
  abstains when the candidate set cannot establish it.
- `explanation_accuracy`: whether material explanatory statements agree with
  the retrieved evidence and correctly describe execution roles.

Attach an English comment identifying the decisive evidence or error. Use a
generation/tool comment for an issue confined to that step, but keep the overall
answer assessment on the original root. These annotations do not change the
model response. In this case both saved Boolean annotations were True after
assistant-assisted review.

## 2. Python Code evaluator

Create a Code evaluator, choose Python and paste the entire
[`langfuse_code_evaluator.py`](lab/langfuse_code_evaluator.py). Name it
`code_trace_integrity`. It exposes `evaluate(ctx)` and uses the selected
`ctx.observation.input` and `.output`; it is not a command-line script that opens
an exported file. Its standard-library result classes match the runtime result
shape observed in this session.

In the sample filter Builder, use:

```text
Name = terminal-python-document-review
Is Root Observation = true
```

Optionally narrow Environment to `web-search-learning`. Do not require root
Version=2: local prompt version 2 is in root metadata, while the root's Version
field is unset. The evaluator requires the v2 output fields; earlier-schema runs
are unsupported. Select the row whose question is the intended function-calling
question, then run **Run test on this sample**.

Inspect `scores[0].value` and its comment in the evaluator output. A Boolean value
can appear as numeric `1` in an exported execution payload. The original target's
saved code score was independently verified as Boolean True. That does not mean
the code judged every answer sentence or every child span.

## 3. LLM judge

Create LLM-as-a-judge with your configured Grok connection. The observed model was
`grok-4.7`; the saved model parameter snapshot was empty. Create messages using
[`judge-config.json`](evaluators/judge-config.json):

- First message: the English rubric in
  [`explanation_judge.txt`](evaluators/explanation_judge.txt).
- Second message: `Evaluate the following document-review execution.` followed
  by `INPUT: {{input}}` and `OUTPUT: {{output}}` on separate sections.

The observed configuration has two **User** messages. A System rubric and User
data message is a reasonable future revision, but it was not the configuration
that produced the published result. The publication also removes an accidentally
pasted UI instruction from message 2; that cleaned variant was not rerun.

Under **Map variables to data**:

| Prompt variable | Observation field |
|---|---|
| `{{input}}` | Entire original root Input |
| `{{output}}` | Entire original root Output |

The placeholders mark where data will be inserted into the judge's messages.
Mapping chooses the fields; it does not send those fields separately without a
message placeholder. Use the entire Output, which includes retrieved text and
structured evidence, rather than just `answer`.

Select the original root in Matching observations and inspect the variable
previews. Input must contain `question`/`candidates`; Output must contain
`answer`, `claim_evidence` and `read_documents`. If you see an outer
`observation` object and code `scores` as Output, you selected the code evaluator
execution, as happened in the initial wrong-target test.

Name the evaluator `doc_llm_explanation_accuracy`. The observed score setting was
**number between 0 and 1**, with `1` used for the rubric's TRUE judgment. Preserve
that distinction in reporting. The saved advanced score instructions still
contained UI placeholder text; this was a setup exercise, not a fully calibrated
scoring specification. A future version should explicitly define 0 and 1 and
record the revised settings before collecting new results.

Run the sample test and inspect both the score and its written explanation.
The published corrected test returned `1`; no negative semantic calibration test
was run. The root snapshot's validator flags must not substitute for judging
the evidence.

## 4. Sample tests, saved scores and rules

The right-side list selects a **sample** for preview/test. It does not execute
the evaluator on every matching row. Saving an evaluator stores its definition.
Rules separately determine automatic execution on incoming matching observations.
At inspection this LLM evaluator had **zero automatic rules**.

The observed main example had saved human and code scores on the original target;
the LLM result was a separate test execution. To claim a persisted LLM annotation,
apply the evaluator to the intended original observation and confirm the new
score there. Do not interpret the evaluator's own test trace as that attachment.

The environment `langfuse-code-eval` contains code execution records;
`langfuse-llm-as-a-judge` contains judge execution records. The original run is
under `web-search-learning`. Always inspect the target identity and score source
before aggregating them. An execution error remains unscored; it is not False.

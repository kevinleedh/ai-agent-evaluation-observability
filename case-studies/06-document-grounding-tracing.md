# Tracing Document Selection Before Judging the Answer

## What this case establishes

This October 16, 2026 learning session built an inspectable Grok document-review
loop, then evaluated one saved answer with human annotation, deterministic code
and an LLM judge. The runner records which candidates the model selects, what
Python actually retrieves, and which returned passages the model quotes.

For the main function-calling example, saved human annotations are
`task_success=True` and `explanation_accuracy=True`. The saved code score is
`code_trace_integrity=True`. A correctly targeted LLM **sample test** returned
numeric `1` and a written grounding explanation. These results establish that the
workflow ran on this example; they do not establish general evaluator reliability.

The [runnable code](document-grounding/lab/README.md),
[evaluation instructions](document-grounding/EVALUATION.md),
[result excerpts](document-grounding/results/) and
[provenance](document-grounding/PROVENANCE.md) accompany this case. No new paid
model calls were made to prepare the publication.

## Start with the visibility problem

The initial goal was to inspect Grok's web search and understand why it used
particular documents. The first runner enabled the provider's actual
`web_search`, recorded returned search/open-page actions, and retained readable
reasoning summaries when supplied. A citation alone was not treated as evidence
that a search executed. Client-received events also did not reveal the provider's
internal tool timings or a complete explanation for every source choice.

To make selection decisions directly inspectable, the next experiment narrowed
the task: provide four candidate documents and require explicit decisions before
fetching. This is **fixed-candidate document review**, not autonomous web-wide
search. The built-in search runner remains available as a separate companion.
No retrieval-quality comparison between the two systems was performed.

## Build a model-and-Python loop

The question was:

> How does Grok function calling work, and who executes a custom function—the
> model provider or our Python application? Support each claim with an exact quote.

The candidates were official xAI pages for Web Search, Citations, Reasoning and
Function Calling. Initially Grok received only their titles/URLs, the question and
the review instructions. The tools were defined in our code; Grok did not invent
new executable tools during the run.

```text
Question + candidate titles/URLs + review prompt
    -> Grok: review_candidates arguments
    -> Python: validate every select/exclude decision
    -> Grok: read_document ID + reason + information_needed
    -> Python: download selected document; return actual text
    -> Grok: submit_answer claims + source IDs + quotes
    -> Python: validate quote presence; render answer; record root snapshot
```

`reason` and `information_needed` are model-declared action justifications.
They are useful evaluation data, not access to hidden internal reasoning or proof
that those statements caused the selection. An exclusion before reading is a
title/URL relevance judgment, not a finding about the excluded document's contents.

In the main example, Grok excluded the first three candidates, selected Function
Calling and requested its execution flow and execution ownership. Python fetched
the Markdown document, returned 14,176 text characters without truncation, and
Grok submitted three claims with four quotes. The raw trace had seven observations:

| Observation | Meaning in this run |
|---|---|
| `terminal-python-document-review` | Root snapshot of the complete application run |
| `grok-document-selection / 1` | Model requests the candidate review |
| `candidate-review` | Python validates and records the decisions |
| `grok-document-selection / 2` | Model requests the selected document |
| `read-document` | Python retrieves and returns document text |
| `grok-document-selection / 3` | Model submits evidence-linked claims |
| `claim-evidence` | Python validates quotes and produces the accepted result |

The numbered generations are calls to the same configured model, not separate
models. Their sequence can change when reads fail, multiple documents are needed
or submissions require correction. The saved metadata links calls 2 and 3 to the
prior provider response with `previous_response_id`; all earlier messages need
not be repeated in the visible input of each generation. The response-link
matches were verified in the [structure export](document-grounding/results/trace-structure.json).

The model reads the text delivered in the tool response. Python performs the
network fetch and exposes that text; Grok does not need to operate a separate
browser to analyze it. Conversely, a model tool-call request alone does not prove
that Python fetched a page. The successful `read-document` output supplies that
execution evidence.

## Separate three evaluation questions

| Method | Criterion | Observed main-example result |
|---|---|---|
| Human review | Does the answer address the task? Is its explanation accurate? | Both Boolean annotations True |
| Code assertion | Are required snapshot structures, source references and quote matches consistent? | Boolean True |
| LLM judge | Are material answer statements supported by the supplied document text? | Numeric 1 in the sample test |

These are complementary checks, not three independent votes on an identical
definition of correctness. Human annotations followed assistant-assisted review;
they are not blinded labels from independent reviewers.

### Human review

The human review considered both parts of the question: the function-calling
sequence and who executes custom functions. The answer described the model
requesting a call, the application executing it and returning the result, and
the model continuing. It also distinguished custom tools from provider-hosted
built-in tools in the supplied documentation snapshot.

The [saved score excerpt](document-grounding/results/saved-scores.json) was checked
through the Langfuse Scores API before publication. It includes the two
`ANNOTATION` scores and an `EVAL` code score. The code score retains its execution comment; the human rows have no score
comment. Suggested chat comments are not presented as saved human comments.

### Code assertion

The standalone [hosted evaluator](document-grounding/lab/langfuse_code_evaluator.py)
reads the selected root observation's Input and Output. It checks candidate
decision coverage, required reasons, selected/read source consistency, final
status, nonempty claims/evidence, quote presence and matching source URLs.
Execution failure is unscored rather than labeled as an incorrect answer.

Its completed test reported:

> Root snapshot checks passed: 4 decisions, 1 reads, 3 claims, 4 quotes checked.
> Status: answered. Semantic support and sibling tool execution records were not
> evaluated.

This is deliberately a snapshot consistency checker. It does not independently
reconstruct every sibling tool execution, prove that a reason is relevant, judge
whether the text entails the claim, or validate every requirement enforced by
the runner. For example, the runner imposes claim/quote length limits that this
hosted evaluator does not independently repeat. The metric name
`code_trace_integrity` should be read within that limited scope.

The [offline regression tests](document-grounding/lab/test_hosted_evaluator.py)
reject deliberately missing/duplicate candidate decisions, missing declared
information, invented quotes, unread sources, empty evidence and a wrong URL.
Another test changes a claim to say that the provider executes every custom
function while preserving real quotes. The code still passes. This is an
expected demonstration that substring matching does not establish semantic truth;
it is not a newly observed bad Grok answer or an LLM-judge test.

An additional saved weather question led the model to exclude all four candidates
and abstain without reading documents or submitting claims. Its zero-quote
structural pass is not verification of a weather forecast. The
[abstention fixture](document-grounding/fixtures/weather-abstention.json)
preserves this distinction.

### LLM-as-a-judge

The [judge rubric](document-grounding/evaluators/explanation_judge.txt) checks
material factual support using both linked quotes and the full retrieved text.
It ignores self-reported validation flags. `claim_support_evaluated=false` means
the earlier code did not grade semantics; it is not an incorrectness score.

The observed configuration used `grok-4.7`, mapped the root Input to `{{input}}`
and the entire root Output to `{{output}}`, and returned a **numeric 0–1 score**.
Although the rubric says TRUE/FALSE, the actual saved output definition was
NUMERIC and the test returned `1`. That number is not a calibrated probability
or independent proof of truth. The generator and judge used the same model name.

The judge's explanation says c1–c3 are materially supported, including
the documented call sequence and custom-versus-built-in execution distinction.
It also notes that the answer body links the page rather than embedding exact
quotes, while the structured evidence contains them. See the complete
[judge result](document-grounding/results/judge-test.json).

This rubric permits support found elsewhere in the supplied document when a
claim's own short quote is incomplete. For example, c1's continuation clause has
clear support in the documented flow, though not in every sentence of c1's
linked opening quote. Passing this rubric does not mean every individual quote
independently supports every clause, nor that answer completeness was graded.
A stricter per-claim citation rubric would be a separate evaluation.

The evaluated observation was `terminal-python-document-review`. Its mapped
variables contained the original question/candidates and answer/claims/retrieved
text. The target trace and observation IDs were checked against the original
export through Langfuse's API before identifiers were removed from public files.
The observed message configuration and publication edits are recorded in
[provenance](document-grounding/PROVENANCE.md).

## What remains unproven

The LLM result is a sample test. At inspection, its evaluator had no automatic
rule assignments and no LLM score was present among the original target's saved
scores. Testing a selected row does not grade every trace in the table, and the
Input/Output variable mapping does not automatically supply sibling observations.

The publication includes 30 passing offline tests: 18 existing runner/recorder
tests and 12 added hosted-evaluator tests. Those checks do not recreate the live
LLM judgment. No semantically incorrect example has yet been run through this
document-review judge as a negative calibration case. A next study should freeze
the mapping/rubric and test human-reviewed positives and negatives, including
wrong execution roles, unsupported claims, incomplete answers and appropriate
abstentions, while preserving failures and disagreements.

Public fixtures contain source excerpts instead of complete third-party pages,
and account/request identifiers are omitted. The live judge received the full
document. Replaying current URLs can produce different text or model responses;
these results describe the inspected session rather than a general benchmark.

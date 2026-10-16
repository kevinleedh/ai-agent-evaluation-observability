# Tracing Tavily Web Search and Evaluating the Answer

## Outcome

I extended [case 06's fixed-candidate document reviewer](06-document-grounding-tracing.md)
into a bounded web-search agent. Grok writes the search query, chooses documents
from Tavily's results, requests their contents and submits claims with exact quotes.
Python executes the tools and sends the execution records to Langfuse.

The session then tested two evaluators: a Python Code evaluator returned Boolean
**True** for snapshot consistency and quote checks, and an LLM judge returned
Boolean **True** for answer grounding. These are completed sample tests on a small
learning example, not evidence that either evaluator is generally reliable.

[Code and replay instructions](tavily-web-search/lab/README.md) ·
[Evaluator setup](tavily-web-search/EVALUATION.md) ·
[Results](tavily-web-search/results/) ·
[Provenance](tavily-web-search/PROVENANCE.md)

## What changed from fixed document review

Previously, four document titles and URLs were supplied before the first model
call. Here, the model first creates a query and our Python wrapper calls Tavily
Search. The returned results become the candidate list. The model reviews titles,
URLs and search snippets before requesting selected pages through Tavily Extract.

| Responsibility | Component |
|---|---|
| Search query, declared reasons, candidate decisions and quoted claims | Grok |
| Search results and extracted page text | Tavily Search and Extract |
| Tool schemas, execution, phase/budget enforcement and quote validation | Python |
| Stored model/tool records, evaluator definitions and sample-test views | Langfuse |

The custom tools are defined in our code. Grok supplies function-call arguments;
Python performs the corresponding API calls. The declared search/selection reasons
are inspectable justifications, not disclosures of hidden internal reasoning.

## Follow one question through the tools

The question was:

> Using official xAI documentation, explain how Grok function calling works and
> who executes custom functions: the model provider or our Python application.
> Use at most three claims, each with an exact supporting quote.

Grok generated this query:

```text
Grok function calling official xAI documentation who executes custom functions
```

Tavily returned five candidates. The model selected Tools Overview and Function
Calling on the official documentation domain. It excluded a YouTube result,
Google Cloud partner documentation and a Grok Build announcement, citing the
question's official-source requirement or the different topic. These are the
model's declared decisions, not verified findings about unread full pages.

Both selected extractions succeeded. The Function Calling result contained 22,753
characters and Tools Overview contained 7,856; neither was truncated by our text
cap. Extraction output is the available evidence, not proof that the entire
original web page was recovered.

The trace had ten observations and four model calls:

```text
terminal-tavily-web-search
  grok-tavily-agent / 1     -> search_web
  tavily-search            -> five candidates
  grok-tavily-agent / 2     -> review_candidates
  candidate-review         -> select two, exclude three
  grok-tavily-agent / 3     -> two read_document requests
  tavily-extract           -> Function Calling text
  tavily-extract           -> Tools Overview text
  grok-tavily-agent / 4     -> submit_answer
  claim-evidence           -> three claims and three quote checks
```

The third model call requested two reads; Python executed two separate extraction
calls. Numbered generations count model calls, not documents. Continuations use
`previous_response_id`; the model receives new tool results while the provider
links the earlier context. The response links were checked in both inspected runs.

The answer states that custom function calls are requested by the model and
executed by the caller, describes the five-step function-calling loop, and
distinguishes custom tools from provider-hosted built-in tools. All three final
quotes came from Function Calling. Reading Tools Overview did not require citing
it, and its unused extraction is visible for future efficiency analysis.

Two executions of this same question are preserved as sanitized
[connection-check](tavily-web-search/fixtures/connection-check.json) and
[user-replay](tavily-web-search/fixtures/user-replay.json) fixtures. They have the
same query, candidate URLs and counts, with different claim wording/IDs. The LLM
test's target was verified against the user-replay root and its full Input/Output.
These are repeated observations of one question, not independent evaluation cases.

## Make the execution boundaries explicit

The first lesson allows one search attempt, at most five returned candidates,
two extraction attempts and ten model calls. Search and extraction failures consume
their budgets; there are no automatic SDK/HTTP retries or hidden direct-fetch
fallbacks. Every candidate needs one select/exclude decision. Reads must use
selected IDs from the current search rather than an invented URL.

The Search request sets `include_answer=False` so Tavily's generated answer is not
used, and `include_raw_content=False` so page extraction remains a separate step.
Images and automatic parameter selection are disabled; usage reporting is enabled.
These Boolean fields are request options, not quality judgments. A returned
`retrieval_score` is also not an answer-correctness score.

Only nonempty successful Extract results become quote evidence. HTTP 200 alone
is insufficient because Extract can report failed URLs in its response. Python
bounds response sizes, validates result URLs and passes at most 24,000 text
characters per successful read. Search snippets remain selection context and
cannot replace a successful page read for final quotations. See the official
[Search](https://docs.tavily.com/documentation/api-reference/endpoint/search) and
[Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract)
interfaces used by the wrapper.

## Evaluate with code assertions

The hosted evaluator is
[`code_tavily_trace_integrity`](tavily-web-search/lab/langfuse_tavily_code_evaluator.py).
It reads the original root's Input and Output through `evaluate(ctx)` and checks:

- Search query/reason/intended information and configured search/result budgets.
- Candidate snapshot consistency, IDs and exactly one decision per candidate.
- Selected/read source membership, read reasons, extraction URLs and attempt counts.
- Final status, claim IDs, evidence presence, quote length and source URL agreement.
- Whitespace-normalized quote matches in successfully read text.
- Agreement between the rendered answer and the accepted claims/source links.

An empty result set can validly lead to abstention. A failed unused extraction does
not invalidate independent successful evidence; a quote from that failed source
does fail. Unsupported targets and execution/search failures are unscored errors,
not incorrect-answer labels.

The user's hosted sample-test screenshot reports **True** with this comment:

> Root snapshot checks passed: 5 candidates, 5 decisions, 2 read attempts, 3 claims,
> 3 quotes. Status: answered. Semantic support, model-call count, action order and
> sibling execution records were not evaluated.

The current saved code was exported from Langfuse and replayed locally against
both original root snapshots and both public excerpt fixtures; all returned True.
The hosted screenshot's sample target IDs were not exported, so its verdict is
reported separately from those identified local replays.

This evaluator checks a root snapshot. It does not independently prove that each
API call happened, reconstruct sibling spans, verify action order or count model
calls. Those properties can be inspected in the complete trace. `True` is not a
claim about the answer's semantic truth.

The offline suite includes 25 deliberately corrupted checker inputs, such as a
missing decision, an invented quote, a failed/unread cited source and a changed
rendered answer. Each returned False as expected. A separate test gives a false
claim a real quote and keeps the rendered answer consistent; code still returns
True. That expected pass demonstrates why semantic judgment is a separate step.

## Evaluate grounding with an LLM judge

The saved evaluator `llm_tavily_answer_grounding` uses
[this System rubric](tavily-web-search/evaluators/answer_grounding_system.txt),
the original Input and the **entire Output**, including successful extracted text.
It checks central-question coverage, material factual support, source attribution,
execution roles and appropriate abstention. It ignores prior scores and
self-reported validation flags. It does not separately grade search-query quality,
search efficiency or whether a better source might exist.

The observed model was `grok-4.7`, with a Boolean score definition. The test returned
**True**. Its explanation specifically connects all three claims to the official
function-calling page: the caller executes the model's requested call locally,
the page lists the five-step loop, and custom tools return to the caller while
built-in tools run on provider servers. It also accepts the Python SDK examples
and the answer's limited wording about a specific Python process. The
[complete result](tavily-web-search/results/judge-test.json) preserves that explanation.

The rubric allows surrounding text in the same cited, successfully read document
to complete an abbreviated quote's support. Structured evidence quotes count even
when the answer body only displays links. It is therefore a full-document-grounding
criterion, not a strict test that each short quotation alone proves every clause.

The generator and judge use the same model name. No semantically negative example
has yet been run through this Tavily judge; the false-claim test above exercises
only the deterministic checker. One positive judgment is not a measured judge
accuracy or evidence of robust error detection.

## Preserve what the results mean

| Evidence | Observed result | Interpretation |
|---|---|---|
| Search/extraction trace | Five results, two successful reads, three quoted claims | Bounded tool workflow completed |
| Hosted Code sample test | Boolean True | Root snapshot consistency checks passed |
| Local saved-code replays | True on both recorded runs | Reproducible deterministic checks on identified snapshots |
| LLM sample test on user replay | Boolean True, with written explanation | Model judged this answer grounded in the supplied text |
| Original-target saved scores at inspection | Empty for both runs | Sample-test results were not persisted as target scores |

Both evaluator definitions were saved, but neither had an automatic rule assignment
at inspection. This case does not report a new formal Human Judge label. It builds
on the prior learning workflow while recording Code and LLM sample tests here.

The [23 offline tests](tavily-web-search/results/offline-validation.json) cover
Tavily/SDK behavior and the saved hosted checker, including the 25 negative
subcases. They do not recreate the LLM judgment. Public fixtures retain the answer,
decisions and quotes but shorten snippets and extracted bodies; the live judge
received full returned text. Credentials, account identifiers and raw screenshots
are excluded. Current search results and source pages may change on replay.

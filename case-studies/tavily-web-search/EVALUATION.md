# Evaluate the Tavily root snapshot in Langfuse

These instructions describe the inspected Langfuse v4.63 UI and SDK 5.0.1 session.
They target `terminal-tavily-web-search` rather than the fixed-document reviewer
from case 06. Dynamic candidates are in root Output, not initial Input.

## Code Assertion

Create a Python Code evaluator named `code_tavily_trace_integrity`. Paste the
entire [exported source](lab/langfuse_tavily_code_evaluator.py), including its
standard-library result classes and `evaluate(ctx)` function. It does not open a
local JSON export or call Tavily/Langfuse over the network.

Use the sample filters:

```text
Name = terminal-tavily-web-search
Is Root Observation = true
Environment = tavily-search-learning
```

Select a completed original root and run **Run test on this sample**. The code
reads `ctx.observation.input` and `.output`; no variable-mapping step is required.
Input must contain the original question/budgets. Output must contain the search
result, dynamic candidates, candidate review, reads, claims and attempt counts.

The checks cover recorded budgets, candidate coverage and IDs, selected/read source
consistency, successful quote evidence, quote length/presence, final status and
agreement between the rendered answer and accepted claims/links. Self-reported
validation flags are ignored. A failed unused read is permitted; citing it is not.
Execution/search failure and unsupported input are unscored evaluator errors.

The sample screenshot returned Boolean True with counts 5/5/2/3/3 for
candidates/decisions/read attempts/claims/quotes. Read the comment to understand
what passed. The checker does not independently fetch sibling tool observations,
count model calls or verify action order, and it does not judge semantic support.

Save the evaluator with **Create evaluator**. A saved definition, a completed
sample test and a score persisted on the original root are separate states.

## LLM Judge

Create LLM-as-a-judge named `llm_tavily_answer_grounding` with the model available
in your configured connection. The observed judge was `grok-4.7`; its per-call
model-parameter snapshot was empty. Set Score output to **Boolean**.

Use the exact saved messages:

- System: [answer_grounding_system.txt](evaluators/answer_grounding_system.txt)
- User: [answer_grounding_user.txt](evaluators/answer_grounding_user.txt)

The saved User template was the UI's short wrapper:

```text
Evaluate the quality of the response.

Input: {{input}}
Response: {{output}}
```

The detailed System rubric defines the criterion. It uses successful extracted
text to evaluate the answer/claims/limitations, central-question coverage,
attribution and execution roles. It allows supporting surrounding context in the
same cited document and does not independently score query quality or efficiency.
Search snippets and failed reads cannot substitute for final page evidence.

Map `{{input}}` to the original root's entire Input and `{{output}}` to its entire
Output. Keep full `read_documents` and `claim_evidence`, not only the answer text.
Inspect the preview, then run the sample test. The published result was Boolean
True; its target IDs and full supplied Input/Output were verified against the
user-replay root before redaction.

The complete [saved configuration](evaluators/judge-config.json) also preserves
the default advanced score-instruction fields for fidelity. The System rubric
provides the substantive criteria; this remains a learning configuration rather
than a calibrated scoring model. A semantic negative case has not yet been tested.

## Tests and persisted scores

At inspection both evaluator definitions were saved and active, with **zero
automatic rule assignments**. Original-target score queries returned empty lists
for both inspected runs. The sample tests above are the observed evaluation
results; this publication does not claim that those tests attached scores to the
original roots or graded every matching row.

To persist scores, separately apply the saved evaluators to the intended original
observations and confirm their names, Boolean values and comments in Scores or
the target observation. Only attach an automatic rule after choosing the intended
scope. Code and LLM test/execution records are separate from the answer itself.

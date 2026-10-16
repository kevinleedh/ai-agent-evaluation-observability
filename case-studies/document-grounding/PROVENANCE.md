# Provenance and publication boundaries

This case records the October 16, 2026 tracing/evaluation learning session.
Publication preparation performed read-only Langfuse inspection and offline tests;
it did not generate new paid model answers or judge calls.

## Sources

- The document-review root and child structure come from the user's exported
  function-calling trace: seven observations, four candidate decisions, one
  successful 14,176-character read, three claims and four quote checks. A second
  user export supplies the weather abstention example. Raw exports are not included.
- The hosted code test comes from the user's code-evaluator execution export.
  The result comment is preserved. The published checker is the authored session
  source with clarified v2-schema selection wording; its evaluation logic is
  unchanged. It does not independently inspect sibling tool observations.
- The LLM test appeared in the user's completed-test screenshot and was
  subsequently retrieved through the Langfuse Observations API. Its target trace
  and observation IDs matched the original root before redaction. The result
  explanation is preserved verbatim in `results/judge-test.json`.
- The saved evaluator configuration was read from the Langfuse Evaluators API.
  It has two User messages, model `grok-4.7`, Input/Output mappings, a NUMERIC 0–1
  output definition and no rule assignments. Its advanced score-instruction fields
  retain placeholder text. A Boolean rubric was discussed, but the actual saved
  configuration and result are reported rather than silently relabeled.
- `results/saved-scores.json` was read from the original root's Langfuse Scores
  API response during publication: `task_success=True` and
  `explanation_accuracy=True` have source `ANNOTATION`; `code_trace_integrity=True`
  has source `EVAL`. No LLM score was present in that response. The annotations
  followed assistant-assisted review; they are not blinded independent labels.
- The managed search prompt and one-item dataset were exported through the SDK
  into `lab/builtin-managed-setup.json`. Their review reference is session-authored
  setup material, not an independently established gold-standard dataset.

## Changes made for publication

- Code was copied from the session lab using an explicit file allowlist.
  Personal Python paths in macOS launchers now use the adjacent `.venv`.
  One mock stream test's Korean sample strings were replaced with English.
- `.env.example` contains empty placeholders. No credentials, raw account metadata,
  trace/observation/provider-response IDs, account names or screenshots are included.
- Public root fixtures keep the original question, candidates, decisions, answer,
  limitations and claim-to-quote mappings. Retrieved document text is replaced by
  the linked quote excerpts. Their `_publication` fields identify this change and
  preserve original character counts. The public excerpt's `truncated` field is
  set True; the original main read was not truncated.
- The LLM judge used the **full original retrieved document**, not the public
  excerpt fixture. The public fixture cannot replay that full-context judgment
  byte for byte. It supports inspection and deterministic regression checks.
- The exported English judge rubric is unchanged. `judge-config.json` removes
  one accidentally pasted Korean UI-helper sentence from the second message.
  The cleaned message configuration was not rerun; observed roles, mappings,
  model, output definition and advanced settings are retained.
- Twelve hosted-evaluator tests were added for publication. Existing runner tests
  are retained. Synthetic bad copies are checker tests, not historic model outputs
  or observed LLM-judge calibration results.

## Limits

The selected runs are not a representative benchmark. Code substring checks,
human task/explanation labels and a full-text-grounding LLM score measure different
things. One positive LLM test does not establish error-detection reliability.
No semantically negative example has been run through this document-review judge.
No automatic LLM rule, end-to-end batch evaluation or complete historical failure
denominator is established. The generator and judge share the same model name.

The Python runner's `--question` option submits one question; interactive `input()`
submits one line at a time. A separate inspected run contained only formatting
instructions because multiline input had been split. It is not labeled as a
failure to answer a topical question absent from its actual Input, and is omitted
from this focused example set.

Source passages, including the provider naming in the function-calling snapshot,
are historical evidence from the returned text. No claim is made that current
documentation or model availability is unchanged. The source URLs are preserved;
full third-party documentation bodies and private operational metadata are not.

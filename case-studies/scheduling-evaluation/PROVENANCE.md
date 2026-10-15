# Provenance and replay boundaries

This follow-up records the October 15, 2026 evaluation-learning session. It reuses
case 04's synthetic datasets and saved final answers; it is not a new generation
benchmark. No additional paid model calls are made to prepare this publication.

- Python evaluator sources are the authored session files. The integrated
  validation-02 evaluator and coverage self-test were saved and executed in
  Langfuse by the assistant. The user pasted the duration evaluators into Langfuse;
  their result names/values were visible in the supplied screenshots. The published
  duration sources are the corrected code supplied in chat, not API exports.
- `explanation_judge.txt` is the evaluator instruction supplied in chat. The
  validation-01 execution screenshot shows the same evaluation criteria. It is not
  an independent export of every saved evaluator version. The mappings were Input
  -> `{{input}}` and Output -> `{{output}}`; scores use Boolean values.
- The two validation-02 judge comments were read in full from the live Langfuse
  Scores table. They are transcribed verbatim in `results/judge-results.json`.
- The validation-01/v4 failure explanation and 57.15-second duration were
  transcribed from the user's final completed-execution screenshot. No machine
  export accompanies that result. It is not inferred from a previous timeout.
- `grok-4.7` was visible for the judge's completed executions. Full parameter
  snapshots, provider usage/cost exports, request IDs and repeated-run distributions
  are not preserved. A reduced reasoning effort was discussed, but the final
  applied setting was not verified. No claim about a speed improvement is made.
- Human explanation labels are the prior assistant-assisted reviews from case 04,
  not new blinded annotations. On validation-02 they were also visible as saved
  UI labels. On validation-01/v4 the UI displayed explanation_accuracy=False.
- Only selected attempts are documented. Timeout entries are operational evidence,
  not incorrect explanation scores and not a complete failure-rate denominator.
- The local regression tests execute the same deterministic code without Langfuse
  credentials. They do not simulate the LLM judge or prove deployment equivalence
  for every historic evaluator version.

Account names, email addresses, project/trace/observation IDs, local absolute paths,
keys, browser screenshots and hidden reasoning text are excluded from publication.
The result comments contain synthetic scheduling information only.

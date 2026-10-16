# AI Evals and Error Analysis

Small, inspectable case studies of model behavior, evaluation criteria, and error analysis. Each case separates observed evidence from conclusions and limitations.

## Case studies

1. [When a Zero Reward Does Not Mean the Agent Failed](case-studies/01-evaluator-induced-db-mismatch.md)
2. [Policy-Compliant Handoff](case-studies/02-policy-compliant-handoff.md)
3. [Email Triage and Reply Priority](case-studies/03-email-triage-reply-priority.md)
4. [Prompt Changes Can Fix One Explanation and Fail on a New Case](case-studies/04-prompt-iteration-scheduling.md) — four prompt versions, three synthetic scheduling problems, seven completed answers, and separate outcome/explanation labels.
5. [From Human Review to Code Assertions and an LLM Judge](case-studies/05-human-code-llm-evaluation.md) — reuse saved answers, test deterministic checks with deliberate errors, and inspect judge agreement on two positive explanations and one negative explanation.
6. [Tracing Document Selection Before Judging the Answer](case-studies/06-document-grounding-tracing.md) — trace fixed-candidate selection, Python document retrieval and quote submission; separate saved human/code scores from an LLM sample test and diagnose a wrong-target evaluation.

The scheduling case includes original final-answer text, JSON prompt/data artifacts, manual grading evidence, and an offline schedule verifier. It does not establish a general model ranking or a statistically reliable improvement from prompt changes.

The evaluation follow-up publishes standalone Langfuse Python evaluators, regression tests, a judge prompt, and selected sanitized score comments. It distinguishes answer-quality scores, synthetic checker tests, execution errors, and unscored explanation semantics.

The document-grounding case includes runnable tracing code, prompts, sanitized excerpt fixtures, a hosted code evaluator and its tests, an exported judge configuration, and observed results. Its one positive judge test demonstrates setup, not general evaluation reliability or autonomous web-search quality.

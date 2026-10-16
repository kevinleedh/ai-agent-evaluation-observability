# Document grounding artifacts

Start with the [case study](../06-document-grounding-tracing.md). This bundle
preserves the implementation, evaluation setup, selected evidence and limitations
of the October 16, 2026 session.

| Location | Contents |
|---|---|
| [lab/](lab/README.md) | Grok/Python document reviewer, built-in search recorders, tool schemas, local prompt, settings, launchers and pinned dependencies |
| [lab/langfuse_code_evaluator.py](lab/langfuse_code_evaluator.py) | Standalone hosted Python root-snapshot checker |
| [evaluators/](evaluators/) | English LLM rubric and cleaned export of the observed judge configuration |
| [fixtures/](fixtures/) | Original answer/decisions/claims with excerpted source text; positive answer and abstention |
| [results/](results/) | Saved score excerpts, code test, corrected LLM test, initial mapping error and trace structure |
| [EVALUATION.md](EVALUATION.md) | Human, Code and LLM setup and target/mapping checks inside Langfuse |
| [PROVENANCE.md](PROVENANCE.md) | What was exported, inspected, authored or changed for publication |

The 30 offline tests cover the runner/recorders and deterministic checker. They
do not reproduce the LLM score. The one corrected positive judge test establishes
setup on that example; semantic negative calibration remains future work.

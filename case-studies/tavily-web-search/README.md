# Tavily web search artifacts

Read the [case study](../07-tavily-web-search-evaluation.md) for the execution and
evaluation results. This is a bounded search-and-read learning workflow.

| Location | Contents |
|---|---|
| [lab/](lab/README.md) | Runnable terminal agent, Tavily backend, tool schemas, prompt, settings, launcher and offline tests |
| [lab/langfuse_tavily_code_evaluator.py](lab/langfuse_tavily_code_evaluator.py) | Exact exported source of the saved hosted Code evaluator |
| [evaluators/](evaluators/) | Exported Code/Judge configuration and actual System/User judge messages |
| [fixtures/](fixtures/) | Two sanitized root snapshots with excerpted source content |
| [results/](results/) | Trace summaries, Code results, LLM result and score persistence status |
| [EVALUATION.md](EVALUATION.md) | Setup and interpretation of the Code and LLM evaluators |
| [PROVENANCE.md](PROVENANCE.md) | Evidence sources, publication changes and replay limits |

Code and LLM sample tests returned True on the selected example. The original
targets had no saved scores and both evaluators had no automatic rules at inspection.
Twenty-three offline tests pass; they are not a semantic judge reliability study.

# Artifact provenance

Prepared on October 15, 2026 from the current evaluation-learning conversation, with the user's authorization to publish its prompts, datasets, final answers, and analysis. No new model generations were performed for this publication.

| Material | Source and fidelity |
|---|---|
| `prompts/v1.json`–`v3.json` | System text pasted by the user, wrapped in Chat Prompt JSON with the documented `{{question}}` user message |
| `prompts/v4.json` | v3 plus the exact two additional instruction sentences proposed in chat and visible in the later Langfuse screenshot; reconstructed artifact, not a prompt API export |
| `datasets/development.json` | The user-input section of the user's pasted Kimi trace; UI labels, assistant content, and reasoning text excluded. The reference output is normalized from the agreed ground truth |
| `datasets/validation-01.json` | Semantically normalized reconstruction of the assistant-authored new problem. Reuses baseline prose and applies the documented changes: G Standard 2 h, Accelerated 1 h/cost 4, M earliest 15:30, budgets 4/3, unapproved free outsourcing proposal. Layout and scenario wording are not certified byte-identical to the Langfuse input |
| `datasets/validation-02.json` | Problem text supplied in chat, with the user-reported answers preserved separately |
| `datasets/reference-constraints.json` | Effective availability, method alternatives, budgets, M restriction, and deadline manually transcribed for offline verification; task rows are parsed from each stored input |
| `responses/*.txt` | Seven user-pasted final answers; version labels removed from the enclosing chat and line breaks normalized. These are final-answer transcriptions, not raw provider response objects |
| `results/annotations.json` | Retrospective assistant-assisted review, discussed with the user; not a Langfuse score export and not independently blinded annotation |
| `results/operational-observations.json` | Selected screenshot/chat diagnostics only; no exhaustive attempt count or runtime denominator |

## Configuration uncertainty

The seven completed answer comparisons were discussed as Grok experiments. Earlier setup messages described Grok 4.7 and `reasoning_effort=low`, but no complete per-run configuration exports accompany these seven final answers. An advanced-settings screenshot later showed Additional options enabled with `{}` and Temperature, Top P, and Output token limit disabled. Therefore exact model identifiers, option parity, provider defaults, per-answer latency, and costs are left unknown in the result records. Instructions to keep settings fixed are not proof that the settings were actually identical.

The Kimi runs and their execution errors are a separate learning phase. Their observations must not be pooled with Grok final-answer quality results to infer a prompt effect.

## Scope and privacy

Only the requested synthetic task artifacts and relevant final-answer evidence are included. Full chat logs, screenshots, account/project identifiers, API keys, local paths, unrelated browser content, and exposed model reasoning sections are not published.

The source set is incomplete and retrospectively selected. Missing evidence is recorded as unknown rather than inferred. The manifest gives hashes for the publication files; it does not establish that reconstructed inputs were the exact historical requests.

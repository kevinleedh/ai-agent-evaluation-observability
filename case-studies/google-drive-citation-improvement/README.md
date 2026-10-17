# Google Drive citation improvement

This package supports [case 08](../08-google-drive-citation-improvement.md).
It contains a working Drive MCP client, the original synthetic files, frozen
evidence cases, answer prompts, evaluation code, and sanitized recorded results.

- [Start and replay instructions](lab/README.md)
- [Evaluation definitions and experiment history](EVALUATION.md)
- [Publication provenance](PROVENANCE.md)
- [Final 42-answer comparison](results/citation-coverage-v2.json)
- [Two final baseline failures and candidate examples](results/final-failure-examples.json)
- [Historical role-citation defect and a new correct citation](results/role-citation-example.json)
- [Files originally uploaded to Google Drive](fixtures/upload-to-drive/)

The final comparison reports attached-quote support **19/21 → 21/21**, with
requested-fact success **21/21 → 21/21**. Its baseline already contains the first
citation-coverage instruction; only the relevance/no-filler block differs.
The saved Drive evidence is fixed during answer generation. Replaying this
comparison makes new model calls, but no new Drive requests.

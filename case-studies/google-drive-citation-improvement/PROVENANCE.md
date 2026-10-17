# Provenance and publication scope

## What was actually executed

The learning session used a personal Google Drive folder containing five synthetic
English text files, Grok through xAI's API, an existing Pipedream MCP connection,
a local Python client, and Langfuse. Eight live run snapshots were saved. Two
successful snapshots had recording readback checks. The application did not build
an MCP server or inspect provider-internal distributed traces.

After inspecting these runs, the session generated 30 partial-answer outputs,
42 citation-revision-1 outputs and 42 citation-revision-2 outputs. The initial
30 outputs were later re-scored without changing their answer text. The two
citation preflight reports have no A/B answer records. Reference repairs were
assistant-constructed controls, not generated comparison outputs.

`PUBLICATION.json` records private source-report filenames/hashes and the source
and published hashes of adapted Python files. These hashes identify provenance;
private payloads cannot be reconstructed or independently verified from a hash.

## What is preserved

- Full original bytes of the five fictional source documents.
- Frozen candidate metadata, selection decisions, successful full text and failed
  read statuses. Controlled failures are labeled in their records.
- All recorded submissions and judge decisions in the completed comparisons,
  including unsuccessful variants and disputed flags.
- Initial and corrected partial-answer judge results, and unsuccessful citation
  reference preflights.
- Frozen baseline/candidate/judge prompts, settings, manifests and local promotion
  record.
- Client, orchestration, experiment, reporting and test code.

The public role example pairs a historical failing answer with a new model output
under a different explicit role question. It is illustrative, not a matched A/B
measurement. Its reference-check repair is separately labeled. The final two
failure examples are independent generated outputs at matching case/trial indices;
they are not manual answer edits or shared-seed pairs.

## What changed for publication

Real Drive file IDs and links were replaced consistently with stable aliases and
`example.invalid` URLs. The folder ID, private local path, Langfuse account/trace
links and source-trace associations were removed or replaced. Evidence bodies,
claim/quote wording and judge decisions were not rewritten. Dataset and input
hashes were recomputed for the public aliases. Byte and text checksums remain
valid because source document bodies were not modified.

Raw MCP payloads, OAuth storage, `.env`, signed file-resource URLs and screenshots
are excluded. Public live snapshots retain the parsed listing and full verified
text, not a raw MCP export. Stored readback results describe checks performed on
private traces; public readers can inspect the report but cannot repeat the
original remote readback without private trace access.

The exported client loads credentials from its own `.env` or environment instead
of an adjacent private lab. Experiment dataset names use a `portfolio-` prefix so
public aliased data does not overwrite the original hosted datasets. Fixture
verification uses the bundled fixture directory, and report commands use the
current lab path. Unicode test strings use escape sequences. These portability changes do not modify answer-generation or grading
rules, but the exported code is explicitly an adapted copy.

Historical preparation requires original private run files and is not the public
replay path. Use the supplied frozen datasets to run new comparisons. Original
Langfuse links were omitted; public evidence is the saved sanitized data, not a
claim that readers have access to the private project.

## Limits of the conclusion

This is a small exploratory synthetic-document study. It has no independent
held-out set, independently adjudicated human label set, or model-training step.
The same Grok alias generated and judged answers. Repeated case trials are not
independent projects, and the counts are not a production accuracy estimate.
The final 19/21 → 21/21 comparison isolates the relevance rule added to an already
citation-aware prompt. It does not establish a measured role-probe improvement,
full-agent improvement, or increased live Drive reliability.

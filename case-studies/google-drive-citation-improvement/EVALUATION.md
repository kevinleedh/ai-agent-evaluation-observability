# Evaluation contract and experiment history

## Independent checks

| Check | Input | Pass means | Does not establish |
|---|---|---|---|
| Code evidence integrity | Submission and frozen read records | Valid claim structure/IDs, successful source reads, quote lengths and normalized substring matches | Semantic support, completeness, or action order |
| Attached-quote support | Each claim and its own quotations, interpreted with supplied evidence | All emitted claims are supported by their attached quotes | That all requested supported facts were answered |
| Grounding | Claims, limitations, successful bodies, metadata and read statuses | Claims pass quote support and factual limitations are supported | That missing requested answers were supplied |
| Task success | Question, successful reads, action records, reference criteria and submission | Every available requested fact is correct in claims; unknown portions are explicitly unresolved | That each attached quotation is sufficient |
| Combined study pass | Code, grounding and task judgments | All three checks pass | Production accuracy or independent human agreement |

The deterministic implementation is `lab/document_audit.py::validate_answer`,
called by `lab/drive_experiment.py::code_check`. The per-claim LLM implementation
is `lab/citation_experiment.py::CitationRunner.judge`. These are experiment
evaluators, not an exported hosted Langfuse Code-evaluator UI configuration.
Running `terminal_drive.py` alone records the agent and performs its local
validation; it does not automatically run this separate LLM judge.

The judge must return one check per claim ID exactly once. Missing, duplicate, or
contradictory checks are evaluator errors, not successful evaluations. The combined
metric treats incomplete evaluations as non-passes and reports errors separately.
Code can accept a real quotation attached to a false claim; an offline regression
test deliberately demonstrates this boundary.

An empty claims array has no failed per-claim citations. Grounding still inspects
limitations, and task success rejects omission of a supported requested fact.
Justified abstention can pass when none of the requested facts is supported.
Moving a required supported answer into limitations does not satisfy the structured
task contract.

## 1. Partial answers: no demonstrated recovery improvement

The first comparison used five cases, two prompts and three repetitions: 30 new
answers. After correcting the judge's missing metadata context, both variants had
15/15 code passes, 15/15 task passes and 14/15 grounding passes. Historical
over-abstention was observed but not reproduced at the reconstructed answer step.

The initial judge omitted file-list metadata and review records, which caused
false flags about known file names and exclusions. Both variants' same 30 answers
were re-scored with the corrected judge; six combined judgments changed. The
initial and corrected reports are both in `results/`. No new answers were
generated during re-scoring. Do not pool their scores as 60 different answers.

The remaining historical role-citation defect motivated the next study. A separate
precedence-related flag was disputed in assistant review. Original scores were
retained; assistant review is not independent human adjudication.

## 2. Citation revision 1: whole-claim coverage

Seven cases include the original five plus two explicit relationship questions.
The prompt change adds atomic claims and whole-claim/attached-quote checking.
The completed comparison has 42 new answers: code and task checks passed 21/21 in
each variant, while attached-quote support was 15/21 for the baseline and 19/21
for the candidate. These are raw judge decisions; some context/header-related
flags may be overly strict and are preserved for review.

Before generating those answers, two reference-check attempts disagreed with the
intended labels. A disputed general precedence reference was narrowed to the
specific two-schedule paraphrase; the role control was isolated by removing an
auxiliary disputed claim from both its bad and repaired versions. The rubric also
clarified the independence of task success and citation support. The audit JSON
and both unsuccessful preflight reports contain the original decisions. These
changes happened before any A/B answers and applied equally to both variants.

Seven hand-authored reference checks then matched their expected labels. These
are targeted sanity checks, not an independent calibration dataset.

## 3. Citation revision 2: relevance guard

Both answer prompts already contain the citation-coverage rule. The candidate
adds only relevance/no-unrelated-filler instructions. Evidence, model parameters,
judge rubric, task contract and trial counts stay fixed within the comparison.
Both variants generate fresh outputs; revision 1 outputs are not reused as a
baseline. Matching trial indices are not shared-seed pairs.

The seven successful reference checks were reused after checking dataset, rubric,
settings and expected-label equality. The final report records this reuse.
The 42 fresh answers yielded:

| Measure | Baseline | Candidate |
|---|---:|---:|
| Code | 21/21 | 21/21 |
| Attached-quote support | 19/21 | 21/21 |
| Task success | 21/21 | 21/21 |
| Grounding | 19/21 | 21/21 |
| Combined | 19/21 | 21/21 |
| Relationship questions, combined | 6/6 | 6/6 |
| Judge errors | 0 | 0 |

The two final baseline failures were `venue_not_in_documents`, trial 2, and
`owner_read_failed`, trial 3. They are different from the historical role defect.
The second flag follows the strict own-quote criterion even though the date is
available elsewhere in the supplied evidence. Retain that distinction when
interpreting the verdict.

The local live prompt was updated only after the final candidate passed all
planned code, grounding and task checks. The promotion record preserves that
local decision. It is not a deployment or proof of a general performance lift.

## Replay boundaries

The checkpoint reconstructs list/review/read exchanges from full saved text and
statuses. It does not reproduce exact live call batching, timing, hidden state or
all original tokens. Public IDs and URLs are aliases, so public model requests
are not byte-identical to the private requests. Offline verification checks saved
data integrity, code decisions and score aggregation; it does not re-create
semantic LLM judgments. A fresh online replay can produce different answers and
scores.

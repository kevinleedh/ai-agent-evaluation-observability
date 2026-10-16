# Runnable tracing lab

Two separate execution paths are included:

| Entry point | Source access | Setup dependency |
|---|---|---|
| `terminal_documents.py` | Python fetches from a fixed candidate list chosen by Grok | Local prompt and candidate files |
| `terminal_search.py` | Provider-hosted Grok `web_search` | Managed Langfuse chat prompt |
| `run_builtin.py` | One-item experiment using the same provider-hosted search | Managed prompt and a one-item Langfuse dataset |

The document reviewer is the primary case. It does not search the wider web.
The built-in-search files preserve the earlier tracing experiment and share
recorder helpers; they are not an interchangeable retrieval backend comparison.

## Set up

Use Python 3.12. From this directory:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Fill in your own xAI and Langfuse credentials in the ignored `.env`. Existing
environment variables take precedence. Adjust `settings.json` for your account's
available model and region. The recorded session used `grok-4.7`, reasoning effort
`low`, at most 6,000 output tokens, a 180-second client timeout and no SDK retries.
Availability of these model names and APIs can change.

```bash
.venv/bin/python terminal_documents.py --check
.venv/bin/python terminal_documents.py --question "How does Grok function calling work, and who executes a custom function—the model provider or our Python application? Support each claim with an exact quote."
```

`--check` makes no API call; it reports missing credentials and returns exit 1
until they are configured. It does not authenticate them. Running without
`--question` starts a terminal loop; `/exit` exits. Interactive input is **one
line per question**. Each question starts an independent trace. Model usage is
billable, and the question, retrieved text and model output are sent to Langfuse.
The `.command` launchers use this directory's `.venv` on macOS.

## What the document reviewer records

1. Grok receives a system prompt, the candidate titles/URLs and a user question.
   Python supplies the `review_candidates` schema; Grok supplies its arguments.
   Every candidate needs one select/exclude decision and a declared reason.
2. Only selected IDs can be read. `read_document` requires `selection_reason` and
   `information_needed` before Python downloads anything. The returned tool result
   contains the actual text Grok can read, its source/content URLs and status.
3. Continuations link to earlier calls with `previous_response_id` and provide
   new tool results. The input shown for generation 3 need not repeat all earlier
   messages. Its Attributes metadata records the link to the prior response.
4. Grok calls `submit_answer` with claims and exact quotes. Python validates quotes
   against successful reads that were available **before that model request**.
   A newly fetched document in the same response's call batch cannot justify an
   answer that the model had not yet received. Invalid submissions return a tool
   error for correction, subject to a ten-round limit.
5. Accepted claims become the rendered answer with source links. The root stores
   decisions, read snapshots, claims and limitations for later review.

The trace root is `terminal-python-document-review`. Children named
`grok-document-selection / 1`, `/ 2`, `/ 3` are model-call sequence numbers, not
different models or fixed stage types. Tool children are `candidate-review`,
`read-document` and `claim-evidence`. The tools execute in our Python application.

The root's local prompt revision is `metadata.prompt_version="2"`; the generation
observations separately set `version="2"`. Do not filter root observations on
Version=2: the root does not set that field.

The reader allows HTTPS on `docs.x.ai` and `langfuse.com`, checks redirects, bounds
downloads to 1 MB and returns at most 24,000 text characters. xAI pages are fetched
through their `.md` URL. HTML gets basic text extraction without JavaScript.
Failed reads are marked as errors and cannot supply quote evidence. This is a
bounded learning runner, not a production browser or a general retrieval system.

Quote matching normalizes whitespace only. `quote_verified=true` proves passage
presence, while `claim_support_evaluated=false` means semantic support has not been
graded by this validator. Neither flag is an independent assessment of truth.

## Offline tests

```bash
.venv/bin/python -m unittest -v test_documents.py test_evidence.py test_terminal.py test_hosted_evaluator.py
```

These tests use mocks and the SDK's real parsing code. They do not call a provider,
download current documentation or upload traces. `test_hosted_evaluator.py` uses
the public, excerpted fixtures to exercise `langfuse_code_evaluator.py`, including
deliberate corruptions and a false claim that still passes substring checks.
The hosted code evaluator itself uses only Python's standard library; the rest of
the lab needs the pinned dependencies.

## Optional built-in search replay

`builtin-managed-setup.json` exports the original managed chat prompt and one
dataset item without account IDs. In your Langfuse project, create the chat prompt
with the exported messages and dataset with the exported input/expected output.
Set the names and actual new prompt version in `settings.json`.

```bash
.venv/bin/python terminal_search.py
.venv/bin/python run_builtin.py
```

The interactive path needs only the prompt; the experiment requires exactly one
active item and no other items. Expected output is a human review reference and
is not sent to Grok. This path does not apply the document-review evaluators.

Search evidence comes from actual returned `web_search_call` items and stream
events, not from URLs in the answer. Search/open-page children record the actions
the provider returns. Their timestamps measure **client event receipt**, not
provider-internal tool duration. Final-response-only actions are labeled as such.
Readable reasoning summaries are recorded only when returned; encrypted reasoning
payloads are excluded. A `not-returned` marker is our instrumentation status,
not a model explanation and not evidence about individual document choices.

See the [case study](../../06-document-grounding-tracing.md),
[evaluation setup](../EVALUATION.md) and [provenance](../PROVENANCE.md).

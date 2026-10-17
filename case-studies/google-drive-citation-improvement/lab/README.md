# Run the Google Drive MCP lab

Use Python 3.12. Run the following commands from this `lab` directory.

## Install and inspect offline

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -v
.venv/bin/python ../scripts/verify_artifacts.py
```

The unit tests mock remote services. The artifact verifier replays deterministic
checks over saved submissions and recomputes recorded result totals; it makes no
API calls and does not re-judge semantic support with an LLM.

## Configure a new live Drive run

```sh
cp .env.example .env
cp settings.example.json settings.local.json
```

Set your xAI/Langfuse credentials in `.env`. Upload the five files in
`../fixtures/upload-to-drive/` to your own test folder and set `folder_id` in
`settings.local.json`. The public dataset's IDs and `example.invalid` source URLs
are placeholders, not a usable Drive connection.

```sh
.venv/bin/python connect_drive.py
.venv/bin/python terminal_drive.py --first-question
```

Complete the browser authorization for the existing Pipedream MCP server and
connect the intended Google Drive account. The client requires the tools
`google_drive-list-files` and `google_drive-download-file`. The observed service
contract accepts an `instruction` argument. If that external contract changes,
inspect the actual tool catalog before adapting the client. Discovery alone does
not prove file access or successful body retrieval.

The first question asks for Aurora's final approved launch date and launch owner.
Run `.venv/bin/python terminal_drive.py` for an interactive prompt. Other questions:

```text
Where will the launch event for Project Aurora take place?
Who is the approver of Project Aurora's final launch approval, who is the launch owner, and are these distinct roles? Give a separate claim and an exact supporting quote for each fact.
Who owns launch execution and who owns customer inquiries for Project Aurora? Explain whether these are distinct roles. Support each fact with an exact quote.
```

The live prompt already contains the tested final instructions. Live tool calls
can fail; this publication does not promise a successful run with new credentials
or new service behavior. The client restricts candidates/reads to direct children
of the configured folder and accepts checksum-verifiable UTF-8 `text/plain`
fixtures up to 65,536 bytes. It does not export native Google Docs or read PDFs.

## Inspect Langfuse

The environment is `drive-mcp-learning`. A typical successful observation tree is:

```text
terminal-drive-mcp-review
  grok-drive-agent / 1       -> list_drive_files
  list_drive_files
    mcp.google_drive-list-files
  grok-drive-agent / 2       -> review_candidates
  review_candidates
  grok-drive-agent / 3       -> read_drive_file requests
  read_drive_file
    mcp.google_drive-download-file
    download-reference-read
  ...additional selected reads...
  grok-drive-agent / 4       -> submit_answer
  submit_answer
```

Actual call counts can vary. Tool results include successful full decoded text or
an explicit failure. Raw MCP responses may contain signed resource URLs and
remain private. Full decoded text reaches the model; those resource URLs do not.
The wrapper records client-observed results and durations, not remote internals.
Live continuations use `previous_response_id`; the controlled comparison below
starts each final answer independently.

New live runs are saved under ignored `runs/`. To check a newly captured run's
recording against your own Langfuse project:

```sh
.venv/bin/python verify_run.py
```

OAuth data stays in ignored `.auth/`. The source includes local private-file
permissions. Never publish `.env`, `.auth`, raw run exports, or signed resources.

## Run a fresh comparison using saved evidence

This path needs xAI and Langfuse credentials but makes no Drive requests. It
creates new answers, judge calls and hosted Langfuse dataset experiments:

```sh
.venv/bin/python citation_experiment.py --study-version 2 --trials 3
.venv/bin/python report_citation_experiment.py --study-version 2
```

The seven reference checks run before comparison. If their expected labels do
not match, the runner saves `reference_disagreement` and stops before A/B answers.
Do not change labels merely to obtain a passing run; inspect disagreements and
version any substantive evaluator change. The original final experiment reused
previously successful checks after equality verification; the command above runs
them afresh.

Replay uses `portfolio-drive-citation-coverage-v2`. It refuses to overwrite an
existing dataset with different inputs. Rename/version a dataset deliberately
if you change evidence. The run alternates variant order, uses three concurrent
items at most, and writes new outputs to ignored `runs/citation-experiments-v2/`.

To repeat the earlier citation comparison, use `--study-version 1`. The earlier
partial-answer comparison is available with `drive_experiment.py --trials 3`.
The supplied frozen assets are ready to run; do not call the historical
`drive_experiment.py --prepare`, which requires private original run files.
Fresh scores may differ from the recorded scores because model outputs and
external model aliases can change.

Reporting after a fresh run writes summaries under `experiments/`. The optional
`report_citation_experiment.py --study-version 2 --promote` applies a fully passing
candidate to the local terminal prompt after checking for independent edits.
Promotion is a local prompt update, not a deployment or model training.

## Files

| File | Purpose |
|---|---|
| `terminal_drive.py` | Grok tool loop, phase limits, live tracing and saved root snapshots |
| `drive_backend.py` | Folder-scoped listing, selected-file reads, original-byte verification |
| `mcp_connection.py` | Existing MCP client, OAuth storage and complete payload tracing |
| `connect_drive.py` | Authentication and catalog discovery |
| `document_audit.py` | Tool schemas and deterministic review/quote validation |
| `drive_experiment.py` | Reconstructed answer checkpoint and shared experiment runner |
| `citation_experiment.py` | Per-claim judge, reference checks and controlled trials |
| `report_citation_experiment.py` | Recorded-score summaries and guarded local promotion |
| `experiments/` | Frozen prompts, datasets, evaluator audits and original summaries |

All public publication changes are documented in `../PROVENANCE.md` and
`../PUBLICATION.json`.

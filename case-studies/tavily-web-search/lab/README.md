# Run Grok with Tavily Search/Extract and Langfuse tracing

Use Python 3.12. From this directory:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Fill in your own xAI, Tavily and Langfuse keys in the ignored `.env`. Adjust the
Langfuse region/model in `settings.json` if needed. The inspected session used
`grok-4.7`, reasoning effort `low`, 6,000 maximum output tokens and no SDK retries.
`httpx` implements the Tavily HTTP requests; no Tavily SDK is needed.

```bash
.venv/bin/python terminal_tavily.py --check
.venv/bin/python terminal_tavily.py
```

`--check` is entirely offline and checks configuration/credential presence rather
than authentication. It returns exit 1 until required keys are configured. The
interactive loop accepts one line per independent question. `/exit` exits. The
macOS launcher `Start Tavily Search.command` uses the adjacent `.venv`.

For one question and exit:

```bash
.venv/bin/python terminal_tavily.py --question "Using official xAI documentation, explain how Grok function calling works and who executes custom functions: the model provider or our Python application. Use at most three claims, each with an exact supporting quote."
```

Live runs use paid xAI/Tavily APIs and send the question, search/extraction results
and answer to Langfuse. The terminal prints the answer and private Trace link.
An ignored `runs/` file retains the root snapshot locally; review it before sharing.
There is no web-app deployment or managed Langfuse prompt/dataset prerequisite.

## Files and execution

- `terminal_tavily.py`: phase/budget control, model continuation, tool traces and terminal interface.
- `tavily_backend.py`: fixed Tavily endpoints, bounded response handling and selected-page extraction.
- `document_audit.py`: candidate decision and claim-to-quote validation helpers.
- `tavily_selection_prompt.txt`: local agent instruction, version 1.
- `runtime.py`: terminal key prompt and local file root, extracted from the original shared runner.
- `langfuse_tavily_code_evaluator.py`: standalone standard-library source for Langfuse Code evaluation.

The tools are `search_web`, `review_candidates`, `read_document` and
`submit_answer`. Their Langfuse records are named `tavily-search`,
`candidate-review`, `tavily-extract` and `claim-evidence`. The root is
`terminal-tavily-web-search` in environment `tavily-search-learning`.

The model creates a query, reviews all returned candidates, selects at most two
documents, receives their extracted text, then submits claims with exact quotes.
Python executes actual HTTP calls and checks the arguments/results. This path
does not use Grok's provider-hosted `web_search`.

`tavily_settings.json` bounds each question to one search attempt, up to five
results, two extraction attempts and ten model calls. Failures consume attempt
budgets. There is no automatic retry, repeat query or direct-download fallback.
Search snippets inform selection but do not count as final quote evidence.

Extract's `results` and `failed_results` are checked even for HTTP 200. Only a
nonempty result matching the requested URL becomes a successful read. Returned
text is capped at 24,000 characters. Only text available before a model request
can support a submitted quote, including when one response requests multiple tools.

Reasons are declared justifications. Tool durations measure the Python request
wrapper; returned `response_time` is separate provider metadata. Neither exposes
internal Tavily stages or hidden model reasoning. `quote_verified=True` checks
whitespace-normalized passage presence; semantic support remains separately graded.

## Offline tests

```bash
.venv/bin/python -m unittest -v test_tavily.py test_langfuse_tavily_evaluator.py
```

These run 23 tests, including 25 negative mutations within one test method.
They use mocked HTTP transport and the real SDK parser, not live APIs or an LLM.
The checker tests include valid abstention, a failed unused read, unscored runtime
failure, invalid evidence and a semantic falsehood that still passes presence checks.

Public fixtures can also be checked without installing third-party packages:

```bash
python3 - <<'PY'
import json
from pathlib import Path
from types import SimpleNamespace
from langfuse_tavily_code_evaluator import evaluate

for path in sorted(Path('../fixtures').glob('*.json')):
    data = json.loads(path.read_text())
    ctx = SimpleNamespace(observation=SimpleNamespace(
        input=data['input'], output=data['output']))
    score = evaluate(ctx).scores[0]
    print(path.name, score.value, score.comment)
PY
```

The public bodies are excerpts. This replays deterministic checks, not the full
context of the historic LLM test. See [evaluation setup](../EVALUATION.md) and
[provenance](../PROVENANCE.md).

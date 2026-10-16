# Evidence and replay boundaries

This case records the October 16, 2026 Tavily tracing/evaluation learning session.
Publication preparation used saved files, read-only Langfuse API inspection and
offline tests. It did not create new paid model answers, Tavily requests or judge
calls, and did not change evaluator definitions/rules/scores.

## Observed evidence

- `connection-check` is the initial successful live run, supplied as a complete
  JSON trace export by the user and also saved locally by the runner. Its ten
  observations include four Grok calls, one search, candidate review, two Extract
  calls and final claim validation.
- `user-replay` is a separate execution of the same question, saved by the user's
  terminal run. The local root Input/Output were matched against Langfuse's
  Observations API response. Its query, candidate URLs, two returned text lengths,
  three-claim/three-quote counts and four model calls match the first run; claim
  wording/IDs and limitations differ. These are two executions of one example.
- Provider response continuation links in both traces were checked before request
  identifiers were removed. Full search and extraction records, not answer URLs
  alone, establish the observed tool executions. Wrapper timings do not expose
  Tavily's internal processing stages.
- The user's completed Code Output screenshot shows Boolean True and the full
  5-candidate/5-decision/2-read/3-claim/3-quote comment. A machine export identifying
  that UI test's exact target was not supplied or recovered. It is not silently
  treated as an identified score attachment to either published run.
- The saved Python evaluator source was exported through the Langfuse Evaluators
  API. This exact source is published and replayed locally against both original
  snapshots and both excerpted public fixtures. All four returned True. The
  original compact authored file and pasted UI source differ in formatting and
  some equivalent control-flow expression structure; the exported source is used
  for publication tests rather than claiming byte/AST identity.
- The LLM Boolean True and its complete explanation were visible in the user's
  screenshot and independently retrieved through the Observations API. Test target
  trace/observation IDs identify the `user-replay` root. Both embedded judge input
  and output data were verified equal to that root's complete original data.
- The saved judge configuration was exported: System rubric, actual User wrapper,
  Input/Output mappings, Boolean output and model `grok-4.7`. Its per-call model
  parameter snapshot was empty. The advanced score-instruction fields contain
  default placeholder wording; those fields are retained rather than rewritten
  and presented as an observed setting.
- Both evaluator definitions were saved and active, but both had zero automatic
  rules. Scores API queries for both original traces returned empty lists. There
  is no new formal Human Judge label in this case. Assistant/user discussion of
  the output is not represented as a saved human annotation.

## Publication changes

- Source files were copied by an explicit allowlist. No `.env`, local run exports,
  raw screenshots, private account names, project/trace/observation IDs, API keys
  or provider request IDs are published. `.env.example` has empty placeholders.
- The Tavily terminal runner originally imported `ROOT` and `request_key` from
  `run_builtin.py`. Their definitions were extracted into `runtime.py` and that
  import updated to keep this bundle standalone. No unrelated built-in-search
  experiment code or managed prompt/dataset prerequisite is needed here.
- The portable macOS launcher uses the adjacent `.venv`; personal absolute paths
  were removed. Unused managed-search prompt/dataset settings were omitted from
  the copied `settings.json`. Tavily settings and agent prompt are retained.
- The hosted evaluator source and saved judge messages/configuration are exported
  without substantive rewriting. Account/version IDs and authors are omitted.
- Public root fixtures retain original questions, candidate URLs/decisions,
  answers, limitations and claim quotes. Search snippets are shortened to at most
  300 characters. Extracted bodies are replaced by their linked quote excerpts;
  the unused Overview read keeps only its opening 300 characters. Public text
  length/truncation fields are updated and `_publication` preserves original read
  lengths/truncation facts. These fixtures are not complete raw exports.
- Live generation and LLM judging received the complete text returned in that
  execution: 22,753 and 7,856 characters. Public fixtures are suitable for code
  replay and inspection, not byte-for-byte reproduction of the full judge context.

## Validation and limits

The published bundle has 23 offline tests: 13 HTTP/session/SDK tests and 10 hosted
checker tests. One checker method contains 25 negative mutations. These include
missing/duplicate decisions, invented/unread/failed quote sources, quote length,
URL/budget/count mismatches, malformed evidence and changed final-answer prose.
They are synthetic checker inputs, not historic failed Grok answers or measured
LLM judge error detection. A false semantic claim with a genuine quote deliberately
passes code checks to illustrate their scope.

This case demonstrates bounded execution and two evaluation methods on a positive
example. It does not establish autonomous repeated search, complete web coverage,
optimal query/source choice, general answer truth or a reliable semantic judge.
Generator and judge use the same model name. No negative semantic judgment,
independent held-out question set, failure-rate denominator or cost comparison is
available. Snapshot consistency does not independently authenticate network calls
or reconstruct every child span. Historic source wording/titles are preserved;
current pages, model availability and search results may differ on replay.

"""Grok chooses a Tavily query and documents; Python executes and traces tools."""
import argparse
from datetime import datetime, timezone
import json
import os

from document_audit import REVIEW_TOOL, SUBMIT_TOOL, function, nonempty, validate_answer, validate_review
from runtime import ROOT, request_key
from tavily_backend import TavilyBackend

SEARCH_TOOL = function("search_web", "Search the web once with Tavily; declare the query's purpose first.", {
    "query": {"type": "string"}, "search_reason": {"type": "string"},
    "information_needed": {"type": "string"},
}, ["query", "search_reason", "information_needed"])
READ_TOOL = function("read_document", "Extract a selected search-result document with Tavily.", {
    "document_id": {"type": "string"}, "selection_reason": {"type": "string"},
    "information_needed": {"type": "string"},
}, ["document_id", "selection_reason", "information_needed"])
TRACE_NAMES = {"search_web": "tavily-search", "review_candidates": "candidate-review",
               "read_document": "tavily-extract", "submit_answer": "claim-evidence"}


def safe_error(error):
    """Never copy an HTTP exception's request, headers or body to the trace."""
    return {"status": "failed", "error_type": type(error).__name__,
            "http_status": getattr(getattr(error, "response", None), "status_code", None),
            "validation_error": str(error) if type(error) is ValueError else None,
            "instruction": "Correct invalid fields or quotes if possible; never use failed reads as evidence. Budgets do not reset."}


class ReviewSession:
    def __init__(self, backend, settings):
        self.backend, self.settings = backend, settings
        self.search_attempts = 0
        self.read_attempts = 0
        self.search_result = None
        self.candidates = []
        self.review = None
        self.reads = []

    def tools(self):
        if self.search_result is None:
            return [SEARCH_TOOL]
        if self.review is None:
            return [REVIEW_TOOL]
        selected = any(d["decision"] == "select" for d in self.review["decisions"])
        if selected and self.read_attempts < self.settings["max_read_attempts"]:
            return [READ_TOOL, SUBMIT_TOOL]
        return [SUBMIT_TOOL]

    def snapshot(self):
        return {"search_result": self.search_result, "candidates": self.candidates,
                "candidate_review": self.review, "read_documents": self.reads,
                "search_attempts": self.search_attempts, "read_attempts": self.read_attempts,
                "backend": "tavily-search-extract", "web_wide_search": True,
                "reason_kind": "model_declared_action_justification"}

    def execute(self, name, arguments, available_evidence):
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object")
        if name not in {t["name"] for t in self.tools()}:
            raise ValueError("Tool unavailable in this phase or its budget is exhausted")
        if name == "search_web":
            for key in ("query", "search_reason", "information_needed"):
                if not nonempty(arguments.get(key)):
                    raise ValueError("Search requires a query, reason and intended information")
            if len(arguments["query"]) > 400:
                raise ValueError("Use a focused query of at most 400 characters")
            if self.search_attempts >= self.settings["max_search_attempts"]:
                raise ValueError("Search budget exhausted")
            self.search_attempts += 1
            try:
                result = self.backend.search(arguments["query"])
            except Exception as error:
                result = safe_error(error)
            self.search_result = {**arguments, **result}
            self.candidates = result.get("candidates", [])
            return self.search_result
        if name == "review_candidates":
            result = validate_review(arguments, self.candidates)
            if sum(d["decision"] == "select" for d in result["decisions"]) > self.settings["max_read_attempts"]:
                raise ValueError("Select at most two documents for this lesson")
            result.update(basis="question_and_search_titles_urls_snippets",
                          reason_kind="model_declared_before_extract")
            self.review = result
            return result
        if name == "read_document":
            for key in ("document_id", "selection_reason", "information_needed"):
                if not nonempty(arguments.get(key)):
                    raise ValueError("Reads require a document ID, reason and intended information")
            doc_id = arguments["document_id"]
            selected = {d["document_id"] for d in self.review["decisions"] if d["decision"] == "select"}
            candidate = next((d for d in self.candidates if d["id"] == doc_id), None)
            if doc_id not in selected or candidate is None:
                raise ValueError("Read only a selected search-result ID")
            if any(r["document_id"] == doc_id for r in self.reads):
                raise ValueError("This document was already attempted; use another selected document")
            self.read_attempts += 1
            try:
                result = self.backend.extract(candidate)
            except Exception as error:
                result = {**safe_error(error), "document_id": doc_id, "source_url": candidate["url"]}
            record = {**arguments, **result}
            self.reads.append(record)
            return record
        if name == "submit_answer":
            # Snapshot is taken before the model call, so same-batch reads are not yet evidence.
            return validate_answer(arguments, available_evidence)
        raise ValueError("Unknown tool")


def ask(question, *, langfuse, client, backend, settings):
    session = ReviewSession(backend, settings)
    messages = [{"role": "system", "content": (ROOT / "tavily_selection_prompt.txt").read_text()},
                {"role": "user", "content": question}]
    previous_id = None
    budgets = {k: settings[k] for k in ("max_search_attempts", "max_results", "max_read_attempts", "max_model_calls")}
    with langfuse.start_as_current_observation(
        name="terminal-tavily-web-search", as_type="span",
        input={"question": question, "budgets": budgets},
        metadata={"backend": "tavily-search-extract", "web_wide_search": True,
                  "prompt_version": settings["prompt_version"], "output_language": "English",
                  "reason_kind": "model_declared_action_justification"},
    ) as root:
        trace_url = langfuse.get_trace_url()
        print("\nTrace:", trace_url, flush=True)
        try:
            for turn in range(settings["max_model_calls"]):
                tools = session.tools()
                available_evidence = list(session.reads)
                print(f"\nGrok call {turn + 1}/{settings['max_model_calls']}", flush=True)
                with langfuse.start_as_current_observation(
                    name=f"grok-tavily-agent / {turn + 1}", as_type="generation",
                    model=settings["model"], input=messages, version=settings["prompt_version"],
                    metadata={"previous_response_id": previous_id,
                              "available_tools": [t["name"] for t in tools]},
                    model_parameters={"reasoning_effort": settings["reasoning_effort"],
                                      "max_output_tokens": settings["max_output_tokens"]},
                ) as generation:
                    try:
                        params = {"model": settings["model"], "input": messages, "tools": tools,
                                  "tool_choice": "required", "store": True,
                                  "reasoning": {"effort": settings["reasoning_effort"]},
                                  "max_output_tokens": settings["max_output_tokens"]}
                        if previous_id:
                            params["previous_response_id"] = previous_id
                        response = client.responses.create(**params)
                        calls = [x for x in response.output if x.type == "function_call"]
                        usage = response.usage
                        generation.update(
                            output={"answer": response.output_text,
                                    "tool_calls": [x.model_dump(mode="json") for x in calls]},
                            metadata={"provider_response_id": response.id},
                            usage_details={"input": usage.input_tokens, "output": usage.output_tokens,
                                           "total": usage.total_tokens} if usage else None)
                        if response.status != "completed" or not calls:
                            raise RuntimeError("Model did not complete a required tool request")
                    except BaseException as error:
                        generation.update(level="ERROR", status_message=type(error).__name__)
                        raise
                previous_id = response.id
                messages = []
                for call in calls:
                    with langfuse.start_as_current_observation(
                        name=TRACE_NAMES.get(call.name, "unknown-tool"), as_type="tool",
                        metadata={"provider_call_id": call.call_id, "backend": "python-executed",
                                  "timing_basis": "client_request_wrapper"},
                    ) as tool:
                        try:
                            if call.name not in {t["name"] for t in tools}:
                                raise ValueError("Tool was not offered for this model call")
                            arguments = json.loads(call.arguments)
                            tool.update(input=arguments)
                            result = session.execute(call.name, arguments, available_evidence)
                            tool.update(output=result)
                            if result.get("status") == "failed":
                                tool.update(level="ERROR", status_message=result.get("error_type", "Tool failed"))
                            if call.name == "submit_answer":
                                output = {**result, **session.snapshot()}
                                root.update(output=output)
                                print("\nAnswer:\n" + output["answer"], flush=True)
                                if output["limitations"]:
                                    print("\nLimitations:", output["limitations"], flush=True)
                                print("\nQuote presence checked; semantic support still needs review.")
                                print("Langfuse Tracing:", trace_url, flush=True)
                                return {"input": {"question": question, "budgets": budgets},
                                        "output": output, "trace_url": trace_url}
                            print_tool_result(call.name, result)
                        except Exception as error:
                            result = safe_error(error)
                            tool.update(output=result, level="ERROR", status_message=type(error).__name__)
                            print("Tool rejected:", result["validation_error"] or result["error_type"], flush=True)
                        messages.append({"type": "function_call_output", "call_id": call.call_id,
                                         "output": json.dumps(result, ensure_ascii=False)})
            raise RuntimeError("Model-call limit reached without an accepted answer")
        except BaseException as error:
            root.update(level="ERROR", status_message=type(error).__name__,
                        output={"status": "failed", **session.snapshot()})
            raise


def print_tool_result(name, result):
    if result.get("status") == "failed":
        print(f"{name}: failed ({result.get('error_type', 'ToolFailure')}); inspect Trace.", flush=True)
    elif name == "search_web":
        print("Search query:", result["query"], flush=True)
        print("Search reason:", result["search_reason"], flush=True)
        for item in result["candidates"]:
            print(f"  {item['id']}: {item['title']} — {item['url']}", flush=True)
    elif name == "review_candidates":
        for item in result["decisions"]:
            print(f"{item['decision'].upper()}: {item['document_id']} — {item['reason']}", flush=True)
    elif name == "read_document":
        print("Extracted:", result["source_url"], flush=True)
        print("Selection reason:", result["selection_reason"], flush=True)
        print(f"Returned to Grok: {len(result['text'])} characters | truncated: {result['truncated']}", flush=True)


def load_settings():
    settings = json.loads((ROOT / "settings.json").read_text())
    settings.update(json.loads((ROOT / "tavily_settings.json").read_text()))
    if (settings["max_search_attempts"] != 1 or not 1 <= settings["max_results"] <= 5
            or not 1 <= settings["max_read_attempts"] <= 2 or not 4 <= settings["max_model_calls"] <= 10):
        raise ValueError("Invalid budgets for this bounded Tavily lesson")
    return settings


def main():
    from dotenv import load_dotenv
    from langfuse import Langfuse
    from openai import OpenAI
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", help="Submit one complete question and exit")
    parser.add_argument("--check", action="store_true", help="Offline settings and credential-presence check")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False, interpolate=False)
    settings = load_settings()
    required = ("XAI_API_KEY", "TAVILY_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
    if args.question is not None and not args.question.strip():
        parser.error("Question must not be empty")
    if args.check:
        missing = [k for k in required if not os.environ.get(k, "").strip()]
        print("Grok + Tavily Search/Extract | 1 search | up to 5 results | up to 2 reads")
        print("Credential setup:", "ready" if not missing else "missing: " + ", ".join(missing))
        print("No API calls; authentication not tested.")
        return 1 if missing else 0
    lf = Langfuse(public_key=request_key("LANGFUSE_PUBLIC_KEY", "Langfuse Public Key"),
                  secret_key=request_key("LANGFUSE_SECRET_KEY", "Langfuse Secret Key"),
                  base_url=os.environ.get("LANGFUSE_BASE_URL") or settings["langfuse_base_url"],
                  environment=settings["environment"])
    client, backend = None, None
    try:
        if not lf.auth_check():
            raise RuntimeError("Langfuse authentication failed")
        backend = TavilyBackend(request_key("TAVILY_API_KEY", "Tavily API Key"),
                                max_results=settings["max_results"], timeout=settings["tavily_timeout_seconds"])
        client = OpenAI(api_key=request_key("XAI_API_KEY", "xAI API Key"),
                        base_url="https://api.x.ai/v1", timeout=settings["timeout_seconds"], max_retries=0)
        print("Grok + Tavily web search | English answers | Langfuse tracing")
        print("One line per independent question | Paid API usage | Exit: /exit or Ctrl+C")
        while True:
            try:
                question = args.question if args.question is not None else input("\nQuestion > ")
            except EOFError:
                break
            question = question.strip()
            if question.lower() in ("/exit", "/quit"):
                break
            if not question:
                continue
            try:
                result = ask(question, langfuse=lf, client=client, backend=backend, settings=settings)
                folder = ROOT / "runs"
                folder.mkdir(exist_ok=True)
                filename = "tavily-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json"
                (folder / filename).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
                print("Local run:", folder / filename, flush=True)
            except Exception as error:
                print("Execution failed:", type(error).__name__, "— inspect the Trace above.", flush=True)
                if args.question is not None:
                    return 1
            finally:
                lf.flush()
            if args.question is not None:
                break
        return 0
    finally:
        if backend:
            backend.close()
        if client:
            client.close()
        lf.shutdown()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nStopped.")
        raise SystemExit(130)
    except Exception as error:
        print("Setup/execution failed:", type(error).__name__, "— check credentials and settings.")
        raise SystemExit(1)

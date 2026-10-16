"""Python document reader with mandatory declared reasons and Langfuse tracing."""
import argparse
from html.parser import HTMLParser
import json
import os
from urllib.parse import urlparse

import httpx

from run_builtin import ROOT, request_key
from document_audit import REVIEW_TOOL, SUBMIT_TOOL, validate_review, validate_answer

MAX_BYTES = 1_000_000
MAX_TEXT = 24_000
MAX_ROUNDS = 10
ALLOWED_HOSTS = {"docs.x.ai", "langfuse.com"}
TOOL = {
    "type": "function", "name": "read_document",
    "description": "Read a candidate document. A selection reason and intended fact are required.",
    "parameters": {"type": "object", "properties": {
        "document_id": {"type": "string"},
        "selection_reason": {"type": "string"},
        "information_needed": {"type": "string"},
    }, "required": ["document_id", "selection_reason", "information_needed"],
        "additionalProperties": False},
}


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "header", "footer"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "header", "footer"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def validate_url(url):
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Only configured official documentation hosts are allowed")


def fetch_document(url):
    validate_url(url)
    # xAI offers Markdown versions of its docs; the source URL remains clickable.
    content_url = url + ".md" if urlparse(url).hostname == "docs.x.ai" else url
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
        for _ in range(4):
            validate_url(content_url)
            with client.stream("GET", content_url, headers={
                    "User-Agent": "DocumentReviewLearning/1.0"}) as response:
                if response.is_redirect:
                    content_url = str(response.url.join(response.headers["location"]))
                    continue
                response.raise_for_status()
                mime = response.headers.get("content-type", "").lower()
                if not any(kind in mime for kind in ("text/", "application/xhtml")):
                    raise ValueError("Unsupported document content type")
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError("Document exceeds size limit")
                    chunks.append(chunk)
                text = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                if "html" in mime:
                    parser = PageText()
                    parser.feed(text)
                    text = "\n".join(parser.parts)
                if not text.strip():
                    raise ValueError("Document contains no readable text")
                return {"source_url": url, "content_url": str(response.url),
                        "text": text[:MAX_TEXT], "truncated": len(text) > MAX_TEXT,
                        "status": "read"}
    raise ValueError("Too many redirects")


def execute_read(arguments, candidates, fetcher=fetch_document):
    """Validate the justification before any network request happens."""
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object")
    for field in ("document_id", "selection_reason", "information_needed"):
        if not isinstance(arguments.get(field), str) or not arguments[field].strip():
            raise ValueError("Required tool fields must be nonempty strings")
    candidate = next((d for d in candidates if d["id"] == arguments["document_id"]), None)
    if candidate is None:
        raise ValueError("Unknown candidate ID")
    return fetcher(candidate["url"])


def ask(question, *, langfuse, client, candidates, settings):
    system = (ROOT / "document_selection_prompt.txt").read_text()
    messages = [{"role": "system", "content": system + "\n\nCandidate documents:\n"
                 + json.dumps(candidates, ensure_ascii=False)},
                {"role": "user", "content": question}]
    with langfuse.start_as_current_observation(
        name="terminal-python-document-review", as_type="span",
        input={"question": question, "candidates": candidates},
        metadata={"backend": "python-document-reader", "web_wide_search": False,
                  "reason_kind": "model_declared_before_fetch", "prompt_version": "2",
                  "output_language": "English"},
    ) as root:
        trace_url = langfuse.get_trace_url()
        print("\nTrace:", trace_url, flush=True)
        read_documents = []
        candidate_review = None
        previous_id = None
        try:
            for turn in range(MAX_ROUNDS):
                print(f"Grok is reviewing documents and preparing evidence… ({turn + 1}/{MAX_ROUNDS})", flush=True)
                tools = [REVIEW_TOOL] if candidate_review is None else [TOOL, SUBMIT_TOOL]
                available_evidence = list(read_documents)
                with langfuse.start_as_current_observation(
                    name=f"grok-document-selection / {turn + 1}", as_type="generation",
                    model=settings["model"], input=messages, version="2",
                    metadata={"previous_response_id": previous_id},
                    model_parameters={"reasoning_effort": settings["reasoning_effort"],
                                      "max_output_tokens": settings["max_output_tokens"]},
                ) as generation:
                    try:
                        params = {"model": settings["model"], "input": messages,
                                  "tools": tools, "tool_choice": "required",
                                  "reasoning": {"effort": settings["reasoning_effort"]},
                                  "max_output_tokens": settings["max_output_tokens"], "store": True}
                        if previous_id:
                            params["previous_response_id"] = previous_id
                        response = client.responses.create(**params)
                        calls = [item for item in response.output if item.type == "function_call"]
                        usage = response.usage
                        generation.update(output={"answer": response.output_text,
                            "tool_calls": [call.model_dump(mode="json") for call in calls]},
                            usage_details={"input": usage.input_tokens, "output": usage.output_tokens,
                                           "total": usage.total_tokens} if usage else None,
                            metadata={"provider_response_id": response.id})
                        if response.status != "completed":
                            raise RuntimeError("Model response incomplete")
                    except BaseException as error:
                        generation.update(level="ERROR", status_message=type(error).__name__)
                        raise
                if not calls:
                    raise RuntimeError("The model did not submit the required structured tool call")
                previous_id = response.id
                messages = []
                for call in calls:
                    # Never persist unparsed arbitrary argument strings in error messages.
                    with langfuse.start_as_current_observation(
                        name={"review_candidates": "candidate-review", "read_document": "read-document",
                              "submit_answer": "claim-evidence"}.get(call.name, "unknown-tool"),
                        as_type="tool",
                        metadata={"provider_call_id": call.call_id,
                                  "reason_kind": "model_declared_before_fetch"},
                    ) as tool:
                        try:
                            if call.name not in {definition["name"] for definition in tools}:
                                raise ValueError("This tool is not available in the current phase")
                            arguments = json.loads(call.arguments)
                            tool.update(input=arguments)
                            if call.name == "review_candidates":
                                if candidate_review is not None or read_documents:
                                    raise ValueError("Candidate review must happen once before reading")
                                candidate_review = validate_review(arguments, candidates)
                                result = candidate_review
                                for decision in result["decisions"]:
                                    print(f"{decision['decision'].upper()}: {decision['document_id']} — {decision['reason']}", flush=True)
                            elif call.name == "read_document":
                                if candidate_review is None:
                                    raise ValueError("Review every candidate before reading")
                                selected = {d["document_id"] for d in candidate_review["decisions"]
                                            if d["decision"] == "select"}
                                if not isinstance(arguments, dict) or arguments.get("document_id") not in selected:
                                    raise ValueError("Only selected candidates may be read")
                                result = execute_read(arguments, candidates)
                                read_documents.append({**arguments, **result})
                                print("\nDocument:", result["source_url"], flush=True)
                                print("Selection reason:", arguments["selection_reason"], flush=True)
                                print("Information needed:", arguments["information_needed"], flush=True)
                            elif call.name == "submit_answer":
                                if candidate_review is None:
                                    raise ValueError("Review every candidate before submitting an answer")
                                result = validate_answer(arguments, available_evidence)
                                tool.update(output=result)
                                result.update(candidate_review=candidate_review, read_documents=read_documents,
                                              reason_kind="model_declared_before_fetch")
                                root.update(output=result)
                                print("\nAnswer:\n" + result["answer"], flush=True)
                                print(f"\nEvidence-linked claims: {len(result['claim_evidence'])}")
                                print("Quote presence verified; semantic support still needs review.")
                                print("Langfuse Tracing:", trace_url, flush=True)
                                return result
                            else:
                                raise ValueError("Unknown tool")
                            tool.update(output=result)
                        except Exception as error:
                            result = {"status": "failed", "error_type": type(error).__name__,
                                      "http_status": getattr(getattr(error, "response", None), "status_code", None),
                                      "instruction": "Correct the invalid fields or quotes and retry; never use failed reads as evidence.",
                                      "validation_error": str(error) if type(error) is ValueError else None}
                            tool.update(output=result, level="ERROR", status_message=type(error).__name__)
                            print("Tool execution failed:", type(error).__name__, flush=True)
                        messages.append({"type": "function_call_output", "call_id": call.call_id,
                                         "output": json.dumps(result, ensure_ascii=False)})
            raise RuntimeError("Document review exceeded turn limit")
        except BaseException as error:
            root.update(level="ERROR", status_message=type(error).__name__,
                        output={"status": "failed", "read_documents": read_documents,
                                "candidate_review": candidate_review})
            raise


def main():
    from dotenv import load_dotenv
    from langfuse import Langfuse
    from openai import OpenAI
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", help="Ask one question and exit")
    parser.add_argument("--check", action="store_true", help="Offline configuration check")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False, interpolate=False)
    settings = json.loads((ROOT / "settings.json").read_text())
    candidates = json.loads((ROOT / "document_candidates.json").read_text())
    if not candidates or len({d["id"] for d in candidates}) != len(candidates):
        raise ValueError("Candidate list must contain unique IDs")
    for candidate in candidates:
        validate_url(candidate["url"])
    if args.question is not None and not args.question.strip():
        parser.error("Question must not be empty")
    if args.check:
        missing = [k for k in ("XAI_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
                   if not os.environ.get(k, "").strip()]
        print(f"{len(candidates)} candidates | Python document reader | English output | prompt v2")
        print("Credential setup:", "ready" if not missing else "missing: " + ", ".join(missing))
        print("No API calls. Candidate decisions and claim-to-quote links are required.")
        return 1 if missing else 0
    lf = Langfuse(public_key=request_key("LANGFUSE_PUBLIC_KEY", "Langfuse Public Key"),
                  secret_key=request_key("LANGFUSE_SECRET_KEY", "Langfuse Secret Key"),
                  base_url=os.environ.get("LANGFUSE_BASE_URL") or settings["langfuse_base_url"],
                  environment="web-search-learning")
    client = None
    try:
        if not lf.auth_check():
            raise RuntimeError("Langfuse authentication failed")
        client = OpenAI(api_key=request_key("XAI_API_KEY", "xAI API Key"),
                        base_url="https://api.x.ai/v1", timeout=settings["timeout_seconds"], max_retries=0)
        print("Python document review | Candidate decisions and claim-to-quote evidence")
        print("Reviews known documents; does not search the entire web. Candidates:")
        for doc in candidates:
            print("- " + doc["title"] + ": " + doc["url"])
        print("Independent questions | API usage is billable | Exit: /exit or Ctrl+C")
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
                ask(question, langfuse=lf, client=client, candidates=candidates, settings=settings)
            except Exception as error:
                print("Execution failed:", type(error).__name__, "— inspect the trace above.")
                if args.question is not None:
                    return 1
            finally:
                lf.flush()
            if args.question is not None:
                break
        return 0
    finally:
        lf.flush()
        if client is not None:
            client.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nStopped.")
        raise SystemExit(130)
    except Exception as error:
        print("Setup failed:", type(error).__name__)
        raise SystemExit(1)

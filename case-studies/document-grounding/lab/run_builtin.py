"""One hosted-dataset item, Grok's real web_search, Langfuse experiment.

Reads credentials from the adjacent .env without writing them to logs or disk.
No retries, automatic judges or quality scores. --check is entirely offline.
Running without --check prompts for missing keys.
"""
import argparse
from datetime import datetime, timezone
from getpass import getpass
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


class ReasoningSummaryRecorder:
    """Record provider-disclosed summaries, never encrypted reasoning payloads."""

    TEXT_EVENTS = {
        "response.reasoning_summary_text.delta", "response.reasoning_summary_text.done",
        "response.reasoning_text.delta", "response.reasoning_text.done",
    }

    def __init__(self, generation):
        self.generation = generation
        self.parts = {}

    def _save(self, item_id, index, text, *, append, origin, event=None):
        key = (item_id, index)
        state = self.parts.get(key)
        if state is None:
            state = self.parts[key] = {"item_id": item_id, "summary_index": index,
                "text": "", "events": [], "origin": origin,
                "first_received_at": datetime.now(timezone.utc).isoformat(),
                "span": self.generation.start_observation(
                    name="reasoning-summary", as_type="span",
                    metadata={"content_kind": "provider_reasoning_summary",
                              "provider_item_id": item_id, "summary_index": index,
                              "origin": origin, "timing_basis": "client_event_receipt",
                              "document_reason_mapping": "not_inferred"})}
        state["text"] = state["text"] + text if append else text
        if event:
            state["events"].append(event)
        # Update while the span is open; close only after final reconciliation.
        state["span"].update(output=self._public(state))

    @staticmethod
    def _public(state):
        return {key: value for key, value in state.items() if key != "span"}

    def record(self, event):
        body = event.model_dump(mode="json")
        kind = body.get("type", "")
        if kind in self.TEXT_EVENTS:
            text = body.get("delta") if kind.endswith(".delta") else body.get("text")
            if not isinstance(text, str) or not text:
                return
            item_id = body.get("item_id") or "output:" + str(body.get("output_index", 0))
            index = body.get("summary_index", body.get("content_index", 0))
            # Keep only disclosed text and event identifiers; no full reasoning item.
            safe_event = {"type": kind, "received_at": datetime.now(timezone.utc).isoformat(),
                          "sequence_number": body.get("sequence_number")}
            self._save(item_id, index, text, append=kind.endswith(".delta"),
                       origin="stream", event=safe_event)
        elif kind == "response.output_item.done":
            self._from_item(body.get("item") or {}, body.get("output_index", 0), "stream_item")

    def _from_item(self, item, output_index, origin):
        if item.get("type") != "reasoning":
            return
        item_id = item.get("id") or "output:" + str(output_index)
        for index, part in enumerate(item.get("summary") or []):
            text = part.get("text")
            if part.get("type") == "summary_text" and isinstance(text, str) and text:
                self._save(item_id, index, text, append=False, origin=origin)

    def reconcile(self, response):
        for index, item in enumerate(response.model_dump(mode="json").get("output", [])):
            self._from_item(item, index, "final_response")

    @property
    def summaries(self):
        return [self._public(state) for state in self.parts.values()]

    def close(self):
        for state in self.parts.values():
            state["span"].end()
        if not self.parts:
            status = self.generation.start_observation(
                name="reasoning-summary / not-returned", as_type="event",
                output={"status": "not_returned",
                        "explanation": "The provider did not return a readable reasoning summary. "
                                       "No document-selection rationale was inferred."},
                metadata={"content_kind": "reasoning_summary_availability"},
            )
            status.end()


class SearchTraceRecorder:
    """Child tools from provider records; times are client receipt times only."""

    def __init__(self, generation):
        self.generation = generation
        self.calls = {}
        self.events = []

    def record(self, event):
        body = event.model_dump(mode="json")
        kind = body.get("type", "")
        item = body.get("item") or {}
        if item.get("type") != "web_search_call" and not kind.startswith(
                "response.web_search_call."):
            return  # Never collect reasoning or answer-text deltas.
        call_id = item.get("id") or body.get("item_id")
        if not call_id:
            return
        received = datetime.now(timezone.utc).isoformat()
        record = {"received_at": received, "event": body}
        self.events.append(record)
        state = self.calls.get(call_id)
        if state is None:
            tool = self.generation.start_observation(
                name="web_search", as_type="tool",
                metadata={"provider_call_id": call_id,
                          "timing_basis": "client_event_receipt",
                          "first_received_at": received},
            )
            state = self.calls[call_id] = {
                "tool": tool, "item": {}, "events": [], "ended": False}
        state["events"].append(record)
        state["item"].update(item)
        if kind.startswith("response.web_search_call."):
            state["item"].update(type="web_search_call", id=call_id,
                                  status=kind.rsplit(".", 1)[-1])
        returned = state["item"]
        action = returned.get("action") or {}
        state["tool"].update(
            name="web_search / " + action.get("type", "pending"),
            input=action or None,
            output={"provider_call": returned.copy(),
                    "received_events": list(state["events"])},
        )
        if kind == "response.output_item.done" and not state["ended"]:
            failed = returned.get("status") in ("failed", "incomplete")
            if failed:
                state["tool"].update(level="ERROR", status_message="Provider tool failed")
            state["tool"].end()
            state["ended"] = True

    def reconcile(self, response):
        # Some providers expose calls only in the final response. Preserve them
        # without pretending their execution start/end were observed live.
        for item in response.model_dump(mode="json").get("output", []):
            if item.get("type") != "web_search_call":
                continue
            state = self.calls.get(item.get("id"))
            if state is None:
                tool = self.generation.start_observation(
                    name="web_search / " + (item.get("action") or {}).get("type", "unknown"),
                    as_type="tool", input=item.get("action"), output=item,
                    metadata={"provider_call_id": item.get("id"),
                              "timing_basis": "final_response_only",
                              "execution_duration_observed": False},
                )
                if item.get("status") in ("failed", "incomplete"):
                    tool.update(level="ERROR", status_message="Provider tool failed")
                tool.end()
            elif not state["ended"]:
                state["item"].update(item)
                state["tool"].update(input=item.get("action"), output={
                    "provider_call": state["item"].copy(),
                    "received_events": list(state["events"])})

    def close(self):
        for state in self.calls.values():
            if not state["ended"]:
                if state["item"].get("status") not in ("completed", "failed", "incomplete"):
                    state["tool"].update(level="WARNING",
                                         status_message="Tool completion not observed")
                state["tool"].end()
                state["ended"] = True


def search_evidence(response):
    """Keep returned evidence, never reconstruct unreturned queries or pages."""
    body = response.model_dump(mode="json")
    calls = [item for item in body.get("output", [])
             if item.get("type") == "web_search_call"]
    annotations = [annotation
                   for item in body.get("output", [])
                   if item.get("type") == "message"
                   for content in item.get("content", [])
                   if content.get("type") == "output_text"
                   for annotation in content.get("annotations", [])]
    urls = []
    for citation in body.get("citations") or []:
        if isinstance(citation, str) and citation.startswith("https://"):
            urls.append(citation)
    for annotation in annotations:
        citation = annotation.get("url_citation", annotation)
        url = citation.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            urls.append(url)
    # Citations alone are not proof that a search ran. A reported call must
    # also have completed. Failed/incomplete calls remain visible as evidence.
    completed = any(call.get("status") == "completed" for call in calls)
    return {
        "answer": response.output_text,
        "search_status": "observed_completed_call" if completed else "not_verified",
        "returned_search_calls": calls,
        "citation_annotations": annotations,
        "source_urls": list(dict.fromkeys(urls)),
        "provider_tool_usage": body.get("server_side_tool_usage"),
        "visibility_limit": "Only provider-returned records are available. "
                            "Missing search queries or page bodies are not inferred.",
    }


def request_key(name, label):
    value = os.environ.get(name, "").strip()
    if not value:
        if not sys.stdin.isatty():
            raise RuntimeError("Run in Terminal to enter missing credentials.")
        value = getpass(label + " (hidden): ").strip()
    if not value:
        raise RuntimeError("A required credential was left empty.")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Offline setup check")
    args = parser.parse_args()
    from dotenv import load_dotenv

    # Use this script's file regardless of the terminal's current directory.
    # Explicit environment variables take precedence over .env values.
    load_dotenv(ROOT / ".env", override=False, interpolate=False)
    settings = json.loads((ROOT / "settings.json").read_text())
    settings["langfuse_base_url"] = (
        os.environ.get("LANGFUSE_BASE_URL", "").strip()
        or settings["langfuse_base_url"]
    )
    from importlib.metadata import version
    from langfuse import Langfuse
    from openai import OpenAI

    if args.check:
        print("Offline check passed; no API calls made.")
        print("Python:", sys.version.split()[0])
        print("Langfuse:", version("langfuse"), "OpenAI SDK:", version("openai"))
        print("Prompt:", settings["prompt_name"], "version", settings["prompt_version"])
        print("Dataset:", settings["dataset_name"])
        print("Model:", settings["model"], "| Tool: provider-hosted web_search")
        print("Local .env:", "found" if (ROOT / ".env").is_file() else "not found")
        for key in ("XAI_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
            print(key + ":", "set" if os.environ.get(key, "").strip() else "missing")
        print("Credential authentication has not been tested.")
        return 0

    print("First lesson: ONE question; Grok built-in web search.", flush=True)
    print("Returned search events, tool records and answer will be sent to Langfuse.")
    print("No automatic quality scoring. Model/search usage is billable.")
    public_key = request_key("LANGFUSE_PUBLIC_KEY", "Langfuse Public Key")
    secret_key = request_key("LANGFUSE_SECRET_KEY", "Langfuse Secret Key")
    langfuse = Langfuse(public_key=public_key, secret_key=secret_key,
                        base_url=settings["langfuse_base_url"],
                        environment="web-search-learning")
    client = None
    try:
        if not langfuse.auth_check():
            raise RuntimeError("Langfuse authentication failed. No model call made.")
        prompt = langfuse.get_prompt(settings["prompt_name"],
                                    version=settings["prompt_version"], type="chat")
        dataset = langfuse.get_dataset(settings["dataset_name"])
        active_items = [item for item in dataset.items
                        if str(item.status).upper().split(".")[-1] != "ARCHIVED"]
        if len(active_items) != 1 or len(dataset.items) != 1:
            raise RuntimeError("This lesson requires exactly ONE active dataset item.")
        question = active_items[0].input.get("question")
        if not isinstance(question, str) or not question.strip():
            raise RuntimeError("Dataset input must contain a nonempty question.")
        # Show the exact public question before credentials for the provider.
        print("\nQuestion:\n" + question, flush=True)
        xai_key = request_key("XAI_API_KEY", "xAI API Key")
        client = OpenAI(api_key=xai_key, base_url="https://api.x.ai/v1",
                        timeout=settings["timeout_seconds"], max_retries=0)
        batch = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_name = "grok-builtin-web-" + batch
        outcomes = []

        def task(*, item, **kwargs):
            messages = prompt.compile(question=item.input["question"])
            trace_url = langfuse.get_trace_url()
            with langfuse.start_as_current_observation(
                name="grok-builtin-web-search", as_type="generation",
                model=settings["model"], prompt=prompt, input=messages,
                model_parameters={"reasoning_effort": settings["reasoning_effort"],
                                  "reasoning_summary": settings.get("reasoning_summary", "detailed"),
                                  "max_output_tokens": settings["max_output_tokens"],
                                  "automatic_retries": 0},
                metadata={"backend": "xai-built-in-web-search",
                          "tool_configuration": [{"type": "web_search"}]},
            ) as generation:
                recorder = SearchTraceRecorder(generation)
                reasoning = ReasoningSummaryRecorder(generation)
                try:
                    response = None
                    with client.responses.create(
                        model=settings["model"], input=messages,
                        tools=[{"type": "web_search"}],
                        include=["web_search_call.action.sources"], stream=True,
                        reasoning={"effort": settings["reasoning_effort"],
                                   "summary": settings.get("reasoning_summary", "detailed")},
                        max_output_tokens=settings["max_output_tokens"],
                    ) as stream:
                        for event in stream:
                            recorder.record(event)
                            reasoning.record(event)
                            if event.type in ("response.completed", "response.incomplete",
                                              "response.failed"):
                                response = event.response
                    if response is None:
                        raise RuntimeError("Stream ended without a final response")
                    recorder.reconcile(response)
                    reasoning.reconcile(response)
                    evidence = search_evidence(response)
                    evidence["search_stream_events"] = recorder.events
                    evidence["reasoning_summaries"] = reasoning.summaries
                    evidence["reasoning_summary_status"] = (
                        "returned" if reasoning.summaries else "not_returned")
                    if response.status != "completed" or not evidence["answer"].strip():
                        generation.update(output=evidence, level="ERROR",
                                          status_message="No completed final answer")
                        raise RuntimeError("No completed final answer")
                    usage = response.usage
                    generation.update(
                        output=evidence,
                        usage_details={"input": usage.input_tokens,
                                       "output": usage.output_tokens,
                                       "total": usage.total_tokens} if usage else None,
                        metadata={"provider_response_id": response.id,
                                  "search_status": evidence["search_status"]},
                    )
                    # Save public question, answer and returned evidence only.
                    # Only disclosed summaries; no encrypted reasoning or credentials.
                    output = {"run_name": run_name, "trace_url": trace_url,
                              "prompt_version": prompt.version,
                              "settings": settings, "question": item.input["question"],
                              "response_status": response.status,
                              "usage": usage.model_dump() if usage else None,
                              **evidence}
                    (ROOT / "runs").mkdir(exist_ok=True)
                    (ROOT / "runs" / (run_name + ".json")).write_text(
                        json.dumps(output, ensure_ascii=False, indent=2) + "\n")
                    outcomes.append(evidence)
                    print("\n" + evidence["answer"], flush=True)
                    print("\nSearch evidence:", evidence["search_status"], flush=True)
                    if trace_url:
                        print("Trace:", trace_url, flush=True)
                    return evidence
                except Exception as error:
                    # Do not echo raw errors that may contain request details.
                    generation.update(level="ERROR", status_message=type(error).__name__,
                                      output={"search_stream_events": recorder.events,
                                              "reasoning_summaries": reasoning.summaries,
                                              "execution_status": "failed"})
                    raise RuntimeError("Model execution failed: " + type(error).__name__) from None
                finally:
                    recorder.close()
                    reasoning.close()

        result = dataset.run_experiment(
            name="Built-in Web Search Lesson", run_name=run_name,
            description="One question, manual review. No quality scores generated.",
            task=task, max_concurrency=1,
            metadata={"backend": "xai-built-in-web-search",
                      "prompt_version": str(prompt.version), "model": settings["model"]},
        )
        print(result.format())
        if not outcomes:
            print("Execution failed. Inspect the Langfuse trace; quality remains unscored.")
            return 1
        if outcomes[0]["search_status"] != "observed_completed_call":
            print("Search was NOT verified. Do not mark the search step as passed.")
            return 2
        print("Next: open the experiment in Langfuse and review answer + citations together.")
        return 0
    finally:
        langfuse.flush()
        if client is not None:
            client.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nStopped.")
        raise SystemExit(130)
    except Exception as error:
        print("Setup/execution stopped:", type(error).__name__)
        print("Check project keys, prompt version and dataset. Keys were not saved.")
        raise SystemExit(1)

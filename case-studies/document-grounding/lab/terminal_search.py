"""Ask Grok questions in Terminal; send real search records to Langfuse Tracing."""
import argparse
import json
import os

from run_builtin import (ROOT, ReasoningSummaryRecorder, SearchTraceRecorder,
                         request_key, search_evidence)


def ask(question, *, langfuse, client, prompt, settings):
    messages = prompt.compile(question=question)
    # Keep the managed prompt unchanged; record this terminal-specific instruction
    # alongside it so the actual model input stays inspectable.
    messages.insert(1, {"role": "system", "content":
        "For this terminal session, write the answer in English even if the user "
        "asks in another language."})
    with langfuse.start_as_current_observation(
        name="terminal-grok-web-search", as_type="span", input={"question": question},
        metadata={"interface": "terminal", "independent_question": True},
    ) as root:
        trace_url = langfuse.get_trace_url()
        print("\nTrace:", trace_url, flush=True)
        print("Grok is searching…", flush=True)
        try:
            with langfuse.start_as_current_observation(
                name="grok-builtin-web-search", as_type="generation",
                model=settings["model"], prompt=prompt, input=messages,
                model_parameters={"reasoning_effort": settings["reasoning_effort"],
                                  "reasoning_summary": settings.get("reasoning_summary", "detailed"),
                                  "max_output_tokens": settings["max_output_tokens"],
                                  "automatic_retries": 0},
                metadata={"backend": "xai-built-in-web-search",
                          "tool_configuration": [{"type": "web_search"}],
                          "response_language": "English"},
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
                            if event.type == "error":
                                raise RuntimeError("Provider stream error")
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
                    usage = response.usage
                    generation.update(
                        output=evidence,
                        usage_details={"input": usage.input_tokens,
                                       "output": usage.output_tokens,
                                       "total": usage.total_tokens} if usage else None,
                        metadata={"provider_response_id": response.id,
                                  "search_status": evidence["search_status"]},
                    )
                    if response.status != "completed" or not evidence["answer"].strip():
                        raise RuntimeError("No completed final answer")
                except BaseException as error:
                    generation.update(level="ERROR", status_message=type(error).__name__,
                                      output={"search_stream_events": recorder.events,
                                              "reasoning_summaries": reasoning.summaries,
                                              "execution_status": "interrupted_or_failed"})
                    raise
                finally:
                    recorder.close()
                    reasoning.close()
            root.update(output=evidence)
            print("\nAnswer:\n" + evidence["answer"], flush=True)
            count = len(evidence["returned_search_calls"])
            print(f"\nReturned search calls: {count}", flush=True)
            if reasoning.summaries:
                print(f"Reasoning summaries: {len(reasoning.summaries)} — inspect reasoning-summary in the trace.")
            else:
                print("The API did not return a readable reasoning summary for this run.")
            if evidence["search_status"] != "observed_completed_call":
                print("No completed search call was verified.", flush=True)
            print("Langfuse Tracing:", trace_url, flush=True)
            return evidence
        except BaseException as error:
            root.update(level="ERROR", status_message=type(error).__name__,
                        output={"execution_status": "interrupted_or_failed"})
            raise


def main():
    from dotenv import load_dotenv
    from langfuse import Langfuse
    from openai import OpenAI

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Offline settings check")
    parser.add_argument("--question", help="Ask one question and exit")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False, interpolate=False)
    settings = json.loads((ROOT / "settings.json").read_text())
    settings["langfuse_base_url"] = (os.environ.get("LANGFUSE_BASE_URL", "").strip()
                                     or settings["langfuse_base_url"])
    if args.check:
        missing = [key for key in ("XAI_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
                   if not os.environ.get(key, "").strip()]
        print("Terminal question → Grok built-in search → Langfuse Tracing")
        print("Credential setup:", "ready" if not missing else "missing: " + ", ".join(missing))
        print("No API calls. Authentication and live search have not been tested by this check.")
        return 1 if missing else 0
    if args.question is not None and not args.question.strip():
        parser.error("--question must not be empty")

    langfuse = Langfuse(
        public_key=request_key("LANGFUSE_PUBLIC_KEY", "Langfuse Public Key"),
        secret_key=request_key("LANGFUSE_SECRET_KEY", "Langfuse Secret Key"),
        base_url=settings["langfuse_base_url"], environment="web-search-learning",
    )
    client = None
    try:
        if not langfuse.auth_check():
            raise RuntimeError("Langfuse authentication failed")
        prompt = langfuse.get_prompt(settings["prompt_name"],
                                    version=settings["prompt_version"], type="chat")
        client = OpenAI(api_key=request_key("XAI_API_KEY", "xAI API Key"),
                        base_url="https://api.x.ai/v1",
                        timeout=settings["timeout_seconds"], max_retries=0)
        print("Grok web search terminal | Model: " + settings["model"])
        print("Each question creates an independent trace. Previous questions are not carried forward.")
        print("API usage is billable. Exit: /exit or Ctrl+C")
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
                ask(question, langfuse=langfuse, client=client, prompt=prompt, settings=settings)
            except Exception as error:
                # Provider exception strings can contain request data. Print only
                # the class and HTTP code, never raw exception bodies or keys.
                status = getattr(error, "status_code", None)
                print("Execution failed:", type(error).__name__,
                      f"(HTTP {status})" if status else "")
                print("Inspect the trace, credentials, model and usage limits.")
                if args.question is not None:
                    return 1
            finally:
                langfuse.flush()
            if args.question is not None:
                break
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
        print("Setup failed:", type(error).__name__)
        print("Check .env credentials, Langfuse connection and prompt settings.")
        raise SystemExit(1)

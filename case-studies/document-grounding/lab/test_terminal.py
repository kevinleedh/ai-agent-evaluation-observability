"""Offline SSE transport checks: no credentials, model calls or trace uploads."""
from contextlib import redirect_stdout
import io
import json
import unittest
from unittest.mock import MagicMock

import httpx
from openai import OpenAI

from terminal_search import ask


class TerminalTests(unittest.TestCase):
    def run_question(self, *, completed=True):
        call = {"type": "web_search_call", "id": "ws_1", "status": "in_progress"}
        done = {**call, "status": "completed", "action": {
            "type": "search", "query": "official docs",
            "sources": [{"type": "url", "url": "https://example.com/docs"}]}}
        events = [
            {"type": "response.reasoning_summary_text.delta", "sequence_number": 0,
             "item_id": "rs_1", "output_index": 1, "summary_index": 0,
             "delta": "I will check official documentation."},
            {"type": "response.output_item.added", "sequence_number": 1,
             "output_index": 0, "item": call},
        ]
        if completed:
            events.extend([
                {"type": "response.output_item.done", "sequence_number": 2,
                 "output_index": 0, "item": done},
                {"type": "response.completed", "sequence_number": 3, "response": {
                    "id": "resp_test", "object": "response", "status": "completed",
                    "created_at": 1, "model": "test-model", "usage": None,
                    "output": [done, {"type": "reasoning", "id": "rs_1",
                        "summary": [{"type": "summary_text", "text": "I will check official documentation."}],
                        "encrypted_content": "ENCRYPTED_SENTINEL"},
                        {"type": "message", "id": "msg_1",
                        "role": "assistant", "status": "completed", "content": [{
                            "type": "output_text", "text": "This is a test answer.",
                            "annotations": []}]}],
                }},
            ])
        def transport(request):
            body = json.loads(request.content)
            self.assertEqual(body["tools"], [{"type": "web_search"}])
            self.assertTrue(body["stream"])
            self.assertEqual(body["reasoning"]["summary"], "detailed")
            self.assertEqual(body["include"], ["web_search_call.action.sources"])
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                text="".join("data: " + json.dumps(event) + "\n\n" for event in events)
                     + "data: [DONE]\n\n")
        lf = MagicMock()
        root, generation = MagicMock(), MagicMock()
        contexts = [MagicMock(), MagicMock()]
        contexts[0].__enter__.return_value = root
        contexts[1].__enter__.return_value = generation
        lf.start_as_current_observation.side_effect = contexts
        lf.get_trace_url.return_value = "https://example.com/trace/test"
        prompt = MagicMock()
        prompt.compile.return_value = [{"role": "system", "content": "Search first."},
                                       {"role": "user", "content": "Question"}]
        output = io.StringIO()
        with OpenAI(api_key="offline-test-key", base_url="https://example.invalid/v1",
                    http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
            with redirect_stdout(output):
                if completed:
                    evidence = ask("Question", langfuse=lf, client=client, prompt=prompt,
                                   settings={"model": "test-model", "reasoning_effort": "low",
                                             "max_output_tokens": 100})
                    self.assertEqual(evidence["search_status"], "observed_completed_call")
                else:
                    with self.assertRaises(RuntimeError):
                        ask("Question", langfuse=lf, client=client, prompt=prompt,
                            settings={"model": "test-model", "reasoning_effort": "low",
                                      "max_output_tokens": 100})
        return lf, root, generation, output.getvalue()

    def test_actual_sdk_parses_stream_and_records_question_tools_answer(self):
        lf, root, generation, text = self.run_question()
        self.assertEqual(lf.start_as_current_observation.call_args_list[0].kwargs["input"],
                         {"question": "Question"})
        self.assertEqual(generation.start_observation.call_count, 2)
        self.assertIn("This is a test answer.", text)
        self.assertIn("https://example.com/trace/test", text)
        self.assertEqual(root.update.call_args.kwargs["output"]["answer"], "This is a test answer.")
        result = root.update.call_args.kwargs["output"]
        self.assertEqual(result["reasoning_summaries"][0]["text"], "I will check official documentation.")
        self.assertEqual(result["reasoning_summary_status"], "returned")
        self.assertNotIn("ENCRYPTED_SENTINEL", str(result))

    def test_interrupted_stream_keeps_events_and_marks_error(self):
        _, root, generation, _ = self.run_question(completed=False)
        self.assertEqual(root.update.call_args.kwargs["level"], "ERROR")
        saved = generation.update.call_args.kwargs["output"]["search_stream_events"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(len(generation.update.call_args.kwargs["output"]["reasoning_summaries"]), 1)
        self.assertEqual(generation.start_observation.return_value.end.call_count, 2)


if __name__ == "__main__":
    unittest.main()
